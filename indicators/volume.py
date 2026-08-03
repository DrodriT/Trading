"""
Ratio de volumen respecto a su media móvil.

Extraído de indicators_rodri.py sin cambios de lógica.
"""
import pandas as pd


def add_volume_ratio(df: pd.DataFrame, period: int = 20, col_name: str = "VOL_RATIO",
                      ma_col_name: str = "VOL_MA") -> pd.DataFrame:
    """Ratio entre el volumen actual y la media de las 'period' velas anteriores."""
    avg_volume = df["volume"].shift(1).rolling(window=period).mean()
    df[ma_col_name] = avg_volume
    df[col_name] = df["volume"] / avg_volume
    return df
