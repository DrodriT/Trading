"""
VP_MEAN_REVERT — reversión hacia el POC del Volume Profile reciente,
desde fuera del Value Area (VAL/VAH).

Extraída de strategy.py sin cambios de cálculo.
"""
import pandas as pd

from core.utils import is_atr_valid

from indicators import add_volume_profile


def detect_vp_mean_revert(df, cfg):
    """Rechazo desde fuera del Value Area (VAL/VAH) hacia el POC del
    Volume Profile reciente (VP_LOOKBACK velas, VP_BINS bins)."""
    if len(df) < cfg.VP_LOOKBACK:
        return None
    last = df.iloc[-1]
    atr = last["ATR"]
    if not is_atr_valid(atr):
        return None

    vp = add_volume_profile(df, cfg.VP_LOOKBACK, cfg.VP_BINS)
    if vp is None:
        return None

    if last["close"] < vp["val"] and last["close"] > last["open"]:
        dist = vp["poc"] - last["close"]
        score = min(dist / atr, 3.0) / 3.0 * 100.0
        return {
            "direction": "ALCISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Rechazo alcista por debajo del Value Area, hacia el POC del Volume Profile",
            "metadata": {"poc": vp["poc"], "vah": vp["vah"], "val": vp["val"], "dist_to_poc": dist},
        }

    if last["close"] > vp["vah"] and last["close"] < last["open"]:
        dist = last["close"] - vp["poc"]
        score = min(dist / atr, 3.0) / 3.0 * 100.0
        return {
            "direction": "BAJISTA",
            "score": score,
            "confidence": score / 100.0,
            "reason": "Rechazo bajista por encima del Value Area, hacia el POC del Volume Profile",
            "metadata": {"poc": vp["poc"], "vah": vp["vah"], "val": vp["val"], "dist_to_poc": dist},
        }

    return None
