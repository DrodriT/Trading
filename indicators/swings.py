"""
Fractales de swing (swing high / swing low) y búsqueda del último swing
confirmado.

Extraído de indicators_rodri.py sin cambios de lógica. Ambas funciones
viven juntas porque last_confirmed_swing opera directamente sobre las
columnas swing_high/swing_low que genera add_swings.
"""
import numpy as np
import pandas as pd


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
