import numpy as np
import pandas as pd


def add_atr(
    df: pd.DataFrame,
    period: int = 14,
    prefix: str = "ATR"
) -> pd.DataFrame:
    
    """
    Average True Range (Wilder)
    Devuelve:
        ATR
        ATR_pct
        ATR_slope
    """

    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    atr_pct = (
        atr /
        close.replace(0, np.nan)
    ) * 100

    atr_slope = atr.diff()

    df[prefix] = atr
    df[f"{prefix}_pct"] = atr_pct
    df[f"{prefix}_slope"] = atr_slope

    return df