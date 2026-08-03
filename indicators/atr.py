"""
Average True Range (ATR).

Extraído de indicators_rodri.py sin cambios de lógica.
"""
import pandas as pd


def add_atr(df: pd.DataFrame, period: int = 14, col_name: str = "ATR") -> pd.DataFrame:
    """Average True Range: mide la volatilidad reciente en unidades de precio."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df[col_name] = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return df
