"""
TREND_PULLBACK — pullback a la EMA rápida dentro de una tendencia
establecida (ADX por encima del mínimo configurado).

Extraída de strategy.py sin cambios de cálculo.
"""
import pandas as pd


def detect_trend_pullback(df, cfg):
    """Pullback hasta la EMA rápida seguido de una vela de rechazo en la
    dirección de la tendencia (EMA rápida vs. lenta + ADX mínimo)."""
    if len(df) < 3:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    ema_fast_col = f"EMA{cfg.EMA_FAST}"
    ema_slow_col = f"EMA{cfg.EMA_SLOW}"
    adx = last["ADX"]
    if pd.isna(adx) or pd.isna(last[ema_fast_col]) or pd.isna(prev[ema_fast_col]):
        return None

    is_uptrend = last[ema_fast_col] > last[ema_slow_col] and adx >= cfg.TREND_ADX_MIN
    is_downtrend = last[ema_fast_col] < last[ema_slow_col] and adx >= cfg.TREND_ADX_MIN

    if (is_uptrend and prev["low"] <= prev[ema_fast_col]
            and last["close"] > last[ema_fast_col] and last["close"] > last["open"]):
        score = min(adx / 50.0, 1.0) * 100.0
        return {
            "direction": "ALCISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Pullback a la EMA rápida con rechazo alcista dentro de tendencia alcista establecida",
            "metadata": {"adx": adx, ema_fast_col: last[ema_fast_col], ema_slow_col: last[ema_slow_col]},
        }

    if (is_downtrend and prev["high"] >= prev[ema_fast_col]
            and last["close"] < last[ema_fast_col] and last["close"] < last["open"]):
        score = min(adx / 50.0, 1.0) * 100.0
        return {
            "direction": "BAJISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Pullback a la EMA rápida con rechazo bajista dentro de tendencia bajista establecida",
            "metadata": {"adx": adx, ema_fast_col: last[ema_fast_col], ema_slow_col: last[ema_slow_col]},
        }

    return None
