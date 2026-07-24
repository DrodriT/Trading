# ============================================================
# INDICATORS — Rodri bot Pro (portado fielmente de Pine Script v6)
# ============================================================
import numpy as np
import pandas as pd
from typing import Tuple, Optional


# ============================================================
# UTILIDADES
# ============================================================

def safe_div(num: float, den: float, fallback: float = 0.0) -> float:
    """División segura: devuelve fallback si den == 0."""
    return num / den if den != 0 and not np.isnan(num) and not np.isnan(den) else fallback


def r_squared(src: pd.Series, length: int) -> float:
    """
    R² de regresión lineal contra índice de barras (mide linealidad).
    Valor entre 0 y 1. 1 = movimiento perfectamente recto.
    """
    if len(src) < length:
        return 0.0
    x = np.arange(length)
    y = src.values[-length:]
    corr = np.corrcoef(x, y)[0, 1]
    return corr ** 2 if not np.isnan(corr) else 0.0


def percent_rank(series: pd.Series, value: float) -> float:
    """
    Percentil de 'value' dentro de 'series'.
    Devuelve 0-100.
    """
    if len(series) == 0 or series.isna().all():
        return 50.0
    return (series < value).sum() / len(series) * 100.0


def grade_from_score(score: float) -> str:
    """Convierte Quality Score (0-100) en nota A/B/C."""
    if score >= 75:
        return "A"
    elif score >= 55:
        return "B"
    else:
        return "C"


# ============================================================
# INDICADORES PRINCIPALES
# ============================================================

