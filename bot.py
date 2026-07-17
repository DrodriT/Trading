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
from indicators import compute_indicators, detect_signals, add_ema, get_trend_vs_ema200


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
        config.STOCH_K_PERIOD, config.STOCH_SMOOTH, config.STOCH_D_PERIOD
    )

    # --- Confirmación multi-timeframe (ej. 1h): tendencia según precio vs EMA200 ---
    mtf_bullish, mtf_bearish, mtf_label = None, None, ""
    if config.ENABLE_MTF_CONFIRMATION:
        mtf_label = config.CONFIRM_TIMEFRAME
        df_mtf = fetch_ohlcv(exchange, symbol, config.CONFIRM_TIMEFRAME, config.EMA_SLOW + 50)
        df_mtf = add_ema(df_mtf, config.EMA_SLOW, f"EMA{config.EMA_SLOW}")
        mtf_bullish, mtf_bearish = get_trend_vs_ema200(df_mtf, config.EMA_SLOW)

    signals = detect_signals(
        df, config.EMA_FAST, config.EMA_SLOW,
        config.STOCH_OVERSOLD, config.STOCH_OVERBOUGHT,
        config.REQUIRE_CONFLUENCE,
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

        emoji = "🟢" if "ALCISTA" in signal_type else "🔴"
        msg = (
            f"{emoji} *{symbol}* — señal *{signal_type}*\n"
            f"{detail}\n"
            f"Precio: `{last_price:.4f}`\n"
            f"Timeframe: `{config.TIMEFRAME}`\n"
            f"Vela: `{last_candle_time}`"
        )
        send_telegram(msg)
        print(msg.replace("*", "").replace("`", ""))
        state[key] = last_candle_time


def run_once():
    exchange_class = getattr(ccxt, config.EXCHANGE_ID)
    exchange = exchange_class({"enableRateLimit": True})
    state = load_state()

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
