"""
Relative Strength Index (RSI).

Extraído de indicators_rodri.py sin cambios de lógica.
"""
import pandas as pd


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