def compute_atr(df: pd.DataFrame, length: int) -> pd.Series:
    """True Range → ATR (EMA suavizado, como TradingView)."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()


def compute_adx(df: pd.DataFrame, length: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX + DI+ + DI- (implementación manual).
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
    smooth_plus_dm = pd.Series(plus_dm).ewm(span=length, adjust=False).mean()
    smooth_minus_dm = pd.Series(minus_dm).ewm(span=length, adjust=False).mean()

    di_plus = safe_div(smooth_plus_dm, atr, 0) * 100
    di_minus = safe_div(smooth_minus_dm, atr, 0) * 100

    dx = safe_div((di_plus - di_minus).abs(), (di_plus + di_minus), 0) * 100
    adx = dx.ewm(span=length, adjust=False).mean()

    return adx, di_plus, di_minus


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

    # True Range sum
    tr_list = []
    for i in range(1, length):
        tr_list.append(max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        ))
    tr_sum = sum(tr_list)

    if ci_range <= 0:
        return 100.0
    if tr_sum <= 0:
        return 50.0

    chop_raw = 100.0 * np.log10(tr_sum / ci_range) / np.log10(max(length, 2))
    return max(0.0, min(100.0, chop_raw))


def compute_rsi(close: pd.Series, length: int) -> float:
    """RSI estándar (Wilder smoothing)."""
    if len(close) < length + 1:
        return 50.0

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()

    rs = safe_div(avg_gain.iloc[-1], avg_loss.iloc[-1], 0)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(series: pd.Series, length: int) -> pd.Series:
    """EMA (alpha = 2/(N+1), igual que TradingView)."""
    return series.ewm(span=length, adjust=False).mean()


# ============================================================
# SYNAPSE TRAIL — BANDAS CON RATCHET
# ============================================================

def compute_synapse_trail(
    df: pd.DataFrame,
    atr_len: int,
    trail_len: int,
    base_mult: float,
    use_adaptive: bool,
    use_ratchet: bool
) -> Tuple[int, float, float, float, float]:
    """
    Calcula la banda Synapse Trail.

    Parámetros:
        df: DataFrame con OHLCV
        atr_len: período ATR
        trail_len: período EMA del centro
        base_mult: multiplicador base del ATR
        use_adaptive: ajustar multiplicador por volatilidad
        use_ratchet: trinquete (banda solo se aprieta)

    Devuelve:
        dir: 1 (long), -1 (short), 0 (sin dirección)
        trail_line: precio de la banda activa
        upper_band: banda superior
        lower_band: banda inferior
        center: centro (EMA)
    """
    if len(df) < max(atr_len, trail_len) + 5:
        return 0, np.nan, np.nan, np.nan, np.nan

    atr = compute_atr(df, atr_len)
    center = compute_ema(df["close"], trail_len)

    # Multiplicador adaptativo
    if use_adaptive:
        vol_rank = percent_rank(atr.iloc[-100:], atr.iloc[-1]) if len(atr) >= 100 else 50.0
        mult_adjust = 0.8 if vol_rank < 30 else 1.25 if vol_rank > 70 else 1.0
    else:
        mult_adjust = 1.0

    effective_mult = base_mult * mult_adjust

    raw_upper = center.iloc[-1] + atr.iloc[-1] * effective_mult
    raw_lower = center.iloc[-1] - atr.iloc[-1] * effective_mult

    # Dirección: se necesita la barra anterior para decidir
    # Usamos un enfoque simplificado con estado acumulado
    if len(df) < 2:
        return 0, np.nan, raw_upper, raw_lower, center.iloc[-1]

    return 0, np.nan, raw_upper, raw_lower, center.iloc[-1]


# ============================================================
# MARKET REGIME SCORE
# ============================================================

def compute_regime_score(
    df: pd.DataFrame,
    adx_period: int,
    choppiness_len: int,
    regime_len: int
) -> Tuple[float, str, bool, bool]:
    """
    Calcula el Market Regime Score (0-100).

    Pesos: ADX 40% + Choppiness 35% + R² 25%

    Devuelve:
        score: 0-100
        label: "Trending" / "Mixed" / "Choppy"
        is_trending: True si score >= 60
        is_choppy: True si score < 35
    """
    # ADX score (0-100)
    adx, _, _ = compute_adx(df, adx_period)
    adx_val = adx.iloc[-1] if not adx.empty and not np.isnan(adx.iloc[-1]) else 0
    adx_score = min(adx_val / 50.0 * 100.0, 100.0)

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


# ============================================================
# QUALITY SCORE (Multi-Factor)
# ============================================================

def compute_quality_score(
    df: pd.DataFrame,
    htf_df: Optional[pd.DataFrame],
    direction: int,
    regime_score: float,
    htf_filter_on: bool,
    volume_filter_on: bool,
    vol_threshold: float,
    vol_ma_period: int,
    rsi_period: int,
    atr: pd.Series,
    upper_band_prev: float,
    lower_band_prev: float
) -> float:
    """
    Quality Score (0-100) para una señal en 'direction'.

    Pesos: HTF 30 + Volumen 20 + RSI 20 + Régimen 20 + Break 10
    """
    close = df["close"].values[-1] if len(df) > 0 else 0.0
    score = 0.0

    # 1. HTF Bias (30 pts)
    if htf_filter_on and htf_df is not None and len(htf_df) >= 50:
        htf_ema = compute_ema(htf_df["close"], 50)
        htf_bull = htf_df["close"].values[-1] > htf_ema.values[-1]
        htf_bear = htf_df["close"].values[-1] < htf_ema.values[-1]

        if (direction == 1 and htf_bull) or (direction == -1 and htf_bear):
            score += 30.0
        elif (direction == 1 and htf_bear) or (direction == -1 and htf_bull):
            score += 0.0
        else:
            score += 15.0  # HTF flat o sin datos
    else:
        score += 15.0

    # 2. Volumen (20 pts)
    if volume_filter_on and "volume" in df.columns and df["volume"].sum() > 0:
        vol_sma = df["volume"].rolling(vol_ma_period).mean()
        if len(vol_sma) > 0 and not np.isnan(vol_sma.values[-1]):
            if df["volume"].values[-1] > vol_sma.values[-1] * vol_threshold:
                score += 20.0
        else:
            score += 20.0  # Sin datos de volumen: full credit
    else:
        score += 20.0  # Filtro off: full credit

    # 3. RSI Momentum (20 pts)
    rsi_val = compute_rsi(df["close"], rsi_period)
    if (direction == 1 and rsi_val > 50) or (direction == -1 and rsi_val < 50):
        score += 20.0

    # 4. Régimen (20 pts)
    score += regime_score * 0.20

    # 5. Breakout Strength (10 pts)
    if not np.isnan(upper_band_prev) and not np.isnan(lower_band_prev):
        atr_val = atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else 1.0
        if direction == 1:
            break_dist = close - upper_band_prev
        else:
            break_dist = lower_band_prev - close
        break_strength = min(abs(break_dist) / atr_val, 3.0) / 3.0 * 100.0
        score += break_strength * 0.10

    return score