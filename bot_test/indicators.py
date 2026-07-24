# ============================================================
# INDICATORS — Synapse Trail Pro
# Porte fiel del indicador Pine Script v6 de WillyAlgoTrader
# ============================================================
import numpy as np
import pandas as pd
from typing import Tuple


def safe_div(num: float, den: float, fallback: float = 0.0) -> float:
    """División segura: devuelve fallback si den == 0."""
    if den == 0 or np.isnan(num) or np.isnan(den):
        return fallback
    return num / den


def r_squared(src: pd.Series, length: int) -> float:
    """
    R² de regresión lineal contra índice de barras.
    Mide la linealidad del precio. 1 = recta perfecta.
    """
    if len(src) < length:
        return 0.0
    y = src.values[-length:]
    x = np.arange(length)
    corr = np.corrcoef(x, y)[0, 1]
    if np.isnan(corr):
        return 0.0
    return corr ** 2


def grade_from_score(score: float) -> str:
    """Convierte Quality Score (0-100) en nota A/B/C."""
    if score >= 75:
        return "A"
    elif score >= 55:
        return "B"
    return "C"


def compute_atr(df: pd.DataFrame, length: int) -> pd.Series:
    """ATR con suavizado EMA (estilo TradingView)."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()


def compute_ema(series: pd.Series, length: int) -> pd.Series:
    """EMA con alpha = 2/(N+1)."""
    return series.ewm(span=length, adjust=False).mean()


def compute_rsi(close: pd.Series, length: int) -> float:
    """RSI estándar (Wilder smoothing)."""
    if len(close) < length + 1:
        return 50.0
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = safe_div(avg_gain.iloc[-1], avg_loss.iloc[-1], 0)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_adx(df: pd.DataFrame, length: int) -> Tuple[float, float, float]:
    """
    ADX + DI+ + DI-.
    Devuelve: (adx, di_plus, di_minus)
    """
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=length, adjust=False).mean()
    smooth_plus = pd.Series(plus_dm).ewm(span=length, adjust=False).mean()
    smooth_minus = pd.Series(minus_dm).ewm(span=length, adjust=False).mean()

    di_plus = safe_div(smooth_plus, atr, 0) * 100
    di_minus = safe_div(smooth_minus, atr, 0) * 100
    dx = safe_div((di_plus - di_minus).abs(), (di_plus + di_minus), 0) * 100
    adx = dx.ewm(span=length, adjust=False).mean()

    return (
        adx.iloc[-1] if not adx.empty else 0.0,
        di_plus.iloc[-1] if not di_plus.empty else 0.0,
        di_minus.iloc[-1] if not di_minus.empty else 0.0
    )


def compute_choppiness(df: pd.DataFrame, length: int) -> float:
    """
    Choppiness Index (0-100).
    Valores altos = mercado lateral/choppy.
    """
    if len(df) < length:
        return 50.0

    high = df["high"].values[-length:]
    low = df["low"].values[-length:]
    close = df["close"].values[-length:]

    ci_high = np.max(high)
    ci_low = np.min(low)
    ci_range = ci_high - ci_low

    if ci_range <= 0:
        return 100.0

    tr_sum = 0.0
    for i in range(1, length):
        tr_sum += max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )

    if tr_sum <= 0:
        return 50.0

    chop_raw = 100.0 * np.log10(tr_sum / ci_range) / np.log10(max(length, 2))
    return max(0.0, min(100.0, chop_raw))


def compute_regime_score(
    df: pd.DataFrame,
    adx_period: int = 14,
    choppiness_len: int = 14,
    regime_len: int = 50
) -> Tuple[float, str, bool, bool]:
    """
    Market Regime Score (0-100).
    Pesos: ADX 40% + Choppiness 35% + R² 25%

    Devuelve:
        score, label, is_trending, is_choppy
    """
    # ADX score (0-100)
    adx, _, _ = compute_adx(df, adx_period)
    adx_score = min(adx / 50.0 * 100.0, 100.0) if not np.isnan(adx) else 0.0

    # Choppiness → trend score (invertido)
    chop_raw = compute_choppiness(df, choppiness_len)
    chop_score = max(0.0, min(100.0, 100.0 - chop_raw))

    # R² (linealidad)
    r2 = r_squared(df["close"], regime_len)
    r2_score = r2 * 100.0

    # Composite
    score = adx_score * 0.40 + chop_score * 0.35 + r2_score * 0.25

    is_trending = score >= 60
    is_choppy = score < 35
    label = "Trending" if is_trending else "Choppy" if is_choppy else "Mixed"

    return score, label, is_trending, is_choppy


def compute_quality_score(
    df: pd.DataFrame,
    htf_df: pd.DataFrame or None,
    direction: int,
    regime_score: float,
    use_htf: bool,
    use_volume: bool,
    vol_threshold: float,
    vol_ma_period: int,
    rsi_period: int,
    atr_series: pd.Series,
    upper_band_prev: float,
    lower_band_prev: float
) -> float:
    """
    Quality Score (0-100).
    Pesos: HTF 30 + Volumen 20 + RSI 20 + Régimen 20 + Break 10
    """
    close_val = df["close"].values[-1]
    score = 0.0

    # 1. HTF Bias (30 pts)
    if use_htf and htf_df is not None and len(htf_df) >= 50:
        htf_ema = compute_ema(htf_df["close"], 50)
        if len(htf_ema) >= 2:
            htf_bull = htf_df["close"].values[-1] > htf_ema.values[-1]
            htf_bear = htf_df["close"].values[-1] < htf_ema.values[-1]
            if (direction == 1 and htf_bull) or (direction == -1 and htf_bear):
                score += 30.0
            elif (direction == 1 and htf_bear) or (direction == -1 and htf_bull):
                score += 0.0
            else:
                score += 15.0
        else:
            score += 15.0
    else:
        score += 15.0

    # 2. Volumen (20 pts)
    if use_volume and "volume" in df.columns and df["volume"].sum() > 0:
        vol_sma = df["volume"].rolling(vol_ma_period).mean()
        if len(vol_sma) > 0 and not np.isnan(vol_sma.values[-1]):
            if df["volume"].values[-1] > vol_sma.values[-1] * vol_threshold:
                score += 20.0
            else:
                score += 0.0
        else:
            score += 20.0
    else:
        score += 20.0

    # 3. RSI Momentum (20 pts)
    rsi_val = compute_rsi(df["close"], rsi_period)
    if (direction == 1 and rsi_val > 50) or (direction == -1 and rsi_val < 50):
        score += 20.0

    # 4. Régimen (20 pts)
    score += regime_score * 0.20

    # 5. Breakout Strength (10 pts)
    if not np.isnan(upper_band_prev) and not np.isnan(lower_band_prev):
        atr_val = atr_series.iloc[-1] if not np.isnan(atr_series.iloc[-1]) else 1.0
        if direction == 1:
            break_dist = close_val - upper_band_prev
        else:
            break_dist = lower_band_prev - close_val
        break_strength = min(abs(break_dist) / atr_val, 3.0) / 3.0 * 100.0
        score += break_strength * 0.10

    return score