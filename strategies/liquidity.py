"""
LIQUIDITY_GRAB — barrido rápido de un rango reciente con mecha significativa.

Extraída de strategy.py sin cambios de cálculo.
"""
import pandas as pd

from core.utils import is_atr_valid


def detect_liquidity_grab(df, cfg):
    """Mecha que barre el máximo/mínimo de la ventana reciente (LG_LOOKBACK)
    y cierra de nuevo dentro del rango."""
    if len(df) < cfg.LG_LOOKBACK + 2:
        return None
    last = df.iloc[-1]
    atr = last["ATR"]
    if not is_atr_valid(atr):
        return None

    window = df.iloc[-(cfg.LG_LOOKBACK + 1):-1]
    recent_low = window["low"].min()
    recent_high = window["high"].max()

    if last["low"] < recent_low and last["close"] > recent_low:
        wick = recent_low - last["low"]
        if wick / atr < cfg.LG_MIN_WICK_ATR_RATIO:
            return None
        score = min(wick / atr, 1.5) / 1.5 * 100.0
        return {
            "direction": "ALCISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Barrido de mínimos recientes con mecha significativa y cierre dentro del rango",
            "metadata": {"wick": wick, "atr": atr, "recent_low": recent_low, "wick_atr_ratio": wick / atr},
        }

    if last["high"] > recent_high and last["close"] < recent_high:
        wick = last["high"] - recent_high
        if wick / atr < cfg.LG_MIN_WICK_ATR_RATIO:
            return None
        score = min(wick / atr, 1.5) / 1.5 * 100.0
        return {
            "direction": "BAJISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Barrido de máximos recientes con mecha significativa y cierre dentro del rango",
            "metadata": {"wick": wick, "atr": atr, "recent_high": recent_high, "wick_atr_ratio": wick / atr},
        }

    return None
