# ============================================================
# BOT DE SEÑALES — Synapse Trail
# Solo analiza y envía alertas con SL + 3 TP por Telegram.
# NO ejecuta órdenes. Tú decides si entras.
# ============================================================
import sys
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
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("synapse_signals.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("synapse_signals")


# ============================================================
# TELEGRAM NOTIFIER
# ============================================================
class TelegramNotifier:
    """Envía mensajes por Telegram."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        if self.enabled:
            logger.info("Telegram: configurado correctamente")
        else:
            logger.warning("Telegram: sin token o chat_id. Los mensajes solo se verán en consola.")

    def send(self, text: str):
        """Envía un mensaje a Telegram."""
        # Siempre mostramos en consola
        logger.info(f"\n{'='*40}\n{text}\n{'='*40}")

        if not self.enabled:
            return

        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Telegram error: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram exception: {e}")


# ============================================================
# DATA FETCHER (datos públicos de Bitget, sin API keys)
# ============================================================
class DataFetcher:
    """Obtiene datos de mercado públicos."""

    def __init__(self):
        self.exchange = ccxt.bitget({"enableRateLimit": True})
        logger.info("Conectado a Bitget (datos públicos)")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Obtiene OHLCV como DataFrame."""
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(
                candles,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"Error fetch {symbol} {timeframe}: {e}")
            return pd.DataFrame()


# ============================================================
# SIGNAL ENGINE (análisis puro, sin ejecución)
# ============================================================
class SignalEngine:
    """Calcula señales basadas en Synapse Trail Pro."""

    def __init__(self):
        # Estado del trail por símbolo (para el ratchet)
        self.trail_state: Dict[str, dict] = {}
        # Para no repetir señales en la misma vela
        self.last_signal: Dict[str, str] = {}

    def get_signal(self, symbol: str, df: pd.DataFrame,
                   htf_df: Optional[pd.DataFrame] = None) -> Optional[dict]:
        """
        Calcula la señal actual.

        Devuelve un dict con la señal o None si no hay señal nueva.
        """
        if len(df) < max(cfg.ATR_LEN, cfg.TRAIL_LEN, cfg.REGIME_LEN) + 5:
            return None

        close = df["close"].values[-1]
        atr = compute_atr(df, cfg.ATR_LEN)
        center = compute_ema(df["close"], cfg.TRAIL_LEN)

        # --- Multiplicador adaptativo ---
        if cfg.USE_ADAPTIVE_MULT and len(atr) >= 100:
            vol_rank = (atr.iloc[-100:] < atr.iloc[-1]).sum() / 100 * 100.0
            mult_adjust = 0.8 if vol_rank < 30 else 1.25 if vol_rank > 70 else 1.0
        else:
            mult_adjust = 1.0

        effective_mult = cfg.BASE_MULT * mult_adjust
        raw_upper = center.iloc[-1] + atr.iloc[-1] * effective_mult
        raw_lower = center.iloc[-1] - atr.iloc[-1] * effective_mult

        # --- Estado anterior del trail ---
        trail_st = self.trail_state.get(
            symbol,
            {"dir": 0, "upper": raw_upper, "lower": raw_lower}
        )
        prev_dir = trail_st["dir"]
        prev_upper = trail_st["upper"]
        prev_lower = trail_st["lower"]

        # --- Determinar dirección ---
        if close > prev_upper:
            new_dir = 1
        elif close < prev_lower:
            new_dir = -1
        else:
            new_dir = prev_dir if prev_dir != 0 else 0

        dir_flipped = new_dir != prev_dir

        # --- Aplicar ratchet ---
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
        self.trail_state[symbol] = {"dir": new_dir, "upper": upper, "lower": lower}

        # --- ¿Señal nueva? ---
        raw_buy = new_dir == 1 and prev_dir == -1
        raw_sell = new_dir == -1 and prev_dir == 1

        if not raw_buy and not raw_sell:
            return None

        signal_dir = 1 if raw_buy else -1

        # Evitar señal duplicada en la misma vela
        candle_id = f"{symbol}_{df.index[-1]}"
        if self.last_signal.get(symbol) == candle_id:
            return None
        self.last_signal[symbol] = candle_id

        # --- Market Regime ---
        regime_score, regime_label, is_trending, is_choppy = compute_regime_score(
            df, cfg.ADX_PERIOD, cfg.CHOPPINESS_LEN, cfg.REGIME_LEN
        )

        # --- Quality Score ---
        quality = compute_quality_score(
            df, htf_df, signal_dir, regime_score,
            cfg.USE_HTF_FILTER, cfg.USE_VOLUME_FILTER,
            cfg.VOLUME_THRESHOLD, cfg.VOLUME_MA_PERIOD,
            cfg.RSI_PERIOD, atr, prev_upper, prev_lower
        )
        grade = grade_from_score(quality)

        # --- Filtro de calidad mínima ---
        if quality < cfg.MIN_QUALITY_SCORE:
            logger.info(
                f"{symbol}: señal {grade} ({quality:.0f}/100) "
                f"ignorada — mínimo: {cfg.MIN_QUALITY_SCORE}"
            )
            return None

        # --- Calcular SL y TPs sugeridos ---
        atr_val = atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else close * 0.01
        sl_distance = atr_val * cfg.SL_MULT

        if signal_dir == 1:  # LONG
            sl = close - sl_distance
            tp1 = close + sl_distance * cfg.TP1_MULT
            tp2 = close + sl_distance * cfg.TP2_MULT
            tp3 = close + sl_distance * cfg.TP3_MULT
        else:  # SHORT
            sl = close + sl_distance
            tp1 = close - sl_distance * cfg.TP1_MULT
            tp2 = close - sl_distance * cfg.TP2_MULT
            tp3 = close - sl_distance * cfg.TP3_MULT

        # --- Construir señal ---
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
    """Construye el mensaje formateado para Telegram."""

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
# BOT PRINCIPAL
# ============================================================
class SynapseSignalBot:
    """Bot que monitorea señales y envía alertas."""

    def __init__(self):
        self.data = DataFetcher()
        self.engine = SignalEngine()
        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)
        self.last_candle_ts: Dict[str, int] = {}

    def has_new_candle(self, symbol: str, df: pd.DataFrame) -> bool:
        """Detecta si hay una vela nueva sin procesar."""
        if df.empty:
            return False
        last_ts = int(df.index[-1].timestamp())
        if symbol not in self.last_candle_ts or self.last_candle_ts[symbol] < last_ts:
            self.last_candle_ts[symbol] = last_ts
            return True
        return False

    def process_symbol(self, symbol: str):
        """Procesa un símbolo: fetch → analyze → notify."""
        try:
            # Obtener datos
            df = self.data.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
            if df.empty or len(df) < 50:
                return

            # Solo procesar velas nuevas
            if not self.has_new_candle(symbol, df):
                return

            # HTF data (si el filtro está activo)
            htf_df = None
            if cfg.USE_HTF_FILTER:
                htf_df = self.data.fetch_ohlcv(symbol, cfg.CONFIRM_TIMEFRAME, limit=200)

            # Calcular señal
            signal = self.engine.get_signal(symbol, df, htf_df)

            if signal:
                msg = build_signal_message(signal)
                self.notifier.send(msg)
                logger.info(
                    f"SEÑAL: {signal['direction']} {signal['symbol']} | "
                    f"Grade: {signal['grade']} | Quality: {signal['quality']:.0f} | "
                    f"SL: {signal['sl']:.4f} | "
                    f"TP1: {signal['tp1']:.4f} | "
                    f"TP2: {signal['tp2']:.4f} | "
                    f"TP3: {signal['tp3']:.4f}"
                )

        except Exception as e:
            logger.error(f"Error procesando {symbol}: {e}")
            traceback.print_exc()

    def run_once(self):
        """Ejecuta un ciclo de revisión sobre todos los símbolos."""
        logger.info(f"Revisando {len(cfg.SYMBOLS)} símbolos...")
        for symbol in cfg.SYMBOLS:
            self.process_symbol(symbol)
            time.sleep(1)  # Pausa entre símbolos para respetar rate limits

    def run_loop(self):
        """Loop principal del bot."""
        logger.info("=" * 50)
        logger.info(f"🤖 Iniciando {cfg.STRATEGY_LABEL}")
        logger.info(f"   TF: {cfg.TIMEFRAME} | HTF: {cfg.CONFIRM_TIMEFRAME}")
        logger.info(f"   SL: {cfg.SL_MULT}×ATR | TP: {cfg.TP1_MULT}R/{cfg.TP2_MULT}R/{cfg.TP3_MULT}R")
        logger.info(f"   Símbolos: {len(cfg.SYMBOLS)} | Mín Grade: {cfg.MIN_QUALITY_SCORE}/100")
        logger.info("=" * 50)

        # Mensaje de inicio
        self.notifier.send(
            f"🤖 <b>{cfg.STRATEGY_LABEL}</b> INICIADO\n\n"
            f"📊 TF: {cfg.TIMEFRAME} | HTF: {cfg.CONFIRM_TIMEFRAME}\n"
            f"🛡️ SL: {cfg.SL_MULT}×ATR | "
            f"🎯 TP: {cfg.TP1_MULT}R/{cfg.TP2_MULT}R/{cfg.TP3_MULT}R\n"
            f"📡 Símbolos: {len(cfg.SYMBOLS)} | "
            f"🏅 Mín Grade: {cfg.MIN_QUALITY_SCORE}/100\n\n"
            f"Esperando señales..."
        )

        while True:
            try:
                self.run_once()
                logger.info(f"Ciclo completado. Esperando {cfg.CHECK_INTERVAL_SECONDS}s...")
                time.sleep(cfg.CHECK_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("Bot detenido por el usuario")
                self.notifier.send(f"🛑 <b>{cfg.STRATEGY_LABEL}</b> DETENIDO")
                break
            except Exception as e:
                logger.error(f"Error en el loop principal: {e}")
                traceback.print_exc()
                time.sleep(30)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    bot = SynapseSignalBot()
    bot.run_loop()