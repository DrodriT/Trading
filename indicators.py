"""
Cálculo de EMA13, EMA200 y Estocástico (%K, %D) sobre un DataFrame OHLCV.
"""
import pandas as pd


def add_ema(df: pd.DataFrame, period: int, col_name: str) -> pd.DataFrame:
    df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def add_stochastic(df: pd.DataFrame, k_period: int, smooth: int, d_period: int) -> pd.DataFrame:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()

    raw_k = 100 * (df["close"] - low_min) / (high_max - low_min)
    df["%K"] = raw_k.rolling(window=smooth).mean()   # estocástico "lento"
    df["%D"] = df["%K"].rolling(window=d_period).mean()
    return df


def compute_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                        k_period: int, smooth: int, d_period: int) -> pd.DataFrame:
    df = add_ema(df, ema_fast, f"EMA{ema_fast}")
    df = add_ema(df, ema_slow, f"EMA{ema_slow}")
    df = add_stochastic(df, k_period, smooth, d_period)
    return df


def detect_signals(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                    oversold: int, overbought: int, require_confluence: bool = False):
    """
    Analiza las DOS últimas velas cerradas para detectar la señal:

      - ALCISTA: el Estocástico cruza (%K sobre %D) estando en zona de SOBREVENTA
                 (%K < oversold) Y el precio de cierre está por ENCIMA de la EMA200.
      - BAJISTA: el Estocástico cruza (%K bajo %D) estando en zona de SOBRECOMPRA
                 (%K > overbought) Y el precio de cierre está por DEBAJO de la EMA200.

    La EMA200 actúa como filtro de tendencia; el cruce del Estocástico en la zona
    correspondiente es el disparador. EMA{ema_fast} se calcula igualmente y se
    incluye en el mensaje como referencia, pero no forma parte de la condición.

    Devuelve una lista de tuplas (tipo, mensaje) con las señales activas en la
    última vela cerrada.
    """
    if len(df) < max(ema_slow, 30) + 2:
        return []

    prev, last = df.iloc[-2], df.iloc[-1]
    slow_col = f"EMA{ema_slow}"

    price_above_ema200 = last["close"] > last[slow_col]
    price_below_ema200 = last["close"] < last[slow_col]

    stoch_cross_up_oversold = (prev["%K"] <= prev["%D"] and last["%K"] > last["%D"]
                                and last["%K"] < oversold)
    stoch_cross_down_overbought = (prev["%K"] >= prev["%D"] and last["%K"] < last["%D"]
                                    and last["%K"] > overbought)

    signals = []

    if stoch_cross_up_oversold and price_above_ema200:
        signals.append(("ALCISTA",
                         f"Estocástico cruza al alza en sobreventa (<{oversold}) "
                         f"y precio por ENCIMA de EMA{ema_slow}"))

    if stoch_cross_down_overbought and price_below_ema200:
        signals.append(("BAJISTA",
                         f"Estocástico cruza a la baja en sobrecompra (>{overbought}) "
                         f"y precio por DEBAJO de EMA{ema_slow}"))

    return signals
