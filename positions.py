"""
Gestión de posiciones — Rodri v1.0

Extraído de main.py (antes bot_rodri.py) sin cambios de lógica: clasifica
señales y operaciones cerradas, abre/cierra/gira posiciones, orquesta el
chequeo de un símbolo en cada pasada (check_symbol), y compone el resumen
diario. Es la capa de negocio que decide QUÉ hacer con cada señal; el
ensemble (ensemble.py) solo decide SI hay señal, nunca si se abre.
"""
from datetime import datetime, timezone

import config
from exchange import fetch_ohlcv
from strategy import compute_base_indicators
from ensemble import compute_ensemble_signal
from market_state import compute_htf_context, apply_htf_confirmation
from risk import build_risk_levels, cap_tp_at_r, suggest_leverage
from charting import generate_signal_chart
from telegram import send_telegram, send_telegram_photo, display_symbol, pct_from_entry, md_escape
from core.logger import get_logger
from state import (
    get_stats, register_result, set_cooldown, can_open_new_trade,
    red_signals_used_today, register_red_signal,
    get_last_processed_candle, set_last_processed_candle,
)

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════
# Clasificación de operación cerrada / calidad de señal
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


def close_position(state, symbol, pos, last_price, close_reason, now, extra_note=""):
    """Cierra una posición: registra stats, resultado, cooldown y avisa por Telegram."""
    stats = get_stats(state)
    was_be = pos.get("be_active", False)
    is_win, is_be_save, r_total = classify_closed_position(pos, close_reason, was_be)
    stats["wins" if is_win else "losses"] += 1
    stats["be_saves"] += 1 if is_be_save else 0
    stats["r_sum"] += r_total
    if close_reason == "flip":
        stats["flips"] += 1
    register_result(state, is_win)

    icon_map = {"flip": "🔄", "tp3": "💠", "sl_be": "🔒", "sl": "🛑"}
    reason_label = close_reason
    if close_reason == "sl" and was_be:
        reason_label = "sl_be"
    icon = icon_map.get(reason_label, "🛑")
    text_map = {
        "flip": "Flip de señal",
        "tp3": "TP3 alcanzado",
        "sl_be": "BE stop-out",
        "sl": "SL alcanzado",
    }
    reason_text = text_map.get(reason_label, "Trade cerrado")

    dir_label = "LONG" if pos["dir"] == "ALCISTA" else "SHORT"
    move_pct = pct_from_entry(pos["entry"], last_price)

    tp_flags = []
    if pos.get("tp1_reached"):
        tp_flags.append("TP1✅")
    if pos.get("tp2_reached"):
        tp_flags.append("TP2✅")
    if pos.get("tp3_reached"):
        tp_flags.append("TP3✅")
    tp_line = f"\n🎯 {' '.join(tp_flags)}" if tp_flags else ""

    closed_trades = stats["wins"] + stats["losses"]
    win_rate = stats["wins"] / closed_trades * 100 if closed_trades else 0

    # Mensaje de cierre: qué se cerró y por qué, con qué señal se abrió
    # (score/prob/estrategia — útil para luego evaluar con tools/analyze.py),
    # el movimiento entrada->salida, los TP que llegó a tocar, el resultado
    # en R, y una línea de acumulado corta (el detalle completo va en el
    # resumen diario).
    send_telegram(
        f"{icon} *{display_symbol(symbol)}* | {dir_label}\n\n"
        f"Score {pos['score']} | Prob {pos['prob'] * 100:.0f}%\n"
        f"{md_escape(chr(10).join(pos['strategies']))}\n\n"
        f"🛑 {reason_text}{extra_note}\n"
        f"Resultado: {'✅ ' if is_win else '❌ '} ({r_total:+.2f}R)\n"
        f"💰 Entrada: `{pos['entry']:.4f}` → Cierre: `{last_price:.4f}`{move_pct}{tp_line}\n\n"
        f"---------------------------------\n"
        f"Acumulado: {stats['wins']}G/{stats['losses']}P\n"
        f"WR {win_rate:.1f}%\n"
        f"R total {stats['r_sum']:+.2f}\n"
        f"---------------------------------"
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
        "htf_trend": pos.get("htf_trend"),
        "htf_penalized": pos.get("htf_penalized", False),
        "used_structural_sl": pos.get("used_structural_sl", False),
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

def check_symbol(exchange, symbol, state, now):
    limit = max(config.VP_LOOKBACK, config.SMC_LOOKBACK, config.BREAKOUT_LOOKBACK) + 100
    df = fetch_ohlcv(exchange, symbol, config.TIMEFRAME, limit)
    df = compute_base_indicators(df, config)

    last_candle_time = df.iloc[-1]["datetime"].isoformat()
    last_price = df.iloc[-1]["close"]

    positions = state.setdefault("positions", {})
    stats = get_stats(state)
    pos = positions.get(symbol)

    already_processed_this_candle = get_last_processed_candle(state, symbol) == last_candle_time

    # ── 1. Señal ensemble sobre la última vela cerrada (5m) ──
    signal = None if already_processed_this_candle else compute_ensemble_signal(df, config)

    # ── 1b. Confirmación con el timeframe superior (15m por defecto) ──
    # No repite las 6 estrategias en 15m: solo mira si hay una tendencia
    # clara (EMA rápida/lenta + ADX) que respalde o contradiga la
    # dirección detectada en 5m. Si va claramente en contra, penaliza el
    # score o bloquea la señal directamente (ver apply_htf_confirmation).
    if signal and config.CONFIRM_ENABLED:
        try:
            df_htf = fetch_ohlcv(exchange, symbol, config.CONFIRM_TIMEFRAME,
                                  config.CONFIRM_LOOKBACK_CANDLES)
            htf_context = compute_htf_context(df_htf, config)
            signal = apply_htf_confirmation(signal, htf_context, config)
        except Exception as e:
            # Si falla la descarga/cálculo de 15m, seguimos con la señal
            # de 5m tal cual: un fallo de red no debe bloquear el trading.
            logger.warning(f"No se pudo confirmar en {config.CONFIRM_TIMEFRAME} para {symbol}: {e}")

    quality = None
    if signal:
        dynamic_min_score = state.get("dynamic_min_score", config.MIN_SCORE)
        quality = classify_signal_quality(signal, dynamic_min_score)
        if quality == "roja" and red_signals_used_today(state, now) >= config.RED_MAX_PER_DAY:
            quality = "descartada"  # límite diario de señales rojas alcanzado

    actionable_signal = signal is not None and quality in ("normal", "roja")

    # ── 2. Flip: señal contraria mientras hay posición abierta -> cerrar antes ──
    if actionable_signal and pos and pos["dir"] != signal["direction"]:
        close_position(state, symbol, pos, last_price, "flip", now)
        pos = None

    # ── 3. Abrir nueva posición si hay hueco y no hay ya una en este símbolo ──
    if actionable_signal and not pos and can_open_new_trade(state, symbol, now):
        atr_val = df.iloc[-1]["ATR"]
        risk = build_risk_levels(last_price, atr_val, signal["direction"], config.RISK_PRESET,
                                  df=df, cfg=config)
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
            "htf_trend": signal.get("htf_trend"),
            "htf_adx": signal.get("htf_adx"),
            "htf_penalized": signal.get("htf_penalized", False),
            "used_structural_sl": risk.get("used_structural_sl", False),
            "leverage": leverage,
            "is_red": is_red,
            "size_factor": config.RED_SIZE_FACTOR if is_red else 1.0,
        }
        positions[symbol] = new_pos
        pos = new_pos

        stats["total_signals"] += 1
        stats["red_signals" if is_red else "normal_signals"] += 1
        stats["long_signals" if signal["direction"] == "ALCISTA" else "short_signals"] += 1

        emoji = "🟢" if signal["direction"] == "ALCISTA" else "🔴"
        dir_label = "LONG" if signal["direction"] == "ALCISTA" else "SHORT"
        sym = display_symbol(symbol)
        sl_pct = pct_from_entry(pos["entry"], pos["sl"])
        sl_tag = " (estructural 🛡️)" if pos.get("used_structural_sl") else " (ATR)"
        red_tag = " ⚠️ SEÑAL ROJA (tamaño x0.30, TP cap 1.7R)" if is_red else ""

        htf_line = ""
        if config.CONFIRM_ENABLED and signal.get("htf_trend"):
            htf_icon = "✅" if not signal.get("htf_penalized") else "⚠️"
            htf_line = (f"{htf_icon} 15m: {signal['htf_trend']} "
                        f"(ADX {signal['htf_adx']:.0f})"
                        f"{' — score penalizado' if signal.get('htf_penalized') else ''}\n")

        msg = (
            f"{emoji} *{sym} | {dir_label}*{red_tag}\n"
            f"Score {pos['score']} | Prob {pos['prob'] * 100:.0f}%\n"
            f"{md_escape(chr(10).join(pos['strategies']))}\n"
            f"{htf_line}\n"
            f"💰 Entrada: `{pos['entry']:.4f}`\n"
            f"🔴 Stop Loss: `{pos['sl']:.4f}`{sl_pct}{sl_tag}\n"
            f"⚡ Apalancamiento sugerido: {leverage}x\n\n"
            f"🎯 TP1: `{pos['tp1']:.4f}`{pct_from_entry(pos['entry'], pos['tp1'])}\n"
            f"🎯 TP2: `{pos['tp2']:.4f}`{pct_from_entry(pos['entry'], pos['tp2'])}\n"
            f"🎯 TP3: `{pos['tp3']:.4f}`{pct_from_entry(pos['entry'], pos['tp3'])}\n\n"
            f"⏱ {symbol} · {config.TIMEFRAME} · {last_candle_time}"
        )
        try:
            chart_path = generate_signal_chart(
                df, symbol, signal["direction"], pos["score"], pos["prob"],
                pos["strategies"], pos["entry"], pos["sl"],
                [pos["tp1"], pos["tp2"], pos["tp3"]],
                lookback_candles=config.CHART_LOOKBACK_CANDLES,
            )
            send_telegram_photo(chart_path, msg)
        except Exception as e:
            logger.error(f"[gráfico] {e}")
            send_telegram(msg)
        logger.info(msg.replace("*", "").replace("`", ""))

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
                if config.USE_BREAK_EVEN and not pos["be_active"]:
                    pos["sl"] = pos["entry"]
                    pos["be_active"] = True
                    send_telegram(
                        f"✅ *{display_symbol(symbol)}*\n\n"
                        f"🎯 TP1 alcanzado (`{pos['tp1']:.4f}`).\n"
                        f"🔒 SL movido a BE (`{pos['entry']:.4f}`)."
                    )
                else:
                    send_telegram(
                        f"✅ *{display_symbol(symbol)}*\n\n"
                        f"🎯 TP1 alcanzado (`{pos['tp1']:.4f}`)."
                    )

            if tp2_first:
                pos["tp2_reached"] = True
                stats["tp2_hits"] += 1
                send_telegram(
                    f"✅ *{display_symbol(symbol)}*\n\n"
                    f"🔥 TP2 alcanzado. Runner hacia TP3.\n"
                    f"`{pos['tp2']:.4f}`"
                )

            if sl_hit or tp3_first:
                if tp3_first:
                    pos["tp3_reached"] = True
                    stats["tp3_hits"] += 1
                    close_position(state, symbol, pos, last_price, "tp3", now)
                else:
                    stats["sl_hits"] += 1
                    close_position(state, symbol, pos, last_price, "sl", now)

    set_last_processed_candle(state, symbol, last_candle_time)


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
