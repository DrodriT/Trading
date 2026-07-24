# ============================================================
# INDICATORS — Synapse Trail Pro
# ============================================================
import numpy as np
import pandas as pd
from typing import Tuple


def safe_div(num: float, den: float, fallback: float = 0.0) -> float:
    if den == 0 or np.isnan(num) or np.isnan(den):
        return fallback
    return num / den


def r_squared(src: pd.Series, length: int) -> float:
    if len(src) < length:
        return 0.0
    y = src.values[-length:]
    x = np.arange(length)
    corr = np.corrcoef(x, y)[0, 1]
    if np.isnan(corr):
        return 0.0
    return corr ** 2


def grade_from_score(score: float) -> str:
    if score >= 75:
        return "A"
    elif score >= 55:
        return "B"
    return "C"


def compute_atr(df: pd.DataFrame, length: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()


def compute_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def compute_rsi(close: pd.Series, length: int) -> float:
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
    di_plus = safe_div(pd.Series(plus_dm).ewm(span=length, adjust=False).mean(), atr, 0) * 100
    di_minus = safe_div(pd.Series(minus_dm).ewm(span=length, adjust=False).mean(), atr, 0) * 100
    dx = safe_div((di_plus - di_minus).abs(), (di_plus + di_minus), 0) * 100
    adx = dx.ewm(span=length, adjust=False).mean()
    return (
        adx.iloc[-1] if not adx.empty else 0.0,
        di_plus.iloc[-1] if not di_plus.empty else 0.0,
        di_minus.iloc[-1] if not di_minus.empty else 0.0
    )


def compute_choppiness(df: pd.DataFrame, length: int) -> float:
    if len(df) < length:
        return 50.0
    high = df["high"].values[-length:]
    low = df["low"].values[-length:]
    close = df["close"].values[-length:]
    ci_range = np.max(high) - np.min(low)
    if ci_range <= 0:
        return 100.0
    tr_sum = 0.0
    for i in range(1, length):
        tr_sum += max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    if tr_sum <= 0:
        return 50.0
    chop_raw = 100.0 * np.log10(tr_sum / ci_range) / np.log10(max(length, 2))
    return max(0.0, min(100.0, chop_raw))


def compute_regime_score(df, adx_period=14, choppiness_len=14, regime_len=50):
    adx, _, _ = compute_adx(df, adx_period)
    adx_score = min(adx / 50.0 * 100.0, 100.0) if not np.isnan(adx) else 0.0
    chop_raw = compute_choppiness(df, choppiness_len)
    chop_score = max(0.0, min(100.0, 100.0 - chop_raw))
    r2 = r_squared(df["close"], regime_len)
    r2_score = r2 * 100.0
    score = adx_score * 0.40 + chop_score * 0.35 + r2_score * 0.25
    is_trending = score >= 60
    is_choppy = score < 35
    label = "Trending" if is_trending else "Choppy" if is_choppy else "Mixed"
    return score, label, is_trending, is_choppy


def compute_quality_score(df, htf_df, direction, regime_score, use_htf, use_volume,
                          vol_threshold, vol_ma_period, rsi_period, atr_series,
                          upper_band_prev, lower_band_prev):
    close_val = df["close"].values[-1]
    score = 0.0

    # HTF (30 pts)
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

    # Volumen (20 pts)
    if use_volume and "volume" in df.columns and df["volume"].sum() > 0:
        vol_sma = df["volume"].rolling(vol_ma_period).mean()
        if len(vol_sma) > 0 and not np.isnan(vol_sma.values[-1]):
            if df["volume"].values[-1] > vol_sma.values[-1] * vol_threshold:
                score += 20.0
        else:
            score += 20.0
    else:
        score += 20.0

    # RSI (20 pts)
    rsi_val = compute_rsi(df["close"], rsi_period)
    if (direction == 1 and rsi_val > 50) or (direction == -1 and rsi_val < 50):
        score += 20.0

    # Régimen (20 pts)
    score += regime_score * 0.20

    # Breakout Strength (10 pts)
    if not np.isnan(upper_band_prev) and not np.isnan(lower_band_prev):
        atr_val = atr_series.iloc[-1] if not np.isnan(atr_series.iloc[-1]) else 1.0
        if direction == 1:
            break_dist = close_val - upper_band_prev
        else:
            break_dist = lower_band_prev - close_val
        break_strength = min(abs(break_dist) / atr_val, 3.0) / 3.0 * 100.0
        score += break_strength * 0.10

    return score