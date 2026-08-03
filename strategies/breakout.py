"""
BREAKOUT — ruptura del rango reciente con confirmación de volumen.

Extraída de strategy.py sin cambios de cálculo.
"""
import pandas as pd


def detect_breakout(df, cfg):
    """Cierre fuera del rango de las últimas BREAKOUT_LOOKBACK velas, con
    volumen por encima del umbral configurado (BREAKOUT_VOL_THRESHOLD)."""
    if len(df) < cfg.BREAKOUT_LOOKBACK + 2:
        return None
    last = df.iloc[-1]
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None

    window = df.iloc[-(cfg.BREAKOUT_LOOKBACK + 1):-1]
    range_high = window["high"].max()
    range_low = window["low"].min()
    vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0

    if last["close"] > range_high and vol_ratio >= cfg.BREAKOUT_VOL_THRESHOLD:
        break_dist = last["close"] - range_high
        score = min(break_dist / atr, 1.5) / 1.5 * 60.0
        score += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        score = min(score, 100.0)
        return {
            "direction": "ALCISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Ruptura alcista del rango reciente con volumen por encima del umbral",
            "metadata": {"range_high": range_high, "break_dist": break_dist, "vol_ratio": vol_ratio},
        }

    if last["close"] < range_low and vol_ratio >= cfg.BREAKOUT_VOL_THRESHOLD:
        break_dist = range_low - last["close"]
        score = min(break_dist / atr, 1.5) / 1.5 * 60.0
        score += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        score = min(score, 100.0)
        return {
            "direction": "BAJISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Ruptura bajista del rango reciente con volumen por encima del umbral",
            "metadata": {"range_low": range_low, "break_dist": break_dist, "vol_ratio": vol_ratio},
        }

    return None
