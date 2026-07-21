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


def get_trend_vs_ema200(df: pd.DataFrame, ema_slow: int):
    """
    Dado un DataFrame OHLCV ya con EMA{ema_slow} calculada, devuelve
    (is_above, is_below) según la última vela cerrada. Se usa para el
    timeframe de confirmación (ej. 1h) independientemente del timeframe
    principal de la señal.
    """
    if len(df) < ema_slow + 2:
        return None, None
    last = df.iloc[-1]
    slow_col = f"EMA{ema_slow}"
    return last["close"] > last[slow_col], last["close"] < last[slow_col]


def build_limit_entries(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                         signal_type: str, swing_lookback: int = 50):
    """
    Calcula de 2 a 4 niveles de entrada escalonados (limit orders), cada uno
    basado en un criterio técnico distinto, en vez de un solo precio de mercado:

      Entry 1 -> precio actual (entrada inmediata)
      Entry 2 -> retest de EMA{ema_fast} (pullback menor)
      Entry 3 -> nivel Fibonacci 0.618 del swing reciente (soporte/resistencia fuerte)
      Entry 4 -> EMA{ema_slow} (zona de invalidación / soporte-resistencia mayor)

    Solo se incluyen los niveles que tengan sentido direccional. Se renumeran
    de forma correlativa (sin huecos) según lo que realmente se muestra.
    """
    last = df.iloc[-1]
    price = last["close"]
    ema_fast_val = last[f"EMA{ema_fast}"]
    ema_slow_val = last[f"EMA{ema_slow}"]

    window = df.tail(swing_lookback)
    swing_high = window["high"].max()
    swing_low = window["low"].min()
    diff = swing_high - swing_low

    entries = []
    is_long = signal_type == "ALCISTA"

    entries.append({"price": price, "basis": "precio actual"})

    if is_long:
        fib_618 = swing_high - diff * 0.618
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast}"),
            (fib_618, "Fibonacci 0.618 del swing reciente"),
            (ema_slow_val, f"soporte mayor EMA{ema_slow}, invalidación"),
        ]
        for lvl, basis in candidates:
            if lvl < entries[-1]["price"]:
                entries.append({"price": lvl, "basis": basis})
    else:
        fib_618 = swing_low + diff * 0.618
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast}"),
            (fib_618, "Fibonacci 0.618 del swing reciente"),
            (ema_slow_val, f"resistencia mayor EMA{ema_slow}, invalidación"),
        ]
        for lvl, basis in candidates:
            if lvl > entries[-1]["price"]:
                entries.append({"price": lvl, "basis": basis})

    for i, e in enumerate(entries, start=1):
        e["label"] = f"Entry {i} ({e['basis']})"

    return entries


def detect_signals(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                    oversold: int, overbought: int, require_confluence: bool = False,
                    mtf_confirm_bullish=None, mtf_confirm_bearish=None,
                    mtf_label: str = ""):
    """
    ALCISTA: Estocástico cruza al alza en sobreventa (%K < oversold) Y precio > EMA200
    BAJISTA: Estocástico cruza a la baja en sobrecompra (%K > overbought) Y precio < EMA200

    Con confirmación multi-timeframe opcional (mtf_confirm_bullish/bearish).
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

    bullish_ok = stoch_cross_up_oversold and price_above_ema200
    bearish_ok = stoch_cross_down_overbought and price_below_ema200

    if bullish_ok and mtf_confirm_bullish is not None and not mtf_confirm_bullish:
        bullish_ok = False
    if bearish_ok and mtf_confirm_bearish is not None and not mtf_confirm_bearish:
        bearish_ok = False

    if bullish_ok:
        msg = (f"Estocástico cruza al alza en sobreventa (<{oversold}) "
               f"y precio por ENCIMA de EMA{ema_slow}")
        if mtf_confirm_bullish is not None:
            msg += f" | confirmado: precio también por ENCIMA de EMA{ema_slow} en {mtf_label}"
        signals.append(("ALCISTA", msg))

    if bearish_ok:
        msg = (f"Estocástico cruza a la baja en sobrecompra (>{overbought}) "
               f"y precio por DEBAJO de EMA{ema_slow}")
        if mtf_confirm_bearish is not None:
            msg += f" | confirmado: precio también por DEBAJO de EMA{ema_slow} en {mtf_label}"
        signals.append(("BAJISTA", msg))

    return signals
