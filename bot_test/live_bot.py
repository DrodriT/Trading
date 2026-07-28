"""
Bot EN VIVO — Synapse Trail Pro sobre Bitget (cuenta DEMO), aislado,
apalancamiento automático por riesgo, cierre parcial 33/33/resto,
break-even tras TP1, y comandos instantáneos por Telegram
(/posiciones, /stats).

⚠️ Antes de dejarlo corriendo solo, lee la cabecera de exchange_client.py.

Uso:
    python3 live_bot.py --dry-run     # no manda órdenes, solo simula/loguea
    python3 live_bot.py               # opera de verdad (cuenta DEMO)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

import live_config as config
import exchange_client as ex_client
import risk_sizing
from telegram_listener import TelegramCommandListener, send_telegram
from strategy import (
    compute_indicators, compute_synapse_trail, compute_regime,
    detect_raw_signal, compute_quality_score, build_risk_levels,
)
from indicators import add_ema, get_trend_vs_ema200

DRY_RUN = "--dry-run" in sys.argv


# ══════════════════════════════════════════════════════════
# Estado
# ══════════════════════════════════════════════════════════

def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {"positions": {}, "stats": _default_stats()}


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _default_stats():
    return {
        "total_signals": 0, "buy_signals": 0, "sell_signals": 0,
        "grade_a": 0, "grade_b": 0, "grade_c": 0,
        "sl_hits": 0, "tp1_hits": 0, "tp2_hits": 0, "tp3_hits": 0,
        "flips": 0, "wins": 0, "losses": 0, "be_saves": 0, "r_sum": 0.0,
    }


def get_stats(state):
    stats = state.setdefault("stats", {})
    for k, v in _default_stats().items():
        stats.setdefault(k, v)
    return stats


# ══════════════════════════════════════════════════════════
# Datos de mercado
# ══════════════════════════════════════════════════════════

def fetch_ohlcv(exchange, symbol, timeframe, limit):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


# ══════════════════════════════════════════════════════════
# Apertura de posición — cálculo de riesgo + órdenes reales
# ══════════════════════════════════════════════════════════

def open_live_position(exchange, symbol, direction, entry_price, atr_val, equity, context):
    risk = build_risk_levels(entry_price, atr_val, direction, config.RISK_PRESET)
    sl_price = risk["sl"]
    tp_prices = [tp["price"] for tp in risk["tps"]]
    tp_rr = [tp["rr"] for tp in risk["tps"]]

    plan = risk_sizing.compute_position_plan(equity, entry_price, sl_price)
    tp_quantities = risk_sizing.split_tp_quantities(plan["contracts"])

    msg_header = (
        f"🟢 *{symbol.split(':')[0].replace('/', '')} | "
        f"{'LONG' if direction == 'ALCISTA' else 'SHORT'}*  ·  "
        f"Score {context['score']} ({context['grade']})\n\n"
        f"💰 Entrada: `{entry_price:.4f}` | Apalancamiento: `{plan['leverage']}x` "
        f"(margen ~{plan['margin']:.2f} USDT)\n"
        f"🔴 Stop Loss: `{sl_price:.4f}`\n\n"
        f"🎯 TP1: `{tp_prices[0]:.4f}` · RR {tp_rr[0]} · {tp_quantities[0]:.4f} contratos\n"
        f"🎯 TP2: `{tp_prices[1]:.4f}` · RR {tp_rr[1]} · {tp_quantities[1]:.4f} contratos\n"
        f"🎯 TP3: `{tp_prices[2]:.4f}` · RR {tp_rr[2]} · {tp_quantities[2]:.4f} contratos\n\n"
        f"📊 Régimen: {context['regime_label']} ({context['regime_score']:.0f}/100)"
    )

    if DRY_RUN:
        print(f"[DRY-RUN] Abriría {symbol} {direction} — {msg_header}")
        send_telegram("🧪 (DRY-RUN, no se mandó orden real)\n\n" + msg_header)
        entry_order = {"average": entry_price, "id": "dry-run"}
        sl_order_id = tp1_order_id = tp2_order_id = tp3_order_id = None
    else:
        ex_client.prepare_market(exchange, symbol, plan["leverage"])
        entry_order = ex_client.open_position(exchange, symbol, direction, plan["contracts"])
        filled_price = entry_order.get("average") or entry_order.get("price") or entry_price

        sl_order = ex_client.place_stop_loss(exchange, symbol, direction, plan["contracts"], sl_price)
        tp1_order = ex_client.place_take_profit(exchange, symbol, direction, tp_quantities[0], tp_prices[0])
        tp2_order = ex_client.place_take_profit(exchange, symbol, direction, tp_quantities[1], tp_prices[1])
        tp3_order = ex_client.place_take_profit(exchange, symbol, direction, tp_quantities[2], tp_prices[2])

        sl_order_id = sl_order.get("id")
        tp1_order_id = tp1_order.get("id")
        tp2_order_id = tp2_order.get("id")
        tp3_order_id = tp3_order.get("id")
        send_telegram(msg_header)

    return {
        "dir": direction,
        "entry": entry_price,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "sl": sl_price,
        "tps": tp_prices,
        "tp_rr": tp_rr,
        "tp_quantities": tp_quantities,
        "contracts_total": plan["contracts"],
        "leverage": plan["leverage"],
        "margin": plan["margin"],
        "sl_order_id": sl_order_id,
        "tp_order_ids": [tp1_order_id, tp2_order_id, tp3_order_id],
        "tp_reached": [False, False, False],
        "be_active": False,
        "grade": context["grade"], "score": context["score"],
        "regime_label": context["regime_label"], "regime_score": context["regime_score"],
    }


def close_remaining_market(exchange, symbol, direction, remaining_contracts):
    """Cierra a mercado lo que quede (usado en flip o cierre manual)."""
    if remaining_contracts <= 0:
        return None
    close_side = "sell" if direction == "ALCISTA" else "buy"
    amount = exchange.amount_to_precision(symbol, remaining_contracts)
    return exchange.create_order(symbol, "market", close_side, float(amount), None, {"reduceOnly": True})


# ══════════════════════════════════════════════════════════
# Escaneo de señales (símbolos SIN posición abierta)
# ══════════════════════════════════════════════════════════

def scan_for_signals(exchange, state):
    positions = state.setdefault("positions", {})
    stats = get_stats(state)

    for symbol in config.SYMBOLS:
        if symbol in positions:
            continue  # ya hay posición viva en este símbolo
        try:
            limit = max(config.REGIME_LEN, config.TRAIL_LEN) + 100
            df = fetch_ohlcv(exchange, symbol, config.TIMEFRAME, limit)
            df = compute_indicators(
                df, config.ATR_LEN, config.TRAIL_LEN, config.ADX_PERIOD,
                config.CHOPPINESS_LEN, config.REGIME_LEN, config.RSI_PERIOD,
                config.VOLUME_MA_PERIOD
            )
            df = compute_synapse_trail(
                df, config.ATR_LEN, config.TRAIL_LEN, config.BASE_MULT,
                config.USE_ADAPTIVE_MULT, config.USE_RATCHET
            )
            df = compute_regime(df)

            last_candle_time = df.iloc[-1]["datetime"].isoformat()
            already = state.get(f"{symbol}_last_candle") == last_candle_time
            raw_signal = None if already else detect_raw_signal(df)
            state[f"{symbol}_last_candle"] = last_candle_time
            if not raw_signal:
                continue

            htf_bull, htf_bear = None, None
            if config.USE_HTF_FILTER:
                df_htf = fetch_ohlcv(exchange, symbol, config.CONFIRM_TIMEFRAME, config.HTF_EMA_PERIOD + 50)
                df_htf = add_ema(df_htf, config.HTF_EMA_PERIOD, f"EMA{config.HTF_EMA_PERIOD}")
                htf_bull, htf_bear = get_trend_vs_ema200(df_htf, config.HTF_EMA_PERIOD)

            has_volume = df["volume"].tail(20).sum() > 0
            is_choppy = bool(df.iloc[-1]["REGIME_is_choppy"])
            is_trending = bool(df.iloc[-1]["REGIME_is_trending"])
            is_long = raw_signal == "ALCISTA"

            score, grade, breakdown = compute_quality_score(
                df, raw_signal, htf_bull, htf_bear, config.USE_HTF_FILTER,
                config.USE_VOLUME_FILTER, config.VOLUME_THRESHOLD, has_volume
            )
            passes_quality = score >= config.MIN_QUALITY_SCORE
            passes_choppy = not (config.SKIP_CHOPPY_SIGNALS and is_choppy)
            htf_valid = config.USE_HTF_FILTER and htf_bull is not None and htf_bear is not None
            htf_against = htf_valid and ((is_long and htf_bear) or (not is_long and htf_bull))
            passes_htf = not (config.HTF_HARD_FILTER and htf_against)
            passes_regime = not config.REQUIRE_TRENDING_REGIME or is_trending

            if not (passes_quality and passes_choppy and passes_htf and passes_regime):
                continue

            regime_label = "Trending" if is_trending else ("Choppy" if is_choppy else "Mixed")
            entry_price = float(df.iloc[-1]["close"])
            atr_val = float(df.iloc[-1]["ATR"])
            equity = ex_client.get_equity_usdt(exchange) if not DRY_RUN else 1000.0  # 1000 ficticio en dry-run

            context = {
                "grade": grade, "score": score,
                "regime_label": regime_label, "regime_score": float(df.iloc[-1]["REGIME_score"]),
            }
            pos = open_live_position(exchange, symbol, raw_signal, entry_price, atr_val, equity, context)
            positions[symbol] = pos

            stats["total_signals"] += 1
            stats["buy_signals" if raw_signal == "ALCISTA" else "sell_signals"] += 1
            stats[f"grade_{grade.lower()}"] += 1

        except Exception as e:
            print(f"[ERROR] scan_for_signals({symbol}): {e}")


# ══════════════════════════════════════════════════════════
# Monitorización de posiciones abiertas — detecta fills
# ══════════════════════════════════════════════════════════

def classify_and_close(state, symbol, pos, tp_hit_flags, closed_by):
    """
    tp_hit_flags: lista [tp1_ok, tp2_ok, tp3_ok] con lo realmente
    alcanzado. R-multiple ponderado por la fracción REAL cerrada en
    cada tramo (no se asume 1/3 fijo, se usa tp_quantities real).
    """
    stats = get_stats(state)
    total = pos["contracts_total"] or 1.0
    tp1_ok, tp2_ok, tp3_ok = tp_hit_flags

    if tp1_ok:
        r = 0.0
        for i, ok in enumerate(tp_hit_flags):
            if ok:
                frac = pos["tp_quantities"][i] / total
                r += frac * pos["tp_rr"][i]
        is_win = True
        is_be_save = closed_by == "sl" and pos["be_active"]
    else:
        r = -1.0
        is_win = False
        is_be_save = False

    stats["wins" if is_win else "losses"] += 1
    stats["be_saves"] += 1 if is_be_save else 0
    stats["r_sum"] += r
    if closed_by == "sl":
        stats["sl_hits"] += 1
    if closed_by == "flip":
        stats["flips"] += 1

    closed_trades = stats["wins"] + stats["losses"]
    win_rate = stats["wins"] / closed_trades * 100 if closed_trades else 0
    avg_r = stats["r_sum"] / closed_trades if closed_trades else 0

    icon = "💠" if tp3_ok else ("🔒" if is_be_save else "🛑")
    reason = "TP3 alcanzado" if tp3_ok else ("BE stop-out" if is_be_save else "SL alcanzado")
    sym_clean = symbol.split(":")[0].replace("/", "")
    send_telegram(
        f"{icon} *{sym_clean}* — {reason}. Trade cerrado.\n"
        f"Entrada: `{pos['entry']:.4f}`\n"
        f"Resultado: {'✅ GANADORA' if is_win else '❌ PERDEDORA'} ({r:+.2f}R)\n"
        f"Grado: *{pos['grade']}* ({pos['score']}/100) | Régimen: {pos['regime_label']} ({pos['regime_score']:.0f}/100)\n\n"
        f"📈 Cerradas: {closed_trades} | WR {win_rate:.1f}% | R medio {avg_r:+.2f} "
        f"| BE saves: {stats['be_saves']} | Flips: {stats['flips']}"
    )
    state["positions"].pop(symbol, None)


def monitor_positions(exchange, state):
    if DRY_RUN:
        return  # en dry-run no hay órdenes reales que consultar
    positions = state.setdefault("positions", {})
    for symbol, pos in list(positions.items()):
        try:
            sl_order = ex_client.fetch_order_status(exchange, symbol, pos["sl_order_id"])
            sl_filled = bool(sl_order) and sl_order.get("status") == "closed"

            tp_filled = [False, False, False]
            for i, oid in enumerate(pos["tp_order_ids"]):
                if pos["tp_reached"][i] or not oid:
                    tp_filled[i] = pos["tp_reached"][i]
                    continue
                order = ex_client.fetch_order_status(exchange, symbol, oid)
                tp_filled[i] = bool(order) and order.get("status") == "closed"

            # --- TP1 recién tocado -> mover SL a BE ---
            if tp_filled[0] and not pos["tp_reached"][0]:
                pos["tp_reached"][0] = True
                if config.USE_BREAK_EVEN and not pos["be_active"]:
                    ex_client.cancel_order_safe(exchange, symbol, pos["sl_order_id"])
                    remaining = pos["contracts_total"] - pos["tp_quantities"][0]
                    new_sl = ex_client.place_stop_loss(exchange, symbol, pos["dir"], remaining, pos["entry"])
                    pos["sl_order_id"] = new_sl.get("id")
                    pos["sl"] = pos["entry"]
                    pos["be_active"] = True
                sym_clean = symbol.split(":")[0].replace("/", "")
                send_telegram(
                    f"✅ *{sym_clean}* — TP1 alcanzado (`{pos['tps'][0]:.4f}` · RR {pos['tp_rr'][0]}).\n"
                    + (f"🔒 SL movido a BE (`{pos['entry']:.4f}`).\n" if pos["be_active"] else "")
                    + f"Grado: *{pos['grade']}* ({pos['score']}/100) | Régimen: {pos['regime_label']} ({pos['regime_score']:.0f}/100)"
                )

            if tp_filled[1] and not pos["tp_reached"][1]:
                pos["tp_reached"][1] = True
                sym_clean = symbol.split(":")[0].replace("/", "")
                send_telegram(
                    f"🔥 *{sym_clean}* — TP2 alcanzado (`{pos['tps'][1]:.4f}` · RR {pos['tp_rr'][1]}). Runner hacia TP3.\n"
                    f"Grado: *{pos['grade']}* ({pos['score']}/100) | Régimen: {pos['regime_label']} ({pos['regime_score']:.0f}/100)"
                )

            # --- Cierre: TP3 o SL ---
            if tp_filled[2]:
                ex_client.cancel_order_safe(exchange, symbol, pos["sl_order_id"])
                classify_and_close(state, symbol, pos, tp_filled, closed_by="tp3")
            elif sl_filled:
                for oid in pos["tp_order_ids"]:
                    ex_client.cancel_order_safe(exchange, symbol, oid)
                classify_and_close(state, symbol, pos, pos["tp_reached"], closed_by="sl")

        except Exception as e:
            print(f"[ERROR] monitor_positions({symbol}): {e}")


# ══════════════════════════════════════════════════════════
# Comandos de Telegram
# ══════════════════════════════════════════════════════════

def build_positions_message(state):
    positions = state.get("positions", {})
    if not positions:
        return "📭 No hay posiciones abiertas ahora mismo."
    lines = [f"📋 *Posiciones abiertas* ({len(positions)}):\n"]
    for symbol, pos in positions.items():
        sym_clean = symbol.split(":")[0].replace("/", "")
        dir_label = "LONG" if pos["dir"] == "ALCISTA" else "SHORT"
        tp_status = " ".join(
            f"TP{i+1}{'✅' if r else '⏳'}" for i, r in enumerate(pos["tp_reached"])
        )
        lines.append(
            f"• *{sym_clean}* {dir_label} · Entrada `{pos['entry']:.4f}` · "
            f"SL `{pos['sl']:.4f}`{' (BE)' if pos['be_active'] else ''} · "
            f"{pos['leverage']}x · {tp_status}"
        )
    return "\n".join(lines)


def build_stats_message(state):
    stats = get_stats(state)
    closed = stats["wins"] + stats["losses"]
    win_rate = stats["wins"] / closed * 100 if closed else 0
    avg_r = stats["r_sum"] / closed if closed else 0
    return (
        f"📊 *Estadísticas de sesión*\n\n"
        f"Señales: {stats['total_signals']} (A:{stats['grade_a']} B:{stats['grade_b']} C:{stats['grade_c']})\n"
        f"Cerradas: {closed} | WR: {win_rate:.1f}% | R medio: {avg_r:+.2f}\n"
        f"W/L: {stats['wins']}/{stats['losses']} | BE saves: {stats['be_saves']} | Flips: {stats['flips']}\n"
        f"Hits — SL: {stats['sl_hits']} TP1: {stats['tp1_hits']} TP2: {stats['tp2_hits']} TP3: {stats['tp3_hits']}\n"
        f"Posiciones abiertas: {len(state.get('positions', {}))}"
    )


# ══════════════════════════════════════════════════════════
# Bucle principal
# ══════════════════════════════════════════════════════════

def main():
    print(f"[{config.STRATEGY_LABEL}] Iniciado {datetime.now(timezone.utc).isoformat()} "
          f"{'(DRY-RUN)' if DRY_RUN else '(DEMO — órdenes reales)'}")

    exchange = ex_client.make_exchange()
    state = load_state()

    listener = TelegramCommandListener(poll_interval_seconds=2.0)
    listener.register("/posiciones", lambda: build_positions_message(state))
    listener.register("/stats", lambda: build_stats_message(state))
    listener.start()

    send_telegram(
        f"[{config.STRATEGY_LABEL}]\n▶️ Bot iniciado "
        f"{'en DRY-RUN (sin órdenes reales)' if DRY_RUN else 'operando en cuenta DEMO'}."
    )

    last_scan = 0.0
    try:
        while True:
            monitor_positions(exchange, state)

            now = time.time()
            if now - last_scan >= config.SCAN_INTERVAL_SECONDS:
                scan_for_signals(exchange, state)
                last_scan = now

            save_state(state)
            time.sleep(config.POSITION_POLL_SECONDS)
    except KeyboardInterrupt:
        listener.stop()
        save_state(state)
        print("Bot detenido por el usuario.")


if __name__ == "__main__":
    main()
