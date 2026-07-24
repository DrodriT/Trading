# ============================================================
# BOT DE SEÑALES + SEGUIMIENTO — Synapse Trail
# - Detecta señales de entrada (SL + 3 TP)
# - Monitorea posición activa (TP1/TP2/TP3/SL/BE)
# - Persiste estado en state.json
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
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("synapse_bot")


# ============================================================
# TELEGRAM
# ============================================================
class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

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
# STATE MANAGER
# ============================================================
class StateManager:
    def __init__(self, filepath: str = cfg.STATE_FILE):
        self.filepath = filepath
        self.data = {
            "trail_state": {},
            "last_candle_ts": {},
            "last_signal": {},
            "active_positions": {}  # symbol -> posición activa
        }
        self.load()

    def load(self):
        try:
            with open(self.filepath, "r") as f:
                loaded = json.load(f)
                self.data["trail_state"] = loaded.get("trail_state", {})
                self.data["last_candle_ts"] = loaded.get("last_candle_ts", {})
                self.data["last_signal"] = loaded.get("last_signal", {})
                self.data["active_positions"] = loaded.get("active_positions", {})
            logger.info(f"Estado cargado: {len(self.data['active_positions'])} posiciones activas")
        except FileNotFoundError:
            logger.info("Sin estado previo.")
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

    # Trail state
    def get_trail_state(self, symbol: str) -> dict:
        default = {"dir": 0, "upper": None, "lower": None}
        return self.data["trail_state"].get(symbol, default)

    def set_trail_state(self, symbol: str, state: dict):
        self.data["trail_state"][symbol] = state

    # Last candle
    def get_last_candle(self, symbol: str) -> int:
        return self.data["last_candle_ts"].get(symbol, 0)

    def set_last_candle(self, symbol: str, ts: int):
        self.data["last_candle_ts"][symbol] = ts

    # Last signal
    def get_last_signal(self, symbol: str) -> str:
        return self.data["last_signal"].get(symbol, "")

    def set_last_signal(self, symbol: str, sig_id: str):
        self.data["last_signal"][symbol] = sig_id

    # Active positions
    def get_position(self, symbol: str) -> Optional[dict]:
        return self.data["active_positions"].get(symbol)

    def set_position(self, symbol: str, pos: dict):
        self.data["active_positions"][symbol] = pos

    def remove_position(self, symbol: str):
        if symbol in self.data["active_positions"]:
            del self.data["active_positions"][symbol]

    def has_position(self, symbol: str) -> bool:
        return symbol in self.data["active_positions"]


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

        if cfg.USE_ADAPTIVE_MULT and len(atr) >= 100:
            vol_rank = (atr.iloc[-100:] < atr.iloc[-1]).sum() / 100 * 100.0
            mult_adjust = 0.8 if vol_rank < 30 else 1.25 if vol_rank > 70 else 1.0
        else:
            mult_adjust = 1.0

        effective_mult = cfg.BASE_MULT * mult_adjust
        raw_upper = center.iloc[-1] + atr.iloc[-1] * effective_mult
        raw_lower = center.iloc[-1] - atr.iloc[-1] * effective_mult

        trail_st = self.state.get_trail_state(symbol)
        prev_dir = trail_st.get("dir", 0)
        prev_upper = trail_st.get("upper", raw_upper)
        prev_lower = trail_st.get("lower", raw_lower)
        if prev_upper is None:
            prev_upper = raw_upper
        if prev_lower is None:
            prev_lower = raw_lower

        if close > prev_upper:
            new_dir = 1
        elif close < prev_lower:
            new_dir = -1
        else:
            new_dir = prev_dir if prev_dir != 0 else 0

        dir_flipped = new_dir != prev_dir

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

        self.state.set_trail_state(symbol, {"dir": new_dir, "upper": upper, "lower": lower})

        raw_buy = new_dir == 1 and prev_dir == -1
        raw_sell = new_dir == -1 and prev_dir == 1

        if not raw_buy and not raw_sell:
            return None

        signal_dir = 1 if raw_buy else -1

        candle_id = f"{symbol}_{df.index[-1]}"
        last_sig = self.state.get_last_signal(symbol)
        if last_sig == candle_id:
            return None
        self.state.set_last_signal(symbol, candle_id)

        regime_score, regime_label, is_trending, is_choppy = compute_regime_score(
            df, cfg.ADX_PERIOD, cfg.CHOPPINESS_LEN, cfg.REGIME_LEN
        )

        quality = compute_quality_score(
            df, htf_df, signal_dir, regime_score,
            cfg.USE_HTF_FILTER, cfg.USE_VOLUME_FILTER,
            cfg.VOLUME_THRESHOLD, cfg.VOLUME_MA_PERIOD,
            cfg.RSI_PERIOD, atr, prev_upper, prev_lower
        )
        grade = grade_from_score(quality)

        if quality < cfg.MIN_QUALITY_SCORE:
            logger.info(f"⏭️ {symbol}: señal {grade} ({quality:.0f}) ignorada — mínimo {cfg.MIN_QUALITY_SCORE}")
            return None

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
            "symbol_full": symbol,
            "direction": "LONG" if signal_dir == 1 else "SHORT",
            "direction_int": signal_dir,
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
# EXIT MONITOR (monitorea SL/TP de posición activa)
# ============================================================
class ExitMonitor:
    def __init__(self, state: StateManager, notifier: TelegramNotifier):
        self.state = state
        self.notifier = notifier

    def check_exits(self, symbol: str, df: pd.DataFrame) -> bool:
        """
        Revisa si el precio tocó SL, TP1, TP2 o TP3 de la posición activa.
        Devuelve True si la posición se cerró.
        """
        pos = self.state.get_position(symbol)
        if not pos:
            return False

        high = df["high"].values[-1]
        low = df["low"].values[-1]
        close = df["close"].values[-1]
        direction = pos["direction_int"]
        symbol_short = symbol.replace("/USDT", "")
        closed = False

        # SL hit
        sl_hit = (direction == 1 and low <= pos["sl"]) or (direction == -1 and high >= pos["sl"])

        # TP hits
        tp3_hit = (direction == 1 and high >= pos["tp3"]) or (direction == -1 and low <= pos["tp3"])
        tp2_hit = (direction == 1 and high >= pos["tp2"]) or (direction == -1 and low <= pos["tp2"])
        tp1_hit = (direction == 1 and high >= pos["tp1"]) or (direction == -1 and low <= pos["tp1"])

        # SL tiene prioridad
        if sl_hit:
            be_tag = "🛡️ BE" if pos.get("be_active", False) else "🛑 SL"
            entry = pos["entry"]
            sl_price = pos["sl"]
            entry_pct = (sl_price - entry) / entry * 100

            msg = (
                f"{be_tag} <b>{symbol_short}</b>\n\n"
                f"💵 Salida: <code>{sl_price:.4f}</code> ({entry_pct:+.2f}% desde entrada)\n"
                f"📊 {'Sin pérdida (Break-Even activo)' if pos.get('be_active') else 'Stop Loss alcanzado'}\n\n"
                f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
            )
            self.notifier.send(msg)
            logger.info(f"SL/BE {symbol_short} @ {sl_price:.4f}")
            self.state.remove_position(symbol)
            return True

        # TP3 (cierre total)
        if tp3_hit and not pos.get("tp3_reached"):
            pos["tp3_reached"] = True
            entry = pos["entry"]
            tp3_price = pos["tp3"]
            pct = (tp3_price - entry) / entry * 100

            # Calcular PnL estimado
            r_total = (cfg.TP1_MULT + cfg.TP2_MULT + cfg.TP3_MULT) / 3

            msg = (
                f"🏆 <b>TP3 ALCANZADO — {symbol_short}</b>\n\n"
                f"💵 Entrada: <code>{entry:.4f}</code>\n"
                f"🎯 TP3: <code>{tp3_price:.4f}</code> ({pct:+.2f}%)\n"
                f"📊 R promedio estimado: {r_total:.1f}R\n\n"
                f"✅ <b>POSICIÓN CERRADA</b>\n\n"
                f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
            )
            self.notifier.send(msg)
            logger.info(f"TP3 {symbol_short} @ {tp3_price:.4f} | Cerrada")
            self.state.remove_position(symbol)
            return True

        # TP2
        if tp2_hit and not pos.get("tp2_reached"):
            pos["tp2_reached"] = True
            self.state.set_position(symbol, pos)
            entry = pos["entry"]
            tp2_price = pos["tp2"]
            pct = (tp2_price - entry) / entry * 100

            msg = (
                f"🎯🎯 <b>TP2 ALCANZADO — {symbol_short}</b>\n\n"
                f"💵 Precio: <code>{tp2_price:.4f}</code> ({pct:+.2f}% desde entrada)\n"
                f"📊 Cierre parcial sugerido: 33% (66% total cerrado)\n"
                f"📈 Restante hacia TP3: <code>{pos['tp3']:.4f}</code>\n\n"
                f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
            )
            self.notifier.send(msg)
            logger.info(f"TP2 {symbol_short} @ {tp2_price:.4f}")

        # TP1
        if tp1_hit and not pos.get("tp1_reached"):
            pos["tp1_reached"] = True
            if cfg.USE_BREAK_EVEN and not pos.get("be_active"):
                pos["be_active"] = True
                pos["sl"] = pos["entry"]  # Mover SL a entrada
            self.state.set_position(symbol, pos)
            entry = pos["entry"]
            tp1_price = pos["tp1"]
            pct = (tp1_price - entry) / entry * 100

            be_msg = "\n🛡️ <b>SL movido a Break-Even</b> (entrada)" if pos.get("be_active") else ""

            msg = (
                f"🎯 <b>TP1 ALCANZADO — {symbol_short}</b>\n\n"
                f"💵 Precio: <code>{tp1_price:.4f}</code> ({pct:+.2f}% desde entrada)\n"
                f"📊 Cierre parcial sugerido: 33%{be_msg}\n"
                f"📈 Restante hacia TP2: <code>{pos['tp2']:.4f}</code> | TP3: <code>{pos['tp3']:.4f}</code>\n\n"
                f"⏰ {datetime.utcnow().strftime('%H:%M UTC')}"
            )
            self.notifier.send(msg)
            logger.info(f"TP1 {symbol_short} @ {tp1_price:.4f}" + (" | BE activado" if pos.get("be_active") else ""))

        return False


