# ============================================================
# BOT DE SEÑALES — Synapse Trail
# Modo GitHub Actions: ejecución única con persistencia de estado
# Uso: python bot.py --once
# ============================================================
import sys
import json
import time
import logging
import traceback
from datetime import datetime
from typing import Dict, Optional

import ccxt
import pandas as pd
import numpy as np

import config as cfg
from indicators import (
    compute_atr, compute_ema, compute_regime_score,
    compute_quality_score, grade_from_score
)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("synapse_signals")


# ============================================================
# TELEGRAM
# ============================================================
class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if self.enabled:
            logger.info("Telegram: configurado")
        else:
            logger.warning("Telegram: sin credenciales")

    def send(self, text: str):
        logger.info(f"\n{'='*40}\n{text}\n{'='*40}")
        if not self.enabled:
            return
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Telegram error: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram exception: {e}")


# ============================================================
# DATA FETCHER
# ============================================================
class DataFetcher:
    def __init__(self):
        self.exchange = ccxt.bitget({"enableRateLimit": True})
        logger.info("Bitget: conectado (datos públicos)")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"Error fetch {symbol} {timeframe}: {e}")
            return pd.DataFrame()


# ============================================================
# STATE MANAGER (persiste trail_state entre ejecuciones)
# ============================================================
class StateManager:
    def __init__(self, filepath: str = cfg.STATE_FILE):
        self.filepath = filepath
        self.data = {
            "trail_state": {},
            "last_candle_ts": {},
            "last_signal": {}
        }
        self.load()

    def load(self):
        try:
            with open(self.filepath, "r") as f:
                loaded = json.load(f)
                self.data["trail_state"] = loaded.get("trail_state", {})
                self.data["last_candle_ts"] = loaded.get("last_candle_ts", {})
                self.data["last_signal"] = loaded.get("last_signal", {})
            logger.info(f"Estado cargado: {len(self.data['trail_state'])} símbolos")
        except FileNotFoundError:
            logger.info("Sin estado previo. Empezando limpio.")
        except Exception as e:
            logger.error(f"Error cargando estado: {e}")

    def save(self):
        try:
            self.data["updated_at"] = datetime.utcnow().isoformat()
            with open(self.filepath, "w") as f:
                json.dump(self.data, f, indent=2, default=str)
            logger.info("Estado guardado")
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

    def get_trail_state(self, symbol: str) -> dict:
        default = {"dir": 0, "upper": None, "lower": None}
        return self.data["trail_state"].get(symbol, default)

    def set_trail_state(self, symbol: str, state: dict):
        self.data["trail_state"][symbol] = state

    def get_last_candle(self, symbol: str) -> int:
        return self.data["last_candle_ts"].get(symbol, 0)

    def set_last_candle(self, symbol: str, ts: int):
        self.data["last_candle_ts"][symbol] = ts

    def get_last_signal(self, symbol: str) -> str:
        return self.data["last_signal"].get(symbol, "")

    def set_last_signal(self, symbol: str, sig_id: str):
        self.data["last_signal"][symbol] = sig_id


