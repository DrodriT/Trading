"""
Bot de alertas — Estrategia "Rodri v1.0" (ensemble multi-estrategia)

Motor de 6 estrategias (SMC_REVERSAL, BREAKOUT, TREND_PULLBACK,
RSI_DIVERGENCE, VP_MEAN_REVERT, LIQUIDITY_GRAB) combinadas en un score +
probabilidad (ver strategy_rodri.py), con:
  - Gestión de posiciones multi-trade (máx N simultáneas, 1 por activo)
  - Cooldown por símbolo tras cerrar un trade
  - Señales "rojas" de baja confianza (tamaño reducido, TP capado, límite diario)
  - Threshold de score dinámico según rachas de resultados recientes
  - Apalancamiento sugerido según volatilidad

Es una versión NUEVA e independiente del bot "Synapse" (bot.py): usa su
propio archivo de estado (state_rodri.json) y no modifica nada del bot
original.

Uso:
    python3 bot_rodri.py            # corre en bucle
    python3 bot_rodri.py --once     # ejecuta una sola pasada (GitHub Actions)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import ccxt
import pandas as pd
import requests

import config_rodri as config
import bitget_executor as bx
from strategy_rodri import (
    compute_base_indicators, compute_ensemble_signal, suggest_leverage,
    cap_tp_at_r, build_risk_levels
)


# ══════════════════════════════════════════════════════════
# Persistencia de estado
# ══════════════════════════════════════════════════════════

def default_state():
    return {
        "positions": {},
        "cooldowns": {},
        "red_signals_today": {"date": None, "count": 0},
        "recent_results": [],
        "dynamic_min_score": config.MIN_SCORE,
        "trade_log": [],
        "stats": {},
        "last_daily_summary_date": None,
    }


def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            state = json.load(f)
        for k, v in default_state().items():
            state.setdefault(k, v)
        return state
    return default_state()


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_stats(state):
    stats = state.setdefault("stats", {})
    defaults = {
        "total_signals": 0, "normal_signals": 0, "red_signals": 0,
        "long_signals": 0, "short_signals": 0,
        "sl_hits": 0, "tp1_hits": 0, "tp2_hits": 0, "tp3_hits": 0,
        "flips": 0, "wins": 0, "losses": 0, "be_saves": 0, "r_sum": 0.0,
    }
    for k, v in defaults.items():
        stats.setdefault(k, v)
    return stats


# ══════════════════════════════════════════════════════════
# Telegram / datos de mercado
# ══════════════════════════════════════════════════════════

def send_telegram(message: str):
    if "PON_AQUI" in config.TELEGRAM_TOKEN or "PON_AQUI" in config.TELEGRAM_CHAT_ID:
        print("[AVISO] Configura TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en config.py")
        print(message)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR Telegram] {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR Telegram] {e}")


def display_symbol(symbol: str) -> str:
    return symbol.split(":")[0].replace("/", "")


def pct_from_entry(entry: float, level: float) -> str:
    if not entry:
        return ""
    pct = (level - entry) / entry * 100.0
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


def fetch_ohlcv(exchange, symbol, timeframe, limit):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def context_line(pos: dict) -> str:
    tag = f" | ⚠️ ROJA (x{config.RED_SIZE_FACTOR})" if pos.get("is_red") else ""
    return (f"Score: *{pos['score']}* | Prob: {pos['prob'] * 100:.0f}% | "
            f"{'+'.join(pos['strategies'])} | Lev: {pos['leverage']}x{tag}")


# ══════════════════════════════════════════════════════════
# Threshold dinámico
# ══════════════════════════════════════════════════════════

def update_dynamic_threshold(state):
    if not config.USE_DYNAMIC_THRESHOLD:
        state["dynamic_min_score"] = config.MIN_SCORE
        return

    current = state.get("dynamic_min_score", config.MIN_SCORE)
    results = state.get("recent_results", [])

    if len(results) >= config.DYNAMIC_LOSING_STREAK_TO_RAISE:
        if all(r is False for r in results[-config.DYNAMIC_LOSING_STREAK_TO_RAISE:]):
            current = min(config.DYNAMIC_THRESHOLD_MAX, current + config.DYNAMIC_THRESHOLD_STEP)

    if len(results) >= config.DYNAMIC_WINNING_STREAK_TO_LOWER:
        if all(r is True for r in results[-config.DYNAMIC_WINNING_STREAK_TO_LOWER:]):
            current = max(config.DYNAMIC_THRESHOLD_MIN, current - config.DYNAMIC_THRESHOLD_STEP)

    state["dynamic_min_score"] = current


def register_result(state, is_win: bool):
    results = state.setdefault("recent_results", [])
    results.append(bool(is_win))
    if len(results) > config.DYNAMIC_THRESHOLD_LOOKBACK_TRADES:
        del results[0]


# ══════════════════════════════════════════════════════════
# Cooldown / límites de posiciones / señales rojas
# ══════════════════════════════════════════════════════════

def is_in_cooldown(state, symbol, now):
    until = state.get("cooldowns", {}).get(symbol)
    return bool(until) and now < datetime.fromisoformat(until)


def set_cooldown(state, symbol, now):
    until = now + timedelta(hours=config.COOLDOWN_HOURS)
    state.setdefault("cooldowns", {})[symbol] = until.isoformat()


def can_open_new_trade(state, symbol, now):
    if is_in_cooldown(state, symbol, now):
        return False
    positions = state.get("positions", {})
    if symbol in positions:
        return False
    if len(positions) >= config.MAX_CONCURRENT_TRADES:
        return False
    return True


def _red_tracker(state, now):
    today_str = now.strftime("%Y-%m-%d")
    tracker = state.setdefault("red_signals_today", {"date": None, "count": 0})
    if tracker["date"] != today_str:
        tracker["date"] = today_str
        tracker["count"] = 0
    return tracker


def red_signals_used_today(state, now):
    return _red_tracker(state, now)["count"]


def register_red_signal(state, now):
    _red_tracker(state, now)["count"] += 1


# ══════════════════════════════════════════════════════════
# Clasificación de operación cerrada (mismo criterio que el bot Synapse)
# ══════════════════════════════════════════════════════════

def classify_closed_position(pos, close_reason, was_be_at_start):
    if pos.get("tp1_reached"):
        r1 = (1 / 3) * pos["tp_rr"][0]
        r2 = (1 / 3) * pos["tp_rr"][1] if pos.get("tp2_reached") else 0.0
        r3 = (1 / 3) * pos["tp_rr"][2] if pos.get("tp3_reached") else 0.0
        r_total = (r1 + r2 + r3) * pos.get("size_factor", 1.0)
        is_win = True
        is_be_save = close_reason == "sl" and was_be_at_start
    else:
        r_total = -1.0 * pos.get("size_factor", 1.0)
        is_win = False
        is_be_save = False
    return is_win, is_be_save, r_total


def classify_signal_quality(signal, dynamic_min_score):
    """
    Devuelve 'normal', 'roja' o 'descartada'.
    Una señal solo puede ser 'normal' (tamaño completo) si además de superar
    el score/prob mínimos, tiene confluencia de varias estrategias
    (MIN_CONFLUENCE_FOR_NORMAL). Con una sola estrategia disparando, como
    mucho se trata como 'roja' — nunca se abre a tamaño completo con la
    palabra de una sola de las 6 estrategias.
    """
    has_confluence = signal["confluence"] >= config.MIN_CONFLUENCE_FOR_NORMAL
    if has_confluence and signal["score"] >= dynamic_min_score and signal["prob"] >= config.MIN_PROB:
        return "normal"
    if signal["prob"] >= config.RED_MIN_PROB:
        return "roja"
    return "descartada"


def close_position(state, symbol, pos, last_price, close_reason, now, exec_exchange=None, extra_note=""):
    """Cierra una posición: registra stats, resultado, cooldown y avisa por Telegram."""
    # Si la posición se ejecutó de verdad en Bitget demo: cancela lo que
    # quede de SL/TP pendientes y cierra a mercado cualquier resto (red de
    # seguridad para flips, o por si el SL/TP del propio Bitget aún no
    # se había disparado cuando el bot lo detectó por su cuenta).
    if config.ENABLE_BITGET_EXECUTION and exec_exchange is not None and pos.get("bitget_executed"):
        try:
            bx.close_remaining_position(
                exec_exchange, symbol, pos["dir"],
                sl_order_id=pos.get("bitget_sl_order_id"),
                tp_order_ids=pos.get("bitget_tp_order_ids"),
            )
        except Exception as e:
            print(f"[bitget_executor] ERROR limpiando posición en Bitget para {symbol}: {e}")

    stats = get_stats(state)
    was_be = pos.get("be_active", False)
    is_win, is_be_save, r_total = classify_closed_position(pos, close_reason, was_be)
    stats["wins" if is_win else "losses"] += 1
    stats["be_saves"] += 1 if is_be_save else 0
    stats["r_sum"] += r_total
    if close_reason == "flip":
        stats["flips"] += 1
    register_result(state, is_win)

    closed_trades = stats["wins"] + stats["losses"]
    win_rate = stats["wins"] / closed_trades * 100 if closed_trades else 0
    avg_r = stats["r_sum"] / closed_trades if closed_trades else 0
    close_pct = pct_from_entry(pos["entry"], last_price)

    icon_map = {"flip": "🔄", "tp3": "💠", "sl_be": "🔒", "sl": "🛑"}
    reason_label = close_reason
    if close_reason == "sl" and was_be:
        reason_label = "sl_be"
    icon = icon_map.get(reason_label, "🛑")
    text_map = {
        "flip": "Flip de señal. Trade cerrado.",
        "tp3": "TP3 alcanzado. Trade cerrado.",
        "sl_be": "BE stop-out. Trade cerrado.",
        "sl": "SL alcanzado. Trade cerrado.",
    }
    reason_text = text_map.get(reason_label, "Trade cerrado.")

    send_telegram(
        f"{icon} *{display_symbol(symbol)}* — {reason_text}{extra_note}\n"
        f"Entrada: `{pos['entry']:.4f}` | Cierre: `{last_price:.4f}`{close_pct}\n"
        f"Resultado: {'✅ GANADORA' if is_win else '❌ PERDEDORA'} ({r_total:+.2f}R)\n"
        f"{context_line(pos)}\n\n"
        f"📈 Cerradas: {closed_trades} | WR {win_rate:.1f}% | R medio {avg_r:+.2f} "
        f"| BE saves: {stats['be_saves']} | Flips: {stats['flips']}"
    )

    state.setdefault("positions", {}).pop(symbol, None)
    set_cooldown(state, symbol, now)

    log = state.setdefault("trade_log", [])
    log.append({
        "symbol": symbol,
        "dir": pos["dir"],
        "strategies": pos["strategies"],
        "confluence": pos["confluence"],
        "score": pos["score"],
        "prob": pos["prob"],
        "is_red": pos.get("is_red", False),
        "leverage": pos.get("leverage"),
        "entry": pos["entry"],
        "exit": last_price,
        "r_result": round(r_total, 4),
        "is_win": is_win,
        "close_reason": reason_label,
        "entry_candle": pos["entry_candle"],
        "closed_at": now.isoformat(),
    })
    if len(log) > config.TRADE_LOG_MAX:
        del log[:len(log) - config.TRADE_LOG_MAX]


# ══════════════════════════════════════════════════════════
# Lógica principal por símbolo
# ══════════════════════════════════════════════════════════

def check_symbol(exchange, symbol, state, now, exec_exchange=None):
    limit = max(config.VP_LOOKBACK, config.SMC_LOOKBACK, config.BREAKOUT_LOOKBACK) + 100
    df = fetch_ohlcv(exchange, symbol, config.TIMEFRAME, limit)
    df = compute_base_indicators(df, config)

    last_candle_time = df.iloc[-1]["datetime"].isoformat()
    last_price = df.iloc[-1]["close"]

    positions = state.setdefault("positions", {})
    stats = get_stats(state)
    pos = positions.get(symbol)

    last_processed_key = f"{symbol}_last_processed_candle"
    already_processed_this_candle = state.get(last_processed_key) == last_candle_time

    # ── 1. Señal ensemble sobre la última vela cerrada ──
    signal = None if already_processed_this_candle else compute_ensemble_signal(df, config)

    quality = None
    if signal:
        dynamic_min_score = state.get("dynamic_min_score", config.MIN_SCORE)
        quality = classify_signal_quality(signal, dynamic_min_score)
        if quality == "roja" and red_signals_used_today(state, now) >= config.RED_MAX_PER_DAY:
            quality = "descartada"  # límite diario de señales rojas alcanzado

    actionable_signal = signal is not None and quality in ("normal", "roja")

    # ── 2. Flip: señal contraria mientras hay posición abierta -> cerrar antes ──
    if actionable_signal and pos and pos["dir"] != signal["direction"]:
        close_position(state, symbol, pos, last_price, "flip", now, exec_exchange)
        pos = None

    # ── 3. Abrir nueva posición si hay hueco y no hay ya una en este símbolo ──
    if actionable_signal and not pos and can_open_new_trade(state, symbol, now):
        atr_val = df.iloc[-1]["ATR"]
        risk = build_risk_levels(last_price, atr_val, signal["direction"], config.RISK_PRESET)
        is_red = quality == "roja"
        if is_red:
            risk = cap_tp_at_r(risk, last_price, signal["direction"], config.RED_TP_CAP_R)
            register_red_signal(state, now)

        leverage = suggest_leverage(df, config)

        new_pos = {
            "dir": signal["direction"],
            "entry": last_price,
            "entry_candle": last_candle_time,
            "sl": risk["sl"],
            "tp1": risk["tps"][0]["price"], "tp2": risk["tps"][1]["price"], "tp3": risk["tps"][2]["price"],
            "tp_rr": [tp["rr"] for tp in risk["tps"]],
            "tp1_reached": False, "tp2_reached": False, "tp3_reached": False,
            "be_active": False,
            "score": signal["score"], "prob": signal["prob"],
            "strategies": signal["strategies"], "confluence": signal["confluence"],
            "leverage": leverage,
            "is_red": is_red,
            "size_factor": config.RED_SIZE_FACTOR if is_red else 1.0,
        }
        positions[symbol] = new_pos
        pos = new_pos

        # ── Ejecución real en Bitget demo (si está activada) ──
        new_pos["bitget_executed"] = False
        if config.ENABLE_BITGET_EXECUTION and exec_exchange is not None:
            try:
                exec_result = bx.open_position(
                    exec_exchange, symbol, signal["direction"], leverage,
                    entry_price=last_price, sl_price=new_pos["sl"],
                    tp_prices=[new_pos["tp1"], new_pos["tp2"], new_pos["tp3"]],
                    risk_pct=config.RISK_PCT_PER_TRADE, tp_split=config.TP_SPLIT,
                )
                new_pos["bitget_executed"] = True
                new_pos["bitget_size"] = exec_result["size"]
                new_pos["bitget_sl_order_id"] = exec_result["sl_order_id"]
                new_pos["bitget_tp_order_ids"] = [tp["order_id"] for tp in exec_result["tp_orders"]]
            except Exception as e:
                print(f"[bitget_executor] ERROR abriendo posición real en Bitget para {symbol}: {e}")
                send_telegram(
                    f"⚠️ *{display_symbol(symbol)}* — La señal se registró en modo papel, pero "
                    f"FALLÓ la apertura real en Bitget demo: `{e}`"
                )

        stats["total_signals"] += 1
        stats["red_signals" if is_red else "normal_signals"] += 1
        stats["long_signals" if signal["direction"] == "ALCISTA" else "short_signals"] += 1

        emoji = "🟢" if signal["direction"] == "ALCISTA" else "🔴"
        dir_label = "LONG" if signal["direction"] == "ALCISTA" else "SHORT"
        sym = display_symbol(symbol)
        sl_pct = pct_from_entry(pos["entry"], pos["sl"])
        red_tag = " ⚠️ SEÑAL ROJA (tamaño x0.30, TP cap 1.7R)" if is_red else ""

        msg = (
            f"{emoji} *{sym} | {dir_label}*{red_tag}\n"
            f"Score {pos['score']} | Prob {pos['prob'] * 100:.0f}% | {'+'.join(pos['strategies'])}\n\n"
            f"💰 Entrada: `{pos['entry']:.4f}`\n"
            f"🔴 Stop Loss: `{pos['sl']:.4f}`{sl_pct}\n"
            f"⚡ Apalancamiento sugerido: {leverage}x\n\n"
            f"🎯 TP1: `{pos['tp1']:.4f}`{pct_from_entry(pos['entry'], pos['tp1'])} · RR {pos['tp_rr'][0]:.2f}\n"
            f"🎯 TP2: `{pos['tp2']:.4f}`{pct_from_entry(pos['entry'], pos['tp2'])} · RR {pos['tp_rr'][1]:.2f}\n"
            f"🎯 TP3: `{pos['tp3']:.4f}`{pct_from_entry(pos['entry'], pos['tp3'])} · RR {pos['tp_rr'][2]:.2f}\n\n"
            f"⏱ {symbol} · {config.TIMEFRAME} · {last_candle_time}"
        )
        send_telegram(msg)
        print(msg.replace("*", "").replace("`", ""))

    # ── 4. Comprobar hits de SL/TP en timeframe de seguimiento (1m) ──
    if pos:
        is_entry_candle = pos["entry_candle"] == last_candle_time
        if not is_entry_candle:
            df_mon = fetch_ohlcv(exchange, symbol, config.MONITOR_TIMEFRAME, 3)
            last_mon = df_mon.iloc[-1]
            last_high, last_low = last_mon["high"], last_mon["low"]

            is_long = pos["dir"] == "ALCISTA"
            sl_hit = (last_low <= pos["sl"]) if is_long else (last_high >= pos["sl"])
            tp1_hit = (last_high >= pos["tp1"]) if is_long else (last_low <= pos["tp1"])
            tp2_hit = (last_high >= pos["tp2"]) if is_long else (last_low <= pos["tp2"])
            tp3_hit = (last_high >= pos["tp3"]) if is_long else (last_low <= pos["tp3"])

            tp1_first = tp1_hit and not pos["tp1_reached"] and not sl_hit
            tp2_first = tp2_hit and not pos["tp2_reached"] and not sl_hit
            tp3_first = tp3_hit and not pos["tp3_reached"] and not sl_hit

            if tp1_first:
                pos["tp1_reached"] = True
                stats["tp1_hits"] += 1
                tp1_pct = pct_from_entry(pos["entry"], pos["tp1"])
                if config.USE_BREAK_EVEN and not pos["be_active"]:
                    pos["sl"] = pos["entry"]
                    pos["be_active"] = True

                    if config.ENABLE_BITGET_EXECUTION and exec_exchange is not None and pos.get("bitget_executed"):
                        try:
                            new_sl_id = bx.move_sl_to_be(
                                exec_exchange, symbol, pos["dir"],
                                old_sl_order_id=pos.get("bitget_sl_order_id"),
                                new_sl_price=pos["entry"], size=pos.get("bitget_size", 0.0),
                            )
                            pos["bitget_sl_order_id"] = new_sl_id
                        except Exception as e:
                            print(f"[bitget_executor] ERROR moviendo SL a BE en Bitget para {symbol}: {e}")

                    send_telegram(
                        f"✅ *{display_symbol(symbol)}* — TP1 alcanzado (`{pos['tp1']:.4f}`{tp1_pct}).\n"
                        f"🔒 SL movido a BE (`{pos['entry']:.4f}`).\n{context_line(pos)}"
                    )
                else:
                    send_telegram(
                        f"✅ *{display_symbol(symbol)}* — TP1 alcanzado (`{pos['tp1']:.4f}`{tp1_pct}).\n"
                        f"{context_line(pos)}"
                    )

            if tp2_first:
                pos["tp2_reached"] = True
                stats["tp2_hits"] += 1
                tp2_pct = pct_from_entry(pos["entry"], pos["tp2"])
                send_telegram(
                    f"🔥 *{display_symbol(symbol)}* — TP2 alcanzado. Runner hacia TP3.\n"
                    f"`{pos['tp2']:.4f}`{tp2_pct}\n{context_line(pos)}"
                )

            if sl_hit or tp3_first:
                if tp3_first:
                    pos["tp3_reached"] = True
                    stats["tp3_hits"] += 1
                    close_position(state, symbol, pos, last_price, "tp3", now, exec_exchange)
                else:
                    stats["sl_hits"] += 1
                    close_position(state, symbol, pos, last_price, "sl", now, exec_exchange)

    state[last_processed_key] = last_candle_time


# ══════════════════════════════════════════════════════════
# Resumen diario
# ══════════════════════════════════════════════════════════

def maybe_send_daily_summary(state):
    if not config.SEND_DAILY_SUMMARY:
        return

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    if now.hour < config.DAILY_SUMMARY_HOUR_UTC:
        return
    if state.get("last_daily_summary_date") == today_str:
        return

    stats = get_stats(state)
    closed_trades = stats["wins"] + stats["losses"]
    win_rate = stats["wins"] / closed_trades * 100 if closed_trades else 0
    avg_r = stats["r_sum"] / closed_trades if closed_trades else 0

    open_positions = state.get("positions", {})
    open_lines = "\n".join(
        f"  • {sym}: {p['dir']} desde `{p['entry']:.4f}`"
        f"{' (ROJA)' if p.get('is_red') else ''}"
        f"{' (BE activo)' if p.get('be_active') else ''}"
        for sym, p in open_positions.items()
    ) or "  • Ninguna"

    msg = (
        f"[{config.STRATEGY_LABEL}]\n"
        f"📊 *Resumen diario* — {today_str}\n\n"
        f"*Señales:* {stats['total_signals']} "
        f"(Normales: {stats['normal_signals']} | Rojas: {stats['red_signals']}) "
        f"| Long/Short: {stats['long_signals']} / {stats['short_signals']}\n"
        f"*Cerradas:* {closed_trades} | Win rate: {win_rate:.1f}% | R medio: {avg_r:+.2f}\n"
        f"*W/L:* {stats['wins']} / {stats['losses']} | BE saves: {stats['be_saves']} | Flips: {stats['flips']}\n"
        f"*Hits:* SL {stats['sl_hits']} | TP1 {stats['tp1_hits']} | TP2 {stats['tp2_hits']} | TP3 {stats['tp3_hits']}\n"
        f"*Umbral dinámico actual:* {state.get('dynamic_min_score', config.MIN_SCORE)}\n\n"
        f"*Posiciones abiertas:*\n{open_lines}"
    )
    send_telegram(msg)
    state["last_daily_summary_date"] = today_str


# ══════════════════════════════════════════════════════════
# Bucle principal
# ══════════════════════════════════════════════════════════

def run_once():
    exchange_class = getattr(ccxt, config.EXCHANGE_ID)
    exchange = exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": config.MARKET_TYPE},
    })

    exec_exchange = None
    if config.ENABLE_BITGET_EXECUTION:
        if "PON_AQUI" in config.BITGET_API_KEY or "PON_AQUI" in config.BITGET_API_SECRET:
            print("[AVISO] ENABLE_BITGET_EXECUTION=True pero faltan las claves de Bitget demo "
                  "(BITGET_API_KEY / BITGET_API_SECRET / BITGET_API_PASSWORD). Corriendo en modo papel.")
        else:
            exec_exchange = bx.create_demo_exchange(
                config.BITGET_API_KEY, config.BITGET_API_SECRET, config.BITGET_API_PASSWORD
            )

    state = load_state()
    now = datetime.now(timezone.utc)

    update_dynamic_threshold(state)

    for symbol in config.SYMBOLS:
        try:
            check_symbol(exchange, symbol, state, now, exec_exchange)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

    maybe_send_daily_summary(state)
    save_state(state)


def main():
    print(f"[{config.STRATEGY_LABEL}] Bot iniciado {datetime.now(timezone.utc).isoformat()} | "
          f"Símbolos: {config.SYMBOLS} | Timeframe: {config.TIMEFRAME}")

    if "--once" in sys.argv:
        run_once()
        return

    while True:
        run_once()
        time.sleep(config.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
