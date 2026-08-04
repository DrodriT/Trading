"""
===============================================================================
Average Directional Index (ADX)
===============================================================================

Descripción:
    Calcula el Average Directional Index (ADX), indicador desarrollado por
    J. Welles Wilder para medir la fuerza de una tendencia.

    El ADX no indica la dirección del mercado, únicamente la intensidad
    de la tendencia. La dirección se obtiene mediante +DI y -DI.

Salida:
    ADX             -> Fuerza de la tendencia.
    ADX_plusDI      -> Fuerza compradora.
    ADX_minusDI     -> Fuerza vendedora.
    ADX_DI_diff     -> Diferencia entre +DI y -DI.
    ADX_slope       -> Pendiente del ADX.

===============================================================================
"""

import numpy as np
import pandas as pd


def add_adx(
    df: pd.DataFrame,
    period: int = 14,
    prefix: str = "ADX"
) -> pd.DataFrame:
    """
    Añade las columnas del ADX al DataFrame.
    """

    # =====================================================================
    # Movimiento Direccional (Directional Movement)
    # =====================================================================

    # Movimiento ascendente entre velas
    up_move = df["high"].diff()

    # Movimiento descendente entre velas
    down_move = -df["low"].diff()

    # Movimiento direccional positivo
    plus_dm = np.where(
        (up_move > down_move) &
        (up_move > 0),
        up_move,
        0.0,
    )

    # Movimiento direccional negativo
    minus_dm = np.where(
        (down_move > up_move) &
        (down_move > 0),
        down_move,
        0.0,
    )

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

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
    # Suavizado de Wilder
    # =====================================================================

    # Average True Range
    atr = tr.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    # Movimiento direccional positivo suavizado
    plus_dm_smooth = plus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    # Movimiento direccional negativo suavizado
    minus_dm_smooth = minus_dm.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    # =====================================================================
    # Directional Indicators (+DI / -DI)
    # =====================================================================

    # Indicador direccional positivo
    plus_di = (
        100
        * plus_dm_smooth
        / atr.replace(0, np.nan)
    )

    # Indicador direccional negativo
    minus_di = (
        100
        * minus_dm_smooth
        / atr.replace(0, np.nan)
    )

    # =====================================================================
    # Directional Index (DX)
    # =====================================================================

    # Suma de ambos indicadores direccionales
    di_sum = plus_di + minus_di

    # Fuerza instantánea de la tendencia
    dx = (
        100
        * (plus_di - minus_di).abs()
        / di_sum.replace(0, np.nan)
    )

    # =====================================================================
    # Average Directional Index (ADX)
    # =====================================================================

    # Fuerza suavizada de la tendencia
    adx = dx.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    # =====================================================================
    # Variables auxiliares
    # =====================================================================

    # Dominancia entre compradores y vendedores
    di_diff = plus_di - minus_di

    # Cambio de la fuerza de la tendencia
    adx_slope = adx.diff()

    # =====================================================================
    # Salida
    # =====================================================================

    df[prefix] = adx
    df[f"{prefix}_plusDI"] = plus_di
    df[f"{prefix}_minusDI"] = minus_di
    df[f"{prefix}_DI_diff"] = di_diff
    df[f"{prefix}_slope"] = adx_slope

    return df