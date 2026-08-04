"""
Gestión de riesgo — niveles de SL/TP, SL estructural, apalancamiento
sugerido y cap de TP para señales rojas.

Extraído de strategy.py sin cambios de lógica.
"""
import pandas as pd

from indicators import last_confirmed_swing

RISK_PRESETS = {
    "Conservative": {"sl_mult": 2.5, "tp_mults": [1.0, 2.0, 4.0]},
    "Balanced":     {"sl_mult": 1.5, "tp_mults": [1.0, 2.0, 3.0]},
    "Aggressive":   {"sl_mult": 1.0, "tp_mults": [1.5, 2.5, 4.0]},
    "Scalping":     {"sl_mult": 0.8, "tp_mults": [0.8, 1.5, 2.0]},
}


def compute_structural_sl(df, entry_price: float, atr_val: float, signal_type: str, cfg):
    """
    Busca el último swing confirmado (low para LONG, high para SHORT) y
    devuelve la distancia de SL correspondiente, con colchón de ATR.
    Devuelve None si no hay swing válido o si la distancia excede
    STRUCTURAL_SL_MAX_ATR_MULT * ATR (demasiado ancho -> fallback a ATR).
    """
    last_pos = len(df) - 1
    is_long = signal_type == "ALCISTA"
    buffer = atr_val * cfg.STRUCTURAL_SL_ATR_BUFFER

    if is_long:
        _, swing_price = last_confirmed_swing(df, "low", last_pos, cfg.STRUCTURAL_SL_LOOKBACK)
        if swing_price is None:
            return None
        sl = swing_price - buffer
        distance = entry_price - sl
    else:
        _, swing_price = last_confirmed_swing(df, "high", last_pos, cfg.STRUCTURAL_SL_LOOKBACK)
        if swing_price is None:
            return None
        sl = swing_price + buffer
        distance = sl - entry_price

    if distance <= 0 or distance > atr_val * cfg.STRUCTURAL_SL_MAX_ATR_MULT:
        return None

    return distance


def build_risk_levels(entry_price: float, atr_val: float, signal_type: str, preset: str, df=None, cfg=None):
    """Calcula SL (estructural con fallback a ATR) y TPs por RR según el
    preset de riesgo configurado."""
    preset_cfg = RISK_PRESETS[preset]
    is_long = signal_type == "ALCISTA"

    used_structural_sl = False
    sl_distance = None

    if df is not None and cfg is not None and cfg.STRUCTURAL_SL_ENABLED:
        sl_distance = compute_structural_sl(df, entry_price, atr_val, signal_type, cfg)
        if sl_distance is not None:
            used_structural_sl = True

    if sl_distance is None:
        sl_distance = atr_val * preset_cfg["sl_mult"]

    sl = entry_price - sl_distance if is_long else entry_price + sl_distance

    tps = []
    for i, mult in enumerate(preset_cfg["tp_mults"], start=1):
        tp_price = entry_price + sl_distance * mult if is_long else entry_price - sl_distance * mult
        tps.append({"label": f"TP{i}", "price": tp_price, "rr": mult})

    return {
        "sl": sl,
        "sl_distance": sl_distance,
        "tps": tps,
        "used_structural_sl": used_structural_sl,
    }


def suggest_leverage(df, cfg) -> int:
    """Apalancamiento sugerido según la volatilidad relativa (ATR% sobre
    el precio de cierre), interpolado entre LEVERAGE_MIN y LEVERAGE_MAX."""
    last = df.iloc[-1]
    if not last["close"] or pd.isna(last["ATR"]):
        return cfg.LEVERAGE_MIN
    atr_pct = (last["ATR"] / last["close"]) * 100.0
    lo, hi = cfg.LEV_ATR_PCT_LOW, cfg.LEV_ATR_PCT_HIGH

    if atr_pct <= lo:
        lev = cfg.LEVERAGE_MAX
    elif atr_pct >= hi:
        lev = cfg.LEVERAGE_MIN
    else:
        t = (atr_pct - lo) / (hi - lo)
        lev = cfg.LEVERAGE_MAX - t * (cfg.LEVERAGE_MAX - cfg.LEVERAGE_MIN)

    return int(round(lev))


def cap_tp_at_r(risk: dict, entry_price: float, signal_type: str, cap_rr: float) -> dict:
    """Recorta los TPs de una señal roja a un máximo de cap_rr (RED_TP_CAP_R)."""
    is_long = signal_type == "ALCISTA"
    sl_distance = risk["sl_distance"]
    capped_tps = []
    for tp in risk["tps"]:
        rr = min(tp["rr"], cap_rr)
        price = entry_price + sl_distance * rr if is_long else entry_price - sl_distance * rr
        capped_tps.append({"label": tp["label"], "price": price, "rr": rr})
    new_risk = dict(risk)
    new_risk["tps"] = capped_tps
    return new_risk
