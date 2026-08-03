"""
Media Móvil Exponencial (EMA).

Extraído de indicators_rodri.py sin cambios de lógica.
"""
import pandas as pd


def add_ema(df: pd.DataFrame, period: int, col_name: str) -> pd.DataFrame:
    """Media móvil exponencial."""
    df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
    return df
