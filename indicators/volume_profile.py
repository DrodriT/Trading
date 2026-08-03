"""
Volume Profile aproximado (POC / VAH / VAL).

Extraído de indicators_rodri.py sin cambios de lógica.
"""
import numpy as np
import pandas as pd


def add_volume_profile(df: pd.DataFrame, lookback: int = 100, bins: int = 24):
    """
    Volume Profile aproximado sobre las últimas 'lookback' velas: reparte el
    volumen de cada vela entre los bins de precio que cubre su rango
    high-low, y devuelve:
      - poc: precio del bin con más volumen (Point of Control)
      - vah / val: bordes del Value Area (~70% del volumen, centrado en POC)
    No añade columnas al DataFrame: se calcula bajo demanda sobre la ventana
    más reciente, ya que recalcularlo vela a vela sería carísimo y aquí solo
    lo necesitamos para la última vela cerrada.
    """
    window = df.tail(lookback)
    lo = window["low"].min()
    hi = window["high"].max()
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        return None

    edges = np.linspace(lo, hi, bins + 1)
    vol_per_bin = np.zeros(bins)

    for _, row in window.iterrows():
        row_lo, row_hi, vol = row["low"], row["high"], row["volume"]
        if pd.isna(row_lo) or pd.isna(row_hi) or row_hi <= row_lo or not vol:
            continue
        bin_lo = int(np.searchsorted(edges, row_lo, side="right") - 1)
        bin_hi = int(np.searchsorted(edges, row_hi, side="right") - 1)
        bin_lo = max(0, min(bin_lo, bins - 1))
        bin_hi = max(0, min(bin_hi, bins - 1))
        span = bin_hi - bin_lo + 1
        vol_per_bin[bin_lo:bin_hi + 1] += vol / span

    total_vol = vol_per_bin.sum()
    poc_bin = int(np.argmax(vol_per_bin))
    poc_price = (edges[poc_bin] + edges[poc_bin + 1]) / 2

    if total_vol == 0:
        return {"poc": poc_price, "vah": hi, "val": lo}

    target = total_vol * 0.70
    acc = vol_per_bin[poc_bin]
    lo_bin, hi_bin = poc_bin, poc_bin
    while acc < target and (lo_bin > 0 or hi_bin < bins - 1):
        expand_low = vol_per_bin[lo_bin - 1] if lo_bin > 0 else -1
        expand_high = vol_per_bin[hi_bin + 1] if hi_bin < bins - 1 else -1
        if expand_high >= expand_low:
            hi_bin += 1
            acc += vol_per_bin[hi_bin]
        else:
            lo_bin -= 1
            acc += vol_per_bin[lo_bin]

    return {
        "poc": poc_price,
        "vah": edges[hi_bin + 1],
        "val": edges[lo_bin],
    }
