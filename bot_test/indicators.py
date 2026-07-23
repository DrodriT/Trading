"""
Caja de herramientas de análisis técnico — funciones GENÉRICAS y reutilizables.

Este archivo NO decide nada sobre cuándo comprar o vender: solo calcula
indicadores sobre un DataFrame OHLCV (columnas: open, high, low, close, volume).
La lógica de qué combinación de indicadores dispara una señal vive en
strategy.py, no aquí.

Indicadores disponibles: EMA, Estocástico, ATR, RSI, MACD.
"""
import pandas as pd


def add_ema(df: pd.DataFrame, period: int, col_name: str) -> pd.DataFrame:
    """Media móvil exponencial."""
    df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def add_stochastic(df: pd.DataFrame, k_period: int, smooth: int, d_period: int) -> pd.DataFrame:
    """Oscilador Estocástico (%K suavizado y %D)."""
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()

    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%K"] = raw_k.rolling(window=smooth).mean()   # estocástico "lento"
    df["%D"] = df["%K"].rolling(window=d_period).mean()
    return df


def add_atr(df: pd.DataFrame, period: int = 14, col_name: str = "ATR") -> pd.DataFrame:
    """
    Average True Range: mide la volatilidad reciente en unidades de precio.
    Útil como base para SL/TP proporcionales a cómo de "movida" está la
    cripto ahora mismo, en vez de un % fijo igual para todas.
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df[col_name] = tr.rolling(window=period).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col_name: str = "RSI") -> pd.DataFrame:
    """
    Relative Strength Index clásico (suavizado de Wilder).
    Valores 0-100; tradicionalmente se considera sobrecompra >70 y
    sobreventa <30, aunque estos umbrales no están aplicados aquí —
    esta función solo calcula el valor, no decide nada.
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Suavizado de Wilder (equivalente a una EMA con alpha=1/period)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss
    df[col_name] = 100 - (100 / (1 + rs))
    df.loc[avg_loss == 0, col_name] = 100  # evitar división por cero cuando no hay pérdidas
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9,
             prefix: str = "MACD") -> pd.DataFrame:
    """
    MACD (Moving Average Convergence Divergence).
    Añade tres columnas: {prefix} (línea MACD), {prefix}_signal (línea de señal)
    y {prefix}_hist (histograma = MACD - señal).
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    df[prefix] = ema_fast - ema_slow
    df[f"{prefix}_signal"] = df[prefix].ewm(span=signal, adjust=False).mean()
    df[f"{prefix}_hist"] = df[prefix] - df[f"{prefix}_signal"]
    return df


def add_adx(df: pd.DataFrame, period: int = 14, prefix: str = "ADX") -> pd.DataFrame:
    """
    Average Directional Index (con +DI y -DI), suavizado a la Wilder.
    Añade tres columnas: {prefix} (fuerza de la tendencia, 0-100, sin dirección),
    {prefix}_plusDI y {prefix}_minusDI (para saber si la dirección dominante
    es alcista o bajista).
    """
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


def add_ssl_channel(df: pd.DataFrame, period: int = 10, prefix: str = "SSL") -> pd.DataFrame:
    """
    SSL Channel: dos líneas (SSL Up / SSL Down) construidas a partir de medias
    móviles simples de máximos y mínimos, que "cambian de lado" según si el
    precio ha roto por encima de la media de máximos o por debajo de la media
    de mínimos. Se usa como filtro/confirmación de tendencia: cuando SSL Up
    está por ENCIMA de SSL Down, el estado es alcista; cuando está por DEBAJO,
    bajista. El cruce entre ambas líneas es la señal clásica de este indicador.
    """
    sma_high = df["high"].rolling(window=period).mean()
    sma_low = df["low"].rolling(window=period).mean()

    hlv = pd.Series(index=df.index, dtype="float64")
    state = 0.0
    values = []
    for close, sh, sl in zip(df["close"], sma_high, sma_low):
        if pd.notna(sh) and close > sh:
            state = 1.0
        elif pd.notna(sl) and close < sl:
            state = -1.0
        values.append(state)
    hlv = pd.Series(values, index=df.index)

    df[f"{prefix}_up"] = sma_low.where(hlv < 0, sma_high)
    df[f"{prefix}_down"] = sma_high.where(hlv < 0, sma_low)
    return df


def add_volume_ratio(df: pd.DataFrame, period: int = 20, col_name: str = "VOL_RATIO",
                      ma_col_name: str = "VOL_MA") -> pd.DataFrame:
    """
    Ratio entre el volumen de la vela actual y la media de las 'period' velas
    anteriores (sin incluir la actual), y expone también esa media como columna
    propia (VOL_MA). >1 en el ratio significa más participación de lo habitual;
    se usa como confirmación de que el movimiento tiene "fuerza" real detrás,
    independientemente de la dirección.
    """
    avg_volume = df["volume"].shift(1).rolling(window=period).mean()
    df[ma_col_name] = avg_volume
    df[col_name] = df["volume"] / avg_volume
    return df


def get_trend_vs_ma(df: pd.DataFrame, ma_col: str, min_periods: int = 0):
    """
    Dado un DataFrame ya con una media móvil calculada en ma_col, devuelve
    (is_above, is_below) según la última vela cerrada. Genérico: sirve para
    cualquier media (EMA200, EMA50, SMA...), no solo EMA200.
    """
    if len(df) < min_periods + 2:
        return None, None
    last = df.iloc[-1]
    return last["close"] > last[ma_col], last["close"] < last[ma_col]


def get_trend_vs_ema200(df: pd.DataFrame, ema_slow: int):
    """Atajo de compatibilidad: get_trend_vs_ma() aplicado a la columna EMA{ema_slow}."""
    return get_trend_vs_ma(df, f"EMA{ema_slow}", min_periods=ema_slow)