# ============================================================
# MESSAGE BUILDER (ENTRADA)
# ============================================================
def build_entry_message(s: dict) -> str:
    direction_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
    choppy_warn = " ⚠️CHOPPY" if s["is_choppy"] else ""
    regime_status = "✅ Trending" if s["is_trending"] else ("⚠️ Choppy" if s["is_choppy"] else "Mixed")

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
# BOT PRINCIPAL
# ============================================================
class SynapseBot:
    def __init__(self):
        self.state = StateManager()
        self.data = DataFetcher()
        self.engine = SignalEngine(self.state)
        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)
        self.exits = ExitMonitor(self.state, self.notifier)

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
            # Fetch data
            df = self.data.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
            if df.empty or len(df) < 50:
                return

            # Solo procesar velas nuevas
            if not self.has_new_candle(symbol, df):
                return

            # ============================================================
            # 1. PRIMERO: REVISAR SALIDAS (posición activa)
            # ============================================================
            if self.state.has_position(symbol):
                closed = self.exits.check_exits(symbol, df)
                if closed:
                    return  # Posición cerrada, no buscar entrada

            # ============================================================
            # 2. LUEGO: BUSCAR NUEVAS ENTRADAS
            # ============================================================
            htf_df = None
            if cfg.USE_HTF_FILTER:
                htf_df = self.data.fetch_ohlcv(symbol, cfg.CONFIRM_TIMEFRAME, limit=200)

            signal = self.engine.get_signal(symbol, df, htf_df)

            # Log de diagnóstico para cada símbolo
            if signal:
                logger.info(f"✅ {symbol}: {signal['direction']} Grade={signal['grade']} Q={signal['quality']:.0f}")
            else:
                logger.info(f"⚪ {symbol}: sin señal en esta vela")

            if signal:
                # Verificar si hay flip (señal contraria con posición activa)
                existing_pos = self.state.get_position(symbol)
                if existing_pos:
                    if existing_pos["direction_int"] != signal["direction_int"]:
                        # FLIP
                        logger.info(f"FLIP {signal['symbol']}: {existing_pos['direction']} → {signal['direction']}")
                        self.state.remove_position(symbol)

                # Guardar nueva posición
                self.state.set_position(symbol, {
                    "symbol": symbol,
                    "direction": signal["direction"],
                    "direction_int": signal["direction_int"],
                    "entry": signal["entry"],
                    "sl": signal["sl"],
                    "tp1": signal["tp1"],
                    "tp2": signal["tp2"],
                    "tp3": signal["tp3"],
                    "grade": signal["grade"],
                    "quality": signal["quality"],
                    "tp1_reached": False,
                    "tp2_reached": False,
                    "tp3_reached": False,
                    "be_active": False,
                    "opened_at": datetime.utcnow().isoformat()
                })

                # Enviar mensaje de entrada
                msg = build_entry_message(signal)
                self.notifier.send(msg)
                logger.info(f"ENTRADA: {signal['direction']} {signal['symbol']} "
                            f"Grade={signal['grade']} Q={signal['quality']:.0f}")

        except Exception as e:
            logger.error(f"Error en {symbol}: {e}")
            traceback.print_exc()

    def run_once(self):
        logger.info(f"Revisando {len(cfg.SYMBOLS)} símbolos...")
        for symbol in cfg.SYMBOLS:
            self.process_symbol(symbol)
            time.sleep(1)

        self.state.save()
        logger.info("Ciclo completado. Estado guardado.")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    bot = SynapseBot()
    bot.run_once()