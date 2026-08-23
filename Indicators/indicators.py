"""
Indicators/indicators.py

Reimplementación de las funciones ta.* de Pine Script utilizadas en
Synapse Trail Pro, replicando su metodología exacta (no simplemente
"lo mismo con otro nombre" de una librería).

IMPORTANTE — diferencias que SÍ importan y que aquí se respetan:

  • ta.ema()  en Pine se "siembra" (seed) con una SMA de `length`
    barras la primera vez que hay datos suficientes, y a partir de
    ahí usa suavizado exponencial recursivo. NO es lo mismo que
    pandas .ewm(span=length, adjust=False) desde la barra 0 (esa
    variante generaría un warm-up distinto en las primeras barras).

  • ta.rma() (Wilder) se siembra igual con una SMA y luego usa
    alpha = 1/length. Es la base de ta.atr(), ta.rsi() y ta.dmi().

  • ta.percentrank(src, length) calcula el percentil del valor
    actual dentro de la ventana de `length` barras (incluyendo la
    actual), como: 100 * (nº de valores anteriores en la ventana
    que son MENORES que el valor actual) / length.

  • R² se calcula igual que en el Pine: correlation(close, bar_index, len)^2.
    Como bar_index es una secuencia estrictamente creciente, la
    correlación de `close` con bar_index en una ventana es
    matemáticamente idéntica a la correlación de `close` con
    cualquier secuencia entera consecutiva 0..len-1 dentro de esa
    misma ventana (la correlación de Pearson es invariante a
    transformaciones afines de una de las dos variables).
"""

from __future__ import annotations
import math
import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════
# Básicos
# ══════════════════════════════════════════════════════════

def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=length).mean()


def _seeded_recursive(series: pd.Series, length: int, alpha: float) -> pd.Series:
    """
    Motor común para ta.ema() y ta.rma(): siembra con SMA(length) en el
    primer punto con datos suficientes, luego recursión exponencial.
    """
    vals = series.astype(float).to_numpy()
    n = len(vals)
    out = np.full(n, np.nan)

    if n == 0 or length <= 0:
        return pd.Series(out, index=series.index)

    seeded = False
    for i in range(n):
        if not seeded:
            if i >= length - 1:
                window = vals[i - length + 1 : i + 1]
                if not np.isnan(window).any():
                    out[i] = window.mean()
                    seeded = True
            continue
        prev = out[i - 1]
        cur = vals[i]
        if np.isnan(cur):
            out[i] = prev
        else:
            out[i] = alpha * cur + (1 - alpha) * prev

    return pd.Series(out, index=series.index)


def ema(series: pd.Series, length: int) -> pd.Series:
    """Equivalente a ta.ema(src, length)."""
    alpha = 2.0 / (length + 1.0)
    return _seeded_recursive(series, length, alpha)


def rma(series: pd.Series, length: int) -> pd.Series:
    """Equivalente a ta.rma(src, length) — suavizado de Wilder."""
    alpha = 1.0 / length
    return _seeded_recursive(series, length, alpha)


# ══════════════════════════════════════════════════════════
# True Range / ATR
# ══════════════════════════════════════════════════════════

def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Primera barra: no hay close previo -> tr = high-low (como ta.tr en Pine)
    tr.iloc[0] = (high.iloc[0] - low.iloc[0])
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Equivalente a ta.atr(length) -> rma(tr, length)."""
    tr = true_range(high, low, close)
    return rma(tr, length)


# ══════════════════════════════════════════════════════════
# RSI (Wilder)
# ══════════════════════════════════════════════════════════

def rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = rma(gain, length)
    avg_loss = rma(loss, length)

    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    # avgLoss == 0 y avgGain > 0 -> RSI = 100
    result = result.where(avg_loss != 0, 100.0)
    # avgLoss == 0 y avgGain == 0 -> RSI = 50 (neutral, evita NaN plano)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    result = result.where(~both_zero, 50.0)
    return result


# ══════════════════════════════════════════════════════════
# DMI / ADX (Wilder)
# ══════════════════════════════════════════════════════════

def dmi(high: pd.Series, low: pd.Series, close: pd.Series, length: int):
    """Equivalente a ta.dmi(length, length) -> (plusDI, minusDI, adx)."""
    up = high.diff()
    down = -low.diff()

    plus_dm = pd.Series(
        np.where((up > down) & (up > 0), up, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0), index=high.index
    )

    tr = true_range(high, low, close)
    tr_rma = rma(tr, length)

    plus_di = 100.0 * rma(plus_dm, length) / tr_rma
    minus_di = 100.0 * rma(minus_dm, length) / tr_rma

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    dx = dx.replace([np.inf, -np.inf], np.nan)
    adx = rma(dx, length)

    return plus_di, minus_di, adx


# ══════════════════════════════════════════════════════════
# Choppiness Index (fórmula exacta usada en el Pine — sección 7)
# ══════════════════════════════════════════════════════════

def choppiness_index(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    ci_high = high.rolling(length, min_periods=length).max()
    ci_low = low.rolling(length, min_periods=length).min()
    tr = true_range(high, low, close)
    ci_atr_sum = tr.rolling(length, min_periods=length).sum()
    ci_range = ci_high - ci_low

    chop_log_n = math.log10(max(length, 2))

    def _row(atr_sum, rng):
        if pd.isna(atr_sum) or pd.isna(rng):
            return np.nan
        if rng <= 0:
            return 100.0
        if atr_sum > 0:
            return 100.0 * math.log10(atr_sum / rng) / chop_log_n
        return 50.0

    chop_raw = pd.Series(
        [_row(a, r) for a, r in zip(ci_atr_sum, ci_range)], index=high.index
    )
    chop_score = (100.0 - chop_raw).clip(lower=0.0, upper=100.0)
    return chop_score


# ══════════════════════════════════════════════════════════
# R² (linealidad) — correlation(close, bar_index, len)^2
# ══════════════════════════════════════════════════════════

def r_squared(close: pd.Series, length: int) -> pd.Series:
    vals = close.astype(float).to_numpy()
    n = len(vals)
    out = np.full(n, np.nan)

    x = np.arange(length, dtype=float)
    x_mean = x.mean()
    x_var = np.sum((x - x_mean) ** 2)

    for i in range(length - 1, n):
        y = vals[i - length + 1 : i + 1]
        if np.isnan(y).any():
            continue
        y_mean = y.mean()
        y_var = np.sum((y - y_mean) ** 2)
        denom = math.sqrt(x_var * y_var)
        if denom == 0:
            corr = 0.0
        else:
            cov = np.sum((x - x_mean) * (y - y_mean))
            corr = cov / denom
        out[i] = corr ** 2

    return pd.Series(out, index=close.index)


# ══════════════════════════════════════════════════════════
# Percent Rank — ta.percentrank(src, length)
# ══════════════════════════════════════════════════════════

def percentrank(series: pd.Series, length: int) -> pd.Series:
    vals = series.astype(float).to_numpy()
    n = len(vals)
    out = np.full(n, np.nan)

    for i in range(n):
        start = max(0, i - length + 1)
        window = vals[start : i + 1]
        if np.isnan(window).any() or len(window) == 0:
            continue
        current = window[-1]
        count_less = np.sum(window[:-1] < current) if len(window) > 1 else 0
        out[i] = 100.0 * count_less / length

    return pd.Series(out, index=series.index)
