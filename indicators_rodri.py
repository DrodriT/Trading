"""
Indicadores para la estrategia Rodri v1.0 — archivo AUTOCONTENIDO, sin
dependencias de ningún otro archivo del proyecto.

Incluye tanto los indicadores "clásicos" (EMA, ATR, RSI, ADX, ratio de
volumen) como los nuevos que necesita el ensemble: swings/fractales, un
Volume Profile aproximado (POC/VAH/VAL) y detección de divergencias RSI.

Todo trabaja con índices POSICIONALES (0..n-1), asumiendo que el DataFrame
viene con un índice por defecto (como el que devuelve fetch_ohlcv en bot_rodri.py).
"""
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────
# Indicadores base (EMA, ATR, RSI, ADX, ratio de volumen)
# ─────────────────────────────────────────────────────────

def add_ema(df: pd.DataFrame, period: int, col_name: str) -> pd.DataFrame:
    """Media móvil exponencial."""
    df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def add_atr(df: pd.DataFrame, period: int = 14, col_name: str = "ATR") -> pd.DataFrame:
    """Average True Range: mide la volatilidad reciente en unidades de precio."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df[col_name] = tr.rolling(window=period).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col_name: str = "RSI") -> pd.DataFrame:
    """Relative Strength Index clásico (suavizado de Wilder)."""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    df[col_name] = 100 - (100 / (1 + rs))
    df.loc[avg_loss == 0, col_name] = 100
    return df


def add_adx(df: pd.DataFrame, period: int = 14, prefix: str = "ADX") -> pd.DataFrame:
    """Average Directional Index (con +DI y -DI), suavizado a la Wilder."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr_wilder = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_wilder
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_wilder

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    df[prefix] = adx
    df[f"{prefix}_plusDI"] = plus_di
    df[f"{prefix}_minusDI"] = minus_di
    return df


def add_volume_ratio(df: pd.DataFrame, period: int = 20, col_name: str = "VOL_RATIO",
                      ma_col_name: str = "VOL_MA") -> pd.DataFrame:
    """Ratio entre el volumen actual y la media de las 'period' velas anteriores."""
    avg_volume = df["volume"].shift(1).rolling(window=period).mean()
    df[ma_col_name] = avg_volume
    df[col_name] = df["volume"] / avg_volume
    return df


# ─────────────────────────────────────────────────────────
# Indicadores nuevos para el ensemble Rodri
# ─────────────────────────────────────────────────────────


