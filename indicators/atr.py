"""
===============================================================================
Average True Range (ATR)
===============================================================================

Descripción:
    Calcula el Average True Range (ATR), indicador desarrollado por
    J. Welles Wilder para medir la volatilidad del mercado.

    El ATR no indica dirección del precio, únicamente la magnitud
    del movimiento.

Salida:
    ATR            -> Volatilidad absoluta.
    ATR_pct        -> ATR expresado como porcentaje del precio.
    ATR_slope      -> Pendiente del ATR (cambio de volatilidad).

===============================================================================
"""

import numpy as np
import pandas as pd


def add_atr(
    df: pd.DataFrame,
    period: int = 14,
    prefix: str = "ATR"
) -> pd.DataFrame:
    """
    Añade las columnas del ATR al DataFrame.
    """

    # =====================================================================
    # True Range (TR)
    # =====================================================================

    # Cierre de la vela anterior
    prev_close = df["close"].shift(1)

    # True Range
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # =====================================================================
    # Average True Range (Wilder)
    # =====================================================================

    atr = tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    # =====================================================================
    # Variables auxiliares
    # =====================================================================

    # ATR en porcentaje respecto al precio
    atr_pct = (
        atr /
        df["close"].replace(0, np.nan)
    ) * 100

    # Pendiente del ATR
    atr_slope = atr.diff()

    # =====================================================================
    # Salida
    # =====================================================================

    df[prefix] = atr
    df[f"{prefix}_pct"] = atr_pct
    df[f"{prefix}_slope"] = atr_slope

    return df