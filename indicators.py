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

    Solo se incluyen los niveles que tengan sentido direccional (ej. para un LONG,
    solo se muestran niveles por DEBAJO del precio actual; para un SHORT, solo
    los que están por ENCIMA). Si un nivel no cumple esa condición, se omite en
    vez de forzarlo, para no dar una entrada inválida.

    Devuelve una lista de dicts: {"label": ..., "price": ..., "basis": ...}
    ordenada desde la más cercana al precio actual hasta la más alejada.
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

    # Entry 1: precio actual
    entries.append({"label": "Entry 1 (precio actual)", "price": price, "basis": "Precio de mercado"})

    if is_long:
        fib_618 = swing_high - diff * 0.618  # soporte de retroceso (golden pocket)
        candidates = [
            ("Entry 2 (retest EMA{})".format(ema_fast), ema_fast_val, f"Retest EMA{ema_fast}"),
            ("Entry 3 (Fibonacci 0.618)", fib_618, "Fibonacci 0.618 del swing reciente"),
            ("Entry 4 (EMA{}, invalidación)".format(ema_slow), ema_slow_val, f"Soporte mayor EMA{ema_slow}"),
        ]
        # Para un LONG, cada nivel siguiente debe estar por debajo del anterior y del precio
        for label, lvl, basis in candidates:
            if lvl < entries[-1]["price"]:
                entries.append({"label": label, "price": lvl, "basis": basis})
    else:
        fib_618 = swing_low + diff * 0.618  # resistencia de retroceso
        candidates = [
            ("Entry 2 (retest EMA{})".format(ema_fast), ema_fast_val, f"Retest EMA{ema_fast}"),
            ("Entry 3 (Fibonacci 0.618)", fib_618, "Fibonacci 0.618 del swing reciente"),
            ("Entry 4 (EMA{}, invalidación)".format(ema_slow), ema_slow_val, f"Resistencia mayor EMA{ema_slow}"),
        ]
        # Para un SHORT, cada nivel siguiente debe estar por encima del anterior y del precio
        for label, lvl, basis in candidates:
            if lvl > entries[-1]["price"]:
                entries.append({"label": label, "price": lvl, "basis": basis})

    return entries


def detect_signals(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                    oversold: int, overbought: int, require_confluence: bool = False,
                    mtf_confirm_bullish=None, mtf_confirm_bearish=None,
                    mtf_label: str = ""):
    """
    Analiza las DOS últimas velas cerradas para detectar la señal:

      - ALCISTA: el Estocástico cruza (%K sobre %D) estando en zona de SOBREVENTA
                 (%K < oversold) Y el precio de cierre está por ENCIMA de la EMA200
                 (en el timeframe principal).
      - BAJISTA: el Estocástico cruza (%K bajo %D) estando en zona de SOBRECOMPRA
                 (%K > overbought) Y el precio de cierre está por DEBAJO de la EMA200
                 (en el timeframe principal).

    La EMA200 actúa como filtro de tendencia; el cruce del Estocástico en la zona
    correspondiente es el disparador. EMA{ema_fast} se calcula igualmente y se
    incluye en el mensaje como referencia, pero no forma parte de la condición.

    Confirmación multi-timeframe (opcional):
        Si mtf_confirm_bullish / mtf_confirm_bearish se pasan (no None), la señal
        ALCISTA solo se valida si mtf_confirm_bullish es True (precio por encima de
        su EMA200 en el timeframe de confirmación, ej. 1h), y la señal BAJISTA solo
        se valida si mtf_confirm_bearish es True (precio por debajo de su EMA200 en
        ese mismo timeframe). Si se pasa None, no se aplica ningún filtro adicional
        (comportamiento igual que antes).

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

    bullish_ok = stoch_cross_up_oversold and price_above_ema200
    bearish_ok = stoch_cross_down_overbought and price_below_ema200

    # Filtro multi-timeframe: si se ha pedido confirmación y no se cumple, se descarta la señal
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