def add_swings(df: pd.DataFrame, left: int = 3, right: int = 3,
                high_col: str = "swing_high", low_col: str = "swing_low") -> pd.DataFrame:
    """
    Marca fractales de swing: una vela es swing high si su high es el máximo
    entre 'left' velas antes y 'right' velas después (y análogo para swing
    low). Las últimas 'right' velas nunca pueden confirmarse todavía (haría
    falta ver velas futuras), así que quedan en False — es el comportamiento
    correcto: un swing solo cuenta cuando ya está confirmado por el precio
    posterior, igual que en Smart Money Concepts o en cualquier indicador de
    fractales.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    is_high = np.zeros(n, dtype=bool)
    is_low = np.zeros(n, dtype=bool)

    for i in range(left, n - right):
        window_h = highs[i - left:i + right + 1]
        window_l = lows[i - left:i + right + 1]
        if highs[i] == window_h.max():
            is_high[i] = True
        if lows[i] == window_l.min():
            is_low[i] = True

    df[high_col] = is_high
    df[low_col] = is_low
    return df


def last_confirmed_swing(df: pd.DataFrame, kind: str, before_pos: int, lookback: int = 200):
    """
    Devuelve (posición, precio) del último swing confirmado de tipo 'high' o
    'low' ANTES de la posición 'before_pos' (sin incluirla), buscando hacia
    atrás hasta 'lookback' velas. Devuelve (None, None) si no encuentra nada.
    """
    col = "swing_high" if kind == "high" else "swing_low"
    price_col = "high" if kind == "high" else "low"
    start = max(0, before_pos - lookback)
    if before_pos <= start:
        return None, None
    sub = df.iloc[start:before_pos]
    matches_pos = np.where(sub[col].values)[0]
    if len(matches_pos) == 0:
        return None, None
    pos = start + matches_pos[-1]
    return pos, df.iloc[pos][price_col]


def add_volume_profile(df: pd.DataFrame, lookback: int = 100, bins: int = 24):
    """
    Volume Profile aproximado sobre las últimas 'lookback' velas: reparte el
    volumen de cada vela entre los bins de precio que cubre su rango
    high-low, y devuelve:
      - poc: precio del bin con más volumen (Point of Control)
      - vah / val: bordes del Value Area (~70% del volumen, centrado en POC)
    No añade columnas al DataFrame: se calcula bajo demanda sobre la ventana
    más reciente, ya que recalcularlo vela a vela sería carísimo y aquí solo
    lo necesitamos para la última vela cerrada.
    """
    window = df.tail(lookback)
    lo = window["low"].min()
    hi = window["high"].max()
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        return None

    edges = np.linspace(lo, hi, bins + 1)
    vol_per_bin = np.zeros(bins)

    for _, row in window.iterrows():
        row_lo, row_hi, vol = row["low"], row["high"], row["volume"]
        if pd.isna(row_lo) or pd.isna(row_hi) or row_hi <= row_lo or not vol:
            continue
        bin_lo = int(np.searchsorted(edges, row_lo, side="right") - 1)
        bin_hi = int(np.searchsorted(edges, row_hi, side="right") - 1)
        bin_lo = max(0, min(bin_lo, bins - 1))
        bin_hi = max(0, min(bin_hi, bins - 1))
        span = bin_hi - bin_lo + 1
        vol_per_bin[bin_lo:bin_hi + 1] += vol / span

    total_vol = vol_per_bin.sum()
    poc_bin = int(np.argmax(vol_per_bin))
    poc_price = (edges[poc_bin] + edges[poc_bin + 1]) / 2

    if total_vol == 0:
        return {"poc": poc_price, "vah": hi, "val": lo}

    target = total_vol * 0.70
    acc = vol_per_bin[poc_bin]
    lo_bin, hi_bin = poc_bin, poc_bin
    while acc < target and (lo_bin > 0 or hi_bin < bins - 1):
        expand_low = vol_per_bin[lo_bin - 1] if lo_bin > 0 else -1
        expand_high = vol_per_bin[hi_bin + 1] if hi_bin < bins - 1 else -1
        if expand_high >= expand_low:
            hi_bin += 1
            acc += vol_per_bin[hi_bin]
        else:
            lo_bin -= 1
            acc += vol_per_bin[lo_bin]

    return {
        "poc": poc_price,
        "vah": edges[hi_bin + 1],
        "val": edges[lo_bin],
    }


def rsi_divergence(df: pd.DataFrame, rsi_col: str = "RSI", lookback: int = 30):
    """
    Divergencia RSI clásica entre los dos últimos swings confirmados del
    mismo tipo dentro de 'lookback' velas:
      - Alcista: precio hace un low más bajo, pero el RSI hace un low más
        alto (el impulso bajista se está debilitando) -> señal LONG.
      - Bajista: precio hace un high más alto, pero el RSI hace un high más
        bajo -> señal SHORT.
    Requiere que el DataFrame ya tenga columnas swing_high/swing_low (ver
    add_swings) y la columna de RSI ya calculada.
    Devuelve ("ALCISTA"/"BAJISTA"/None, fuerza 0-100).
    """
    last_pos = len(df) - 1

    pos1, low1 = last_confirmed_swing(df, "low", last_pos, lookback)
    if pos1 is not None:
        pos0, low0 = last_confirmed_swing(df, "low", pos1, lookback)
        if pos0 is not None and low1 < low0:
            rsi1 = df.iloc[pos1][rsi_col]
            rsi0 = df.iloc[pos0][rsi_col]
            if pd.notna(rsi1) and pd.notna(rsi0) and rsi1 > rsi0:
                strength = min((rsi1 - rsi0) / 20.0, 1.0) * 100.0
                return "ALCISTA", strength

    pos1, high1 = last_confirmed_swing(df, "high", last_pos, lookback)
    if pos1 is not None:
        pos0, high0 = last_confirmed_swing(df, "high", pos1, lookback)
        if pos0 is not None and high1 > high0:
            rsi1 = df.iloc[pos1][rsi_col]
            rsi0 = df.iloc[pos0][rsi_col]
            if pd.notna(rsi1) and pd.notna(rsi0) and rsi1 < rsi0:
                strength = min((rsi0 - rsi1) / 20.0, 1.0) * 100.0
                return "BAJISTA", strength

    return None, 0.0
