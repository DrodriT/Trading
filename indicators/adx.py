"""
ADX v2 Mejorado
Average Directional Index con +DI y -DI

Mejoras:
- Wilder smoothing consistente
- DM filtering
- Protección divisiones
- Fuerza direccional
- Pendiente ADX
"""
import pandas as pd
import numpy as np

def add_adx(
    df: pd.DataFrame,
    period: int = 14,
    prefix: str = "ADX"
    ) -> pd.DataFrame:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # ==================================================
    # Movimiento direccional
    # ==================================================
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where(
        (up_move > down_move) &
        (up_move > 0),
        up_move,
        0.0
    )
    minus_dm = np.where(
        (down_move > up_move) &
        (down_move > 0),
        down_move,
        0.0
    )
    plus_dm = pd.Series(
        plus_dm,
        index=df.index
    )
    minus_dm = pd.Series(
        minus_dm,
        index=df.index
    )

    # ==================================================
    # True Range
    # ==================================================
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ],
        axis=1
    ).max(axis=1)

    # ==================================================
    # Wilder smoothing
    # ==================================================
    atr = tr.ewm(
        alpha=1/period,
        adjust=False
    ).mean()
    plus_dm_smooth = plus_dm.ewm(
        alpha=1/period,
        adjust=False
    ).mean()
    minus_dm_smooth = minus_dm.ewm(
        alpha=1/period,
        adjust=False
    ).mean()

    # ==================================================
    # DI
    # ==================================================
    plus_di = (
        100 *
        plus_dm_smooth /
        atr.replace(0,np.nan)
    )
    minus_di = (
        100 *
        minus_dm_smooth /
        atr.replace(0,np.nan)
    )

    # ==================================================
    # DX
    # ==================================================
    di_sum = plus_di + minus_di
    dx = (
        100 *
        (plus_di - minus_di).abs() /
        di_sum.replace(0,np.nan)
    )

    # ==================================================
    # ADX
    # ==================================================
    adx = dx.ewm(
        alpha=1/period,
        adjust=False
    ).mean()

    # ==================================================
    # Datos adicionales
    # ==================================================
    di_diff = plus_di - minus_di
    adx_slope = adx.diff()

    # ==================================================
    # Salida
    # ==================================================
    df[prefix] = adx
    df[f"{prefix}_plusDI"] = plus_di
    df[f"{prefix}_minusDI"] = minus_di
    df[f"{prefix}_DI_diff"] = di_diff
    df[f"{prefix}_slope"] = adx_slope

    return df