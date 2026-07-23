"""
Bot de alertas cripto: EMA13 / EMA200 + Estocástico -> Telegram

Uso:
    python3 bot.py            # corre en bucle, revisando cada CHECK_INTERVAL_SECONDS
    python3 bot.py --once     # ejecuta una sola pasada y termina (útil para cron)
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
from indicators import add_ema, add_atr, get_trend_vs_ema200
from strategy import (
    compute_indicators, detect_signals, build_limit_entries,
    build_risk_management, build_score
)


def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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


def fetch_ohlcv(exchange, symbol, timeframe, limit):
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def check_symbol(exchange, symbol, state):
    limit = config.EMA_SLOW + 50  # suficientes velas para que EMA200 sea fiable
    df = fetch_ohlcv(exchange, symbol, config.TIMEFRAME, limit)
    df = compute_indicators(
        df, config.EMA_FAST, config.EMA_SLOW,
        config.STOCH_K_PERIOD, config.STOCH_SMOOTH, config.STOCH_D_PERIOD,
        adx_period=config.ADX_PERIOD, macd_fast=config.MACD_FAST, macd_slow=config.MACD_SLOW,
        macd_signal=config.MACD_SIGNAL, rsi_period=config.RSI_PERIOD,
        volume_ma_period=config.VOLUME_MA_PERIOD, ssl_period=config.SSL_PERIOD
    )
    df = add_atr(df, config.ATR_PERIOD)

    # --- Confirmación multi-timeframe (1h): tendencia y fuerza según precio vs EMA200 ---
    mtf_bullish, mtf_bearish, mtf_label = None, None, ""
    trend_strength_1h_pct = 0.0
    if config.ENABLE_MTF_CONFIRMATION:
        mtf_label = config.CONFIRM_TIMEFRAME
        df_mtf = fetch_ohlcv(exchange, symbol, config.CONFIRM_TIMEFRAME, config.EMA_SLOW + 50)
        df_mtf = add_ema(df_mtf, config.EMA_SLOW, f"EMA{config.EMA_SLOW}")
        mtf_bullish, mtf_bearish = get_trend_vs_ema200(df_mtf, config.EMA_SLOW)

        last_mtf = df_mtf.iloc[-1]
        ema_1h_val = last_mtf[f"EMA{config.EMA_SLOW}"]
        trend_strength_1h_pct = abs(last_mtf["close"] - ema_1h_val) / ema_1h_val * 100

    signals = detect_signals(
        df, 
        ema_fast=config.EMA_FAST,
        ema_slow=config.EMA_SLOW,
        rsi_min_long=config.RSI_MIN_LONG,
        rsi_max_short=config.RSI_MAX_SHORT,
        volume_threshold=config.VOLUME_THRESHOLD,
        adx_threshold=config.ADX_THRESHOLD,
        mtf_confirm_bullish=mtf_bullish,
        mtf_confirm_bearish=mtf_bearish,
        mtf_label=mtf_label
    )

    if not signals:
        return

    last_candle_time = df.iloc[-1]["datetime"].isoformat()
    last_price = df.iloc[-1]["close"]

    for signal_type, detail in signals:
        key = f"{symbol}_{signal_type}"
        if state.get(key) == last_candle_time:
            continue  # ya avisado para esta vela

        # --- Cooldown: no repetir el mismo símbolo+dirección demasiado seguido ---
        cooldown_key = f"{symbol}_{signal_type}_last_alert_ts"
        last_alert_ts = state.get(cooldown_key)
        if last_alert_ts:
            hours_since = (datetime.now(timezone.utc) - datetime.fromisoformat(last_alert_ts)).total_seconds() / 3600
            if hours_since < config.COOLDOWN_HOURS:
                state[key] = last_candle_time  # marcar la vela como vista, aunque no se avise
                continue

        emoji = "🟢" if "ALCISTA" in signal_type else "🔴"

        entries = build_limit_entries(df, config.EMA_FAST, config.EMA_SLOW, signal_type)
        entries_text = "\n".join(
            f"  • {e['label']}: `{e['price']:.4f}` — {e['basis']}" for e in entries
        )

        # --- Gestión de riesgo: SL / TP escalonados / apalancamiento sugerido ---
        risk = build_risk_management(
            df, signal_type, last_price,
            sl_atr_mult=config.SL_ATR_MULT,
            risk_target_pct=config.RISK_TARGET_PCT,
            rr_ratios=config.TP_RR_RATIOS,
            max_leverage=config.MAX_LEVERAGE
        )
        tps_text = "\n".join(
            f"  • {tp['label']}: `{tp['price']:.4f}` | {tp['pct']:.2f}% | RR {tp['rr']:.2f}"
            for tp in risk["tps"]
        )
        leverage_text = f"{risk['leverage_suggested']:.1f}x" if risk["leverage_suggested"] else "N/D"

        # --- Score ponderado (ADX, MACD, RSI, Volumen, Tendencia 1H, SSL) ---
        score, breakdown, semaforo = build_score(
            df, signal_type, trend_strength_1h_pct, weights=config.SCORE_WEIGHTS
        )
        breakdown_text = "\n".join(
            f"  • {name}: {pts}/{config.SCORE_WEIGHTS[key]} pts"
            for name, pts, key in [
                ("ADX", breakdown["ADX"], "adx"),
                ("MACD", breakdown["MACD"], "macd"),
                ("RSI", breakdown["RSI"], "rsi"),
                ("Volumen", breakdown["Volumen"], "volumen"),
                ("Tendencia 1H", breakdown["Tendencia 1H"], "tendencia_1h"),
                ("SSL", breakdown["SSL"], "ssl"),
            ]
        )

        # --- Indicadores en crudo (valores actuales, informativos) ---
        last_row = df.iloc[-1]
        indicators_text = (
            f"  • SSL Up: `{last_row['SSL_up']:.4f}` | SSL Down: `{last_row['SSL_down']:.4f}`\n"
            f"  • RSI: `{last_row['RSI']:.1f}`\n"
            f"  • MACD: `{last_row['MACD']:.4f}` | Señal: `{last_row['MACD_signal']:.4f}` | Hist: `{last_row['MACD_hist']:.4f}`\n"
            f"  • ADX: `{last_row['ADX']:.1f}` (+DI: `{last_row['ADX_plusDI']:.1f}` / -DI: `{last_row['ADX_minusDI']:.1f}`)\n"
            f"  • ATR: `{last_row['ATR']:.4f}`\n"
            f"  • Volumen medio: `{last_row['VOL_MA']:.2f}` | Volumen relativo: `{last_row['VOL_RATIO']:.2f}x`"
        )

        msg = (
            f"[{config.STRATEGY_LABEL}]\n"
            f"{emoji} *{symbol}* — señal *{signal_type}*\n"
            f"{detail}\n"
            f"Precio: `{last_price:.4f}`\n"
            f"Timeframe: `{config.TIMEFRAME}`\n"
            f"Vela: `{last_candle_time}`\n\n"
            f"Score: {score}/100 | Semáforo: {semaforo}\n"
            f"{breakdown_text}\n\n"
            f"*Indicadores:*\n{indicators_text}\n\n"
            f"*Entradas escalonadas sugeridas:*\n{entries_text}\n\n"
            f"*Gestión de riesgo (ATR):*\n"
            f"  • SL: `{risk['sl']:.4f}` ({risk['sl_pct']:.2f}%)\n"
            f"  • Apalancamiento sugerido (riesgo {config.RISK_TARGET_PCT:.0f}%): `{leverage_text}`\n"
            f"{tps_text}"
        )
        send_telegram(msg)
        print(msg.replace("*", "").replace("`", ""))
        state[key] = last_candle_time
        state[cooldown_key] = datetime.now(timezone.utc).isoformat()


def run_once():
    exchange_class = getattr(ccxt, config.EXCHANGE_ID)
    exchange = exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": config.MARKET_TYPE},
    })
    state = load_state()

    # --- TEST TEMPORAL: BORRAR ESTA LÍNEA CUANDO CONFIRMES QUE FUNCIONA ---
    # send_telegram(f"✅ Bot ejecutado correctamente ({config.EXCHANGE_ID}, {config.TIMEFRAME}) — {datetime.now(timezone.utc).isoformat()}")

    for symbol in config.SYMBOLS:
        try:
            check_symbol(exchange, symbol, state)
        except Exception as e:
            print(f"[ERROR] {symbol}: {e}")

    save_state(state)


def main():
    print(f"Bot iniciado {datetime.now(timezone.utc).isoformat()} | "
          f"Símbolos: {config.SYMBOLS} | Timeframe: {config.TIMEFRAME}")

    if "--once" in sys.argv:
        run_once()
        return

    while True:
        run_once()
        time.sleep(config.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
