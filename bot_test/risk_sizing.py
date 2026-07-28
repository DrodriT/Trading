"""
Cálculo de apalancamiento automático por riesgo + tamaño de posición.

Fórmula (ver live_config.py para el detalle):
    risk_amount   = equity × RISK_PCT_PER_TRADE
    margin        = equity × MARGIN_PCT_PER_TRADE
    notional      = risk_amount / sl_distance_pct
    leverage_raw  = notional / margin
    leverage      = clamp(round(leverage_raw), MIN_LEVERAGE, MAX_LEVERAGE)

Importante: el leverage se REDONDEA y se ACOTA al cap de seguridad.
Una vez fijado el leverage final, el notional/tamaño de posición se
recalculan a partir de ESE leverage (no del leverage_raw teórico), para
que el margen usado sea siempre exactamente MARGIN_PCT_PER_TRADE del
equity — lo que puede variar ligeramente el riesgo real respecto al
RISK_PCT_PER_TRADE nominal (menos, nunca más, gracias al cap).
"""
import math

import live_config as config


def compute_position_plan(equity: float, entry_price: float, sl_price: float,
                           contract_size: float = 1.0, amount_precision: int = None):
    """
    Devuelve un dict con: sl_distance_pct, risk_amount, margin, leverage,
    leverage_raw, notional, contracts.

    `contract_size` y `amount_precision` permiten ajustar el tamaño final
    a lo que exija el mercado (se aplican fuera, en exchange_client, con
    exchange.amount_to_precision — aquí solo se calcula el número "ideal").
    """
    if entry_price <= 0 or equity <= 0:
        raise ValueError("equity y entry_price deben ser > 0")

    sl_distance_pct = abs(entry_price - sl_price) / entry_price
    if sl_distance_pct <= 0:
        raise ValueError("sl_price no puede ser igual a entry_price")

    risk_amount = equity * config.RISK_PCT_PER_TRADE
    margin = equity * config.MARGIN_PCT_PER_TRADE

    notional_raw = risk_amount / sl_distance_pct
    leverage_raw = notional_raw / margin if margin > 0 else config.MIN_LEVERAGE

    leverage = max(config.MIN_LEVERAGE, min(config.MAX_LEVERAGE, round(leverage_raw)))

    # Con el leverage YA fijado (redondeado/acotado), el notional real es
    # margen × leverage — puede ser menor que el "ideal" si el cap actuó.
    notional = margin * leverage
    contracts = notional / entry_price / contract_size

    return {
        "sl_distance_pct": sl_distance_pct,
        "risk_amount": risk_amount,
        "margin": margin,
        "leverage_raw": round(leverage_raw, 2),
        "leverage": leverage,
        "leverage_capped": leverage != round(leverage_raw),
        "notional": notional,
        "contracts": contracts,
    }


def split_tp_quantities(total_contracts: float, tp_splits=None):
    """
    Reparte `total_contracts` en N tramos según tp_splits (fracciones que
    NO tienen por qué sumar 1.0 — el último tramo se lleva el resto).
    Ej.: tp_splits=[0.33, 0.33] con total=1.0 -> [0.33, 0.33, 0.34].
    Devuelve una lista de tamaños, uno por TP (len = len(tp_splits) + 1).
    """
    if tp_splits is None:
        tp_splits = config.TP_SPLIT
    quantities = []
    remaining = total_contracts
    for frac in tp_splits:
        qty = total_contracts * frac
        quantities.append(qty)
        remaining -= qty
    quantities.append(max(remaining, 0.0))  # último TP = lo que sobre
    return quantities