# ============================================================
# SIGNAL ENGINE
# ============================================================
class SignalEngine:
    def __init__(self, state: StateManager):
        self.state = state

    def get_signal(self, symbol: str, df: pd.DataFrame,
                   htf_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
        if len(df) < max(cfg.ATR_LEN, cfg.TRAIL_LEN, cfg.REGIME_LEN) + 5:
            return None

        close = df["close"].values[-1]
        atr = compute_atr(df, cfg.ATR_LEN)
        center = compute_ema(df["close"], cfg.TRAIL_LEN)

        # Multiplicador adaptativo
        if cfg.USE_ADAPTIVE_MULT and len(atr) >= 100:
            vol_rank = (atr.iloc[-100:] < atr.iloc[-1]).sum() / 100 * 100.0
            mult_adjust = 0.8 if vol_rank < 30 else 1.25 if vol_rank > 70 else 1.0
        else:
            mult_adjust = 1.0

        effective_mult = cfg.BASE_MULT * mult_adjust
        raw_upper = center.iloc[-1] + atr.iloc[-1] * effective_mult
        raw_lower = center.iloc[-1] - atr.iloc[-1] * effective_mult

        # Cargar estado previo del trail
        trail_st = self.state.get_trail_state(symbol)
        prev_dir = trail_st.get("dir", 0)
        prev_upper = trail_st.get("upper", raw_upper)
        prev_lower = trail_st.get("lower", raw_lower)

        if prev_upper is None:
            prev_upper = raw_upper
        if prev_lower is None:
            prev_lower = raw_lower

        # Determinar dirección
        if close > prev_upper:
            new_dir = 1
        elif close < prev_lower:
            new_dir = -1
        else:
            new_dir = prev_dir if prev_dir != 0 else 0

        dir_flipped = new_dir != prev_dir

        # Ratchet
        if cfg.USE_RATCHET:
            if new_dir == 1:
                lower = max(raw_lower, prev_lower) if not dir_flipped else raw_lower
                upper = raw_upper
            elif new_dir == -1:
                upper = min(raw_upper, prev_upper) if not dir_flipped else raw_upper
                lower = raw_lower
            else:
                upper, lower = raw_upper, raw_lower
        else:
            upper, lower = raw_upper, raw_lower

        # Guardar estado
        self.state.set_trail_state(symbol, {"dir": new_dir, "upper": upper, "lower": lower})

        # Señal nueva
        raw_buy = new_dir == 1 and prev_dir == -1
        raw_sell = new_dir == -1 and prev_dir == 1

        if not raw_buy and not raw_sell:
            return None

        signal_dir = 1 if raw_buy else -1

        # Evitar duplicados
        candle_id = f"{symbol}_{df.index[-1]}"
        last_sig = self.state.get_last_signal(symbol)
        if last_sig == candle_id:
            return None
        self.state.set_last_signal(symbol, candle_id)

        # Régimen
        regime_score, regime_label, is_trending, is_choppy = compute_regime_score(
            df, cfg.ADX_PERIOD, cfg.CHOPPINESS_LEN, cfg.REGIME_LEN
        )

        # Quality Score
        quality = compute_quality_score(
            df, htf_df, signal_dir, regime_score,
            cfg.USE_HTF_FILTER, cfg.USE_VOLUME_FILTER,
            cfg.VOLUME_THRESHOLD, cfg.VOLUME_MA_PERIOD,
            cfg.RSI_PERIOD, atr, prev_upper, prev_lower
        )
        grade = grade_from_score(quality)

        if quality < cfg.MIN_QUALITY_SCORE:
            logger.info(f"{symbol}: {grade} ({quality:.0f}) < {cfg.MIN_QUALITY_SCORE}")
            return None

        # SL/TP
        atr_val = atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else close * 0.01
        sl_distance = atr_val * cfg.SL_MULT

        if signal_dir == 1:
            sl = close - sl_distance
            tp1 = close + sl_distance * cfg.TP1_MULT
            tp2 = close + sl_distance * cfg.TP2_MULT
            tp3 = close + sl_distance * cfg.TP3_MULT
        else:
            sl = close + sl_distance
            tp1 = close - sl_distance * cfg.TP1_MULT
            tp2 = close - sl_distance * cfg.TP2_MULT
            tp3 = close - sl_distance * cfg.TP3_MULT

        return {
            "symbol": symbol.replace("/USDT", ""),
            "direction": "LONG" if signal_dir == 1 else "SHORT",
            "entry": close,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "grade": grade,
            "quality": quality,
            "regime": regime_label,
            "regime_score": regime_score,
            "is_trending": is_trending,
            "is_choppy": is_choppy,
            "atr": atr_val,
            "rr_tp1": cfg.TP1_MULT,
            "rr_tp2": cfg.TP2_MULT,
            "rr_tp3": cfg.TP3_MULT,
            "timestamp": datetime.utcnow().strftime("%H:%M UTC")
        }


# ============================================================
# MESSAGE BUILDER
# ============================================================
def build_signal_message(s: dict) -> str:
    direction_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
    choppy_warn = " ⚠️CHOPPY" if s["is_choppy"] else ""

    if s["is_trending"]:
        regime_status = "✅ Trending"
    elif s["is_choppy"]:
        regime_status = "⚠️ Choppy"
    else:
        regime_status = "Mixed"

    pct_sl = (s["sl"] - s["entry"]) / s["entry"] * 100
    pct_tp1 = (s["tp1"] - s["entry"]) / s["entry"] * 100
    pct_tp2 = (s["tp2"] - s["entry"]) / s["entry"] * 100
    pct_tp3 = (s["tp3"] - s["entry"]) / s["entry"] * 100

    return (
        f"{direction_emoji} <b>{s['direction']} — {s['symbol']}</b>{choppy_warn}\n\n"
        f"💵 Entrada: <code>{s['entry']:.4f}</code>\n"
        f"🏅 Grade: <b>{s['grade']}</b> ({s['quality']:.0f}/100)\n\n"
        f"🛑 SL: <code>{s['sl']:.4f}</code> ({pct_sl:+.2f}%)\n"
        f"🎯 TP1: <code>{s['tp1']:.4f}</code> ({pct_tp1:+.2f}%) — {s['rr_tp1']}R\n"
        f"🎯 TP2: <code>{s['tp2']:.4f}</code> ({pct_tp2:+.2f}%) — {s['rr_tp2']}R\n"
        f"🎯 TP3: <code>{s['tp3']:.4f}</code> ({pct_tp3:+.2f}%) — {s['rr_tp3']}R\n\n"
        f"📊 Régimen: {regime_status} ({s['regime_score']:.0f}/100)\n"
        f"📏 ATR: {s['atr']:.4f}\n\n"
        f"⏰ {s['timestamp']}"
    )


# ============================================================
# BOT
# ============================================================
class SynapseSignalBot:
    def __init__(self):
        self.state = StateManager()
        self.data = DataFetcher()
        self.engine = SignalEngine(self.state)
        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)

    def has_new_candle(self, symbol: str, df: pd.DataFrame) -> bool:
        if df.empty:
            return False
        last_ts = int(df.index[-1].timestamp())
        prev_ts = self.state.get_last_candle(symbol)
        if prev_ts < last_ts:
            self.state.set_last_candle(symbol, last_ts)
            return True
        return False

    def process_symbol(self, symbol: str):
        try:
            df = self.data.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
            if df.empty or len(df) < 50:
                return

            if not self.has_new_candle(symbol, df):
                return

            htf_df = None
            if cfg.USE_HTF_FILTER:
                htf_df = self.data.fetch_ohlcv(symbol, cfg.CONFIRM_TIMEFRAME, limit=200)

            signal = self.engine.get_signal(symbol, df, htf_df)

            if signal:
                msg = build_signal_message(signal)
                self.notifier.send(msg)
                logger.info(f"SEÑAL: {signal['direction']} {signal['symbol']} "
                            f"Grade={signal['grade']} Q={signal['quality']:.0f}")

        except Exception as e:
            logger.error(f"Error en {symbol}: {e}")
            traceback.print_exc()

    def run_once(self):
        logger.info(f"Revisando {len(cfg.SYMBOLS)} símbolos...")
        for symbol in cfg.SYMBOLS:
            self.process_symbol(symbol)
            time.sleep(1)

        # Guardar estado al final
        self.state.save()
        logger.info("Ciclo completado. Estado guardado.")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    # Solo enviar mensaje de inicio si no estamos en GitHub Actions
    # (en Actions se ejecuta cada pocos minutos, no queremos spam)
    
    bot = SynapseSignalBot()
    bot.run_once()