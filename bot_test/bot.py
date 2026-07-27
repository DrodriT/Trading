"""
Bot de alertas cripto — VERSIÓN "Synapse" (basada en Synapse Trail Pro)
con ejecución real de órdenes en Bitget Demo (swap).

Uso:
    python3 bot.py            # corre en bucle
    python3 bot.py --once     # ejecuta una sola pasada (usado por GitHub Actions)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import ccxt
import pandas as pd
import requests

import config
from indicators import add_ema, get_trend_vs_ema200
from strategy import (
    compute_indicators, compute_synapse_trail, compute_regime,
    detect_raw_signal, compute_quality_score, build_risk_levels,
    build_limit_entries, RISK_PRESETS
)
from trading_engine import BitgetTrader   # <--- importamos el motor

# ══════════════════════════════════════════════════════════
# Persistencia de estado
# ══════════════════════════════════════════════════════════

def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {"positions": {}, "stats": {}}


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_stats(state):
    stats = state.setdefault("stats", {})
    defaults = {
        "total_signals": 0, "buy_signals": 0, "sell_signals": 0,
        "grade_a": 0, "grade_b": 0, "grade_c": 0,
        "sl_hits": 0, "tp1_hits": 0, "tp2_hits": 0, "tp3_hits": 0,
        "flips": 0, "wins": 0, "losses": 0, "be_saves": 0, "r_sum": 0.0,
    }
    for k, v in defaults.items():
        stats.setdefault(k, v)
    return stats


# ══════════════════════════════════════════════════════════
# Telegram / datos
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
    """'BTC/USDT:USDT' -> 'BTCUSDT' — símbolo limpio para mostrar en Telegram."""
    return symbol.split(":")[0].replace("/", "")


def pct_from_entry(entry: float, level: float) -> str:
    """'(+0.42%)' / '(-1.18%)' — igual que formatPctFromEntry() en el Pine."""
    if not entry:
        return ""
    pct = (level - entry) / entry * 100.0
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


def context_line(pos: dict) -> str:
    """
    Línea de contexto reutilizada en todos los mensajes de cierre/TP/SL:
    grado, quality score y régimen de mercado EN EL MOMENTO DE LA ENTRADA
    (igual criterio que el tooltip del Pine, que muestra el contexto de
    la señal, no el régimen actual que ya pudo cambiar).
    """
    grade = pos.get("grade", "—")
    score = pos.get("score", "—")
    regime_label = pos.get("regime_label", "—")
    regime_score = pos.get("regime_score")
    regime_str = f"{regime_label} ({regime_score:.0f}/100)" if regime_score is not None else regime_label
    return f"Grado: *{grade}* ({score}/100) | Régimen en la entrada: {regime_str}"


def fetch_ohlcv(exchange, symbol, timeframe, limit):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


# ══════════════════════════════════════════════════════════
# Clasificación de una operación cerrada
# ══════════════════════════════════════════════════════════

def classify_closed_position(pos, close_reason, was_be_at_start):
    """
    tp1_reached = True  -> GANADORA (1/3 en cada TP alcanzado, resto 0R)
    tp1_reached = False -> PERDEDORA (-1R)
    BE save: ganadora que cerró por el SL porque el break-even ya estaba activo.
    """
    if pos.get("tp1_reached"):
        r1 = (1 / 3) * pos["tp_rr"][0]
        r2 = (1 / 3) * pos["tp_rr"][1] if pos.get("tp2_reached") else 0.0
        r3 = (1 / 3) * pos["tp_rr"][2] if pos.get("tp3_reached") else 0.0
        r_total = r1 + r2 + r3
        is_win = True
        is_be_save = close_reason == "sl" and was_be_at_start
    else:
        r_total = -1.0
        is_win = False
        is_be_save = False
    return is_win, is_be_save, r_total


# ══════════════════════════════════════════════════════════
# Lógica principal por símbolo (con órdenes reales)
# ══════════════════════════════════════════════════════════

def check_symbol(exchange, symbol, state, trader):
    """
    trader: instancia de BitgetTrader (o None si no se quiere operar)
    """
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

    # --- HTF bias ---
    htf_bull, htf_bear = None, None
    if config.USE_HTF_FILTER:
        df_htf = fetch_ohlcv(exchange, symbol, config.CONFIRM_TIMEFRAME, config.HTF_EMA_PERIOD + 50)
        df_htf = add_ema(df_htf, config.HTF_EMA_PERIOD, f"EMA{config.HTF_EMA_PERIOD}")
        htf_bull, htf_bear = get_trend_vs_ema200(df_htf, config.HTF_EMA_PERIOD)

    has_volume = df["volume"].tail(20).sum() > 0

    last_candle_time = df.iloc[-1]["datetime"].isoformat()
    last_price = df.iloc[-1]["close"]
    last_high = df.iloc[-1]["high"]
    last_low = df.iloc[-1]["low"]

    positions = state.setdefault("positions", {})
    stats = get_stats(state)
    pos = positions.get(symbol)

    # --- Evitar reprocesar la misma vela ---
    last_processed_key = f"{symbol}_last_processed_candle"
    already_processed_this_candle = state.get(last_processed_key) == last_candle_time

    # ── 1. Detectar señal ──
    raw_signal = None if already_processed_this_candle else detect_raw_signal(df)

    new_signal_passes = False
    score, grade, breakdown = None, None, None

    if raw_signal:
        is_choppy = bool(df.iloc[-1]["REGIME_is_choppy"])
        is_trending = bool(df.iloc[-1]["REGIME_is_trending"])
        is_long = raw_signal == "ALCISTA"

        score, grade, breakdown = compute_quality_score(
            df, raw_signal, htf_bull, htf_bear, config.USE_HTF_FILTER,
            config.USE_VOLUME_FILTER, config.VOLUME_THRESHOLD, has_volume
        )
        passes_min_quality = score >= config.MIN_QUALITY_SCORE
        passes_choppy = not (config.SKIP_CHOPPY_SIGNALS and is_choppy)

        htf_data_valid = config.USE_HTF_FILTER and htf_bull is not None and htf_bear is not None
        htf_against = htf_data_valid and ((is_long and htf_bear) or (not is_long and htf_bull))
        passes_htf = not (config.HTF_HARD_FILTER and htf_against)

        passes_regime = not config.REQUIRE_TRENDING_REGIME or is_trending

        new_signal_passes = passes_min_quality and passes_choppy and passes_htf and passes_regime

    # ── 2. FLIP: cerrar posición contraria antes de abrir la nueva ──
    if new_signal_passes and pos and pos["dir"] != raw_signal:
        # Cerrar la posición real primero
        if trader:
            side = 'long' if pos["dir"] == "ALCISTA" else 'short'
            close_order = trader.close_position(symbol, side)
            if not close_order:
                print(f"[ERROR] No se pudo cerrar posición flip para {symbol}")
                # No eliminamos la posición del estado, para que en la próxima iteración se reintente
                # Pero entonces no abriremos la nueva señal. Dejamos el estado como está.
                # Para evitar bucles, podríamos marcarla como pendiente de cierre, pero por simplicidad
                # si falla, no hacemos nada más y salimos.
                # Como es demo, podemos arriesgarnos a no actualizar el estado y que el bot intente de nuevo.
                # No obstante, para no perder la oportunidad, podríamos forzar el cierre en el siguiente ciclo.
                # Decido no actualizar estado y retornar para que no se abra la nueva.
                return
        # Si llegamos aquí, la orden de cierre se ejecutó correctamente (o no hay trader)
        was_be = pos.get("be_active", False)
        is_win, is_be_save, r_total = classify_closed_position(pos, "flip", was_be)
        stats["wins" if is_win else "losses"] += 1
        stats["be_saves"] += 1 if is_be_save else 0
        stats["r_sum"] += r_total
        stats["flips"] += 1

        flip_pct = pct_from_entry(pos["entry"], last_price)
        old_dir_label = "LONG" if pos["dir"] == "ALCISTA" else "SHORT"
        new_dir_label = "LONG" if raw_signal == "ALCISTA" else "SHORT"
        send_telegram(
            f"🔄 *{display_symbol(symbol)}* — Flip {old_dir_label}→{new_dir_label}. Trade cerrado.\n"
            f"Cierre: `{last_price:.4f}`{flip_pct}\n"
            f"Resultado: {'✅ GANADORA' if is_win else '❌ PERDEDORA'} ({r_total:+.2f}R)\n"
            f"{context_line(pos)}"
        )
        positions.pop(symbol, None)
        pos = None   # para que pueda abrir la nueva a continuación

    # ── 3. Abrir nueva posición si hay señal y no hay posición ──
    if new_signal_passes and not pos:
        # Ejecutar orden real ANTES de guardar estado
        if trader:
            side = 'buy' if raw_signal == 'ALCISTA' else 'sell'
            order = trader.open_position(symbol, side, amount_usdt=config.ORDER_AMOUNT_USDT)
            if not order:
                print(f"[ERROR] No se pudo abrir posición para {symbol}")
                return   # No actualizar estado, se reintentará en la próxima ejecución
            # Si la orden se ejecutó, obtenemos el precio de ejecución (puede diferir de last_price)
            filled_price = order.get('price', last_price)
        else:
            # Si no hay trader, usamos last_price (solo alerta)
            filled_price = last_price
            order = None

        preset = RISK_PRESETS[config.RISK_PRESET]
        risk = build_risk_levels(filled_price, df.iloc[-1]["ATR"], raw_signal, config.RISK_PRESET)

        regime_label_at_entry = "Trending" if df.iloc[-1]["REGIME_is_trending"] else (
            "Choppy" if df.iloc[-1]["REGIME_is_choppy"] else "Mixed")

        new_pos = {
            "dir": raw_signal,
            "entry": filled_price,
            "entry_candle": last_candle_time,
            "sl": risk["sl"],
            "tp1": risk["tps"][0]["price"],
            "tp2": risk["tps"][1]["price"],
            "tp3": risk["tps"][2]["price"],
            "tp_rr": [tp["rr"] for tp in risk["tps"]],
            "tp1_reached": False,
            "tp2_reached": False,
            "tp3_reached": False,
            "be_active": False,
            "grade": grade,
            "score": score,
            "regime_label": regime_label_at_entry,
            "regime_score": float(df.iloc[-1]["REGIME_score"]),
        }
        if order:
            new_pos["order_id"] = order['id']
        positions[symbol] = new_pos
        pos = new_pos

        stats["total_signals"] += 1
        stats["buy_signals" if raw_signal == "ALCISTA" else "sell_signals"] += 1
        stats[f"grade_{grade.lower()}"] += 1

        emoji = "🟢" if raw_signal == "ALCISTA" else "🔴"
        dir_label = "LONG" if raw_signal == "ALCISTA" else "SHORT"
        sym = display_symbol(symbol)
        entries = build_limit_entries(df, "TRAIL_EMA", config.HTF_EMA_PERIOD, raw_signal)
        extra_entries = entries[1:]
        sl_pct = pct_from_entry(pos["entry"], pos["sl"])

        msg = (
            f"{emoji} *{sym} | {dir_label}*  ·  Score {score} ({grade})\n\n"
            f"💰 Entrada: `{pos['entry']:.4f}`\n"
            f"🔴 Stop Loss: `{pos['sl']:.4f}`{sl_pct}\n\n"
            f"🎯 TP1: `{pos['tp1']:.4f}`{pct_from_entry(pos['entry'], pos['tp1'])} · RR {pos['tp_rr'][0]}\n"
            f"🎯 TP2: `{pos['tp2']:.4f}`{pct_from_entry(pos['entry'], pos['tp2'])} · RR {pos['tp_rr'][1]}\n"
            f"🎯 TP3: `{pos['tp3']:.4f}`{pct_from_entry(pos['entry'], pos['tp3'])} · RR {pos['tp_rr'][2]}\n\n"
            f"📊 Régimen: {regime_label} ({df.iloc[-1]['REGIME_score']:.0f}/100) | Preset: {config.RISK_PRESET}\n"
            f"⏱ {symbol} · {config.TIMEFRAME} · {last_candle_time}"
        )
        if extra_entries:
            extra_text = "\n".join(f"  • `{e['price']:.4f}` — {e['basis']}" for e in extra_entries)
            msg += f"\n\n*Entradas escalonadas alternativas:*\n{extra_text}"
        send_telegram(msg)
        print(msg.replace("*", "").replace("`", ""))

    # ── 4. Si hay posición abierta, comprobar hits ──
    if pos:
        is_long = pos["dir"] == "ALCISTA"
        is_entry_candle = pos["entry_candle"] == last_candle_time
        can_hit = not is_entry_candle

        if can_hit:
            effective_sl = pos["sl"]
            sl_hit = (last_low <= effective_sl) if is_long else (last_high >= effective_sl)
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
                    send_telegram(
                        f"✅ *{display_symbol(symbol)}* — TP1 alcanzado (`{pos['tp1']:.4f}`{tp1_pct} · RR {pos['tp_rr'][0]}).\n"
                        f"🔒 SL movido a BE (`{pos['entry']:.4f}`).\n"
                        f"{context_line(pos)}"
                    )
                else:
                    send_telegram(
                        f"✅ *{display_symbol(symbol)}* — TP1 alcanzado (`{pos['tp1']:.4f}`{tp1_pct} · RR {pos['tp_rr'][0]}).\n"
                        f"{context_line(pos)}"
                    )

            if tp2_first:
                pos["tp2_reached"] = True
                stats["tp2_hits"] += 1
                tp2_pct = pct_from_entry(pos["entry"], pos["tp2"])
                send_telegram(
                    f"🔥 *{display_symbol(symbol)}* — TP2 alcanzado. Runner hacia TP3.\n"
                    f"`{pos['tp2']:.4f}`{tp2_pct} · RR {pos['tp_rr'][1]}\n"
                    f"{context_line(pos)}"
                )

            was_be_at_start = pos["be_active"]

            if sl_hit or tp3_first:
                # Cerrar la posición real ANTES de actualizar estadísticas
                if trader:
                    side = 'long' if pos["dir"] == "ALCISTA" else 'short'
                    close_order = trader.close_position(symbol, side)
                    if not close_order:
                        print(f"[ERROR] No se pudo cerrar posición {symbol} por SL/TP3")
                        # No eliminamos la posición, se reintentará
                        return

                if tp3_first:
                    pos["tp3_reached"] = True
                    stats["tp3_hits"] += 1
                else:
                    stats["sl_hits"] += 1

                close_reason = "sl" if sl_hit else "tp3"
                is_win, is_be_save, r_total = classify_closed_position(pos, close_reason, was_be_at_start)
                stats["wins" if is_win else "losses"] += 1
                stats["be_saves"] += 1 if is_be_save else 0
                stats["r_sum"] += r_total

                closed_trades = stats["wins"] + stats["losses"]
                win_rate = stats["wins"] / closed_trades * 100 if closed_trades else 0
                avg_r = stats["r_sum"] / closed_trades if closed_trades else 0

                was_be_stop = sl_hit and was_be_at_start
                if tp3_first:
                    icon, reason_text = "💠", "TP3 alcanzado"
                elif was_be_stop:
                    icon, reason_text = "🔒", "BE stop-out"
                else:
                    icon, reason_text = "🛑", "SL alcanzado"
                close_pct = pct_from_entry(pos["entry"], last_price)
                send_telegram(
                    f"{icon} *{display_symbol(symbol)}* — {reason_text}. Trade cerrado.\n"
                    f"Entrada: `{pos['entry']:.4f}` | Cierre: `{last_price:.4f}`{close_pct}\n"
                    f"Resultado: {'✅ GANADORA' if is_win else '❌ PERDEDORA'} ({r_total:+.2f}R)\n"
                    f"{context_line(pos)}\n\n"
                    f"📈 Cerradas: {closed_trades} | WR {win_rate:.1f}% | R medio {avg_r:+.2f} "
                    f"| BE saves: {stats['be_saves']} | Flips: {stats['flips']}"
                )
                positions.pop(symbol, None)

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
        f"{' (BE activo)' if p.get('be_active') else ''}"
        for sym, p in open_positions.items()
    ) or "  • Ninguna"

    msg = (
        f"[{config.STRATEGY_LABEL}]\n"
        f"📊 *Resumen diario* — {today_str}\n\n"
        f"*Señales:* {stats['total_signals']} "
        f"(A:{stats['grade_a']} B:{stats['grade_b']} C:{stats['grade_c']}) "
        f"| Long/Short: {stats['buy_signals']} / {stats['sell_signals']}\n"
        f"*Cerradas:* {closed_trades} | Win rate: {win_rate:.1f}% | R medio: {avg_r:+.2f}\n"
        f"*W/L:* {stats['wins']} / {stats['losses']} | BE saves: {stats['be_saves']} | Flips: {stats['flips']}\n"
        f"*Hits:* SL {stats['sl_hits']} | TP1 {stats['tp1_hits']} | TP2 {stats['tp2_hits']} | TP3 {stats['tp3_hits']}\n\n"
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
    # Instanciamos el trader (si no hay credenciales, se lanzará excepción)
    trader = BitgetTrader()
    state = load_state()

    for symbol in config.SYMBOLS:
        try:
            check_symbol(exchange, symbol, state, trader)
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