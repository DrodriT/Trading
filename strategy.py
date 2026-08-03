"""
Motor de estrategias ENSEMBLE — "Rodri v1.0"
"""
import pandas as pd

from indicators import (
    add_ema, add_atr, add_adx, add_rsi, add_volume_ratio,
    add_swings, last_confirmed_swing,
)
from strategies import DETECTORS, STRATEGY_NAMES

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


def compute_base_indicators(df: pd.DataFrame, cfg) -> pd.DataFrame:
    df = add_atr(df, cfg.ATR_LEN, col_name="ATR")
    df = add_ema(df, cfg.EMA_FAST, col_name=f"EMA{cfg.EMA_FAST}")
    df = add_ema(df, cfg.EMA_SLOW, col_name=f"EMA{cfg.EMA_SLOW}")
    df = add_adx(df, cfg.ADX_PERIOD)
    df = add_rsi(df, cfg.RSI_PERIOD)
    df = add_volume_ratio(df, cfg.VOLUME_MA_PERIOD)
    df = add_swings(df, cfg.SWING_LEFT, cfg.SWING_RIGHT)
    return df


# ─────────────────────────────────────────────────────────
# Las 6 estrategias (SMC_REVERSAL, BREAKOUT, TREND_PULLBACK,
# RSI_DIVERGENCE, VP_MEAN_REVERT, LIQUIDITY_GRAB) viven ahora en su
# propio paquete strategies/, cada una en su archivo, con contrato rico
# {direction, score, confidence, reason, metadata} | None. DETECTORS se
# importa arriba desde strategies.
# ─────────────────────────────────────────────────────────


def run_all_strategies(df, cfg):
    """
    Ejecuta las 6 estrategias sobre el DataFrame ya indicadorizado y
    devuelve la lista de "hits" (una por cada estrategia que disparó),
    con el peso y el score ponderado ya aplicados para el ensemble.

    Cada detector devuelve {direction, score, confidence, reason,
    metadata} o None (contrato rico). Aquí solo se usa "direction" y
    "score" para el cálculo del ensemble (igual que antes); confidence,
    reason y metadata se conservan en el hit para inspección/depuración
    (p. ej. desde tools/analyze.py) pero no alteran el score ni el
    resultado del ensemble.
    """
    hits = []
    for name, fn in DETECTORS.items():
        result = fn(df, cfg)
        if result is None:
            continue
        direction = result["direction"]
        score = result["score"]
        weight = cfg.STRATEGY_WEIGHTS.get(name, 1.0)
        hits.append({
            "name": name, "direction": direction, "score": round(score, 1),
            "weight": weight, "weighted_score": round(score * weight, 1),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
            "metadata": result.get("metadata"),
        })
    return hits




def score_to_probability(score: float, cfg) -> float:
    p0, p100 = cfg.PROB_AT_SCORE_0, cfg.PROB_AT_SCORE_100
    prob = p0 + (score / 100.0) * (p100 - p0)
    return max(0.0, min(1.0, prob))


def compute_ensemble_signal(df, cfg):
    hits = run_all_strategies(df, cfg)
    if not hits:
        return None

    by_dir = {"ALCISTA": [], "BAJISTA": []}
    for h in hits:
        by_dir[h["direction"]].append(h)

    def dir_total(hs):
        if not hs:
            return -1.0
        if len(hs) == 1:
            return min(hs[0]["score"], cfg.MAX_SOLO_SCORE)
        total_weight = sum(h["weight"] for h in hs)
        avg = (sum(h["weighted_score"] for h in hs) / total_weight)
        bonus = cfg.CONFLUENCE_BONUS * (len(hs) - 1)
        return min(100.0, avg + bonus)

    total_long = dir_total(by_dir["ALCISTA"])
    total_short = dir_total(by_dir["BAJISTA"])

    if total_long < 0 and total_short < 0:
        return None

    if total_long >= total_short:
        winning_dir, winning_hits, score = "ALCISTA", by_dir["ALCISTA"], total_long
    else:
        winning_dir, winning_hits, score = "BAJISTA", by_dir["BAJISTA"], total_short

    score = round(score)
    prob = round(score_to_probability(score, cfg), 2)

    return {
        "direction": winning_dir,
        "score": score,
        "prob": prob,
        "strategies": [h["name"] for h in winning_hits],
        "confluence": len(winning_hits),
    }


# ─────────────────────────────────────────────────────────
# Confirmación de timeframe superior (15m por defecto)
# ─────────────────────────────────────────────────────────
def compute_htf_context(df_htf: pd.DataFrame, cfg) -> dict:
    """
    Calcula el contexto de tendencia en el timeframe superior de
    confirmación (por defecto 15m): EMA rápida/lenta + ADX. No repite las
    6 estrategias en 15m, solo determina si hay una tendencia clara y en
    qué dirección, para poder confirmar o penalizar las señales que ya
    detectó el ensemble de 5m.

    Devuelve {"trend": "ALCISTA"/"BAJISTA"/"NEUTRAL", "adx": float}.
    """
    df_htf = add_ema(df_htf, cfg.CONFIRM_EMA_FAST, col_name="HTF_EMA_FAST")
    df_htf = add_ema(df_htf, cfg.CONFIRM_EMA_SLOW, col_name="HTF_EMA_SLOW")
    df_htf = add_adx(df_htf, cfg.CONFIRM_ADX_PERIOD, prefix="HTF_ADX")

    last = df_htf.iloc[-1]
    ema_fast, ema_slow, adx = last["HTF_EMA_FAST"], last["HTF_EMA_SLOW"], last["HTF_ADX"]

    if pd.isna(ema_fast) or pd.isna(ema_slow) or pd.isna(adx):
        return {"trend": "NEUTRAL", "adx": 0.0}

    if ema_fast > ema_slow and adx >= cfg.CONFIRM_ADX_MIN:
        trend = "ALCISTA"
    elif ema_fast < ema_slow and adx >= cfg.CONFIRM_ADX_MIN:
        trend = "BAJISTA"
    else:
        trend = "NEUTRAL"

    return {"trend": trend, "adx": round(float(adx), 1)}


def apply_htf_confirmation(signal: dict, htf: dict, cfg) -> dict:
    """
    Ajusta (o bloquea) la señal de 5m según el contexto de 15m:
      - 15m NEUTRAL o a favor de la señal -> no se toca nada.
      - 15m claramente EN CONTRA:
          - ADX 15m >= CONFIRM_BLOCK_ADX_MIN -> tendencia demasiado fuerte
            en contra, se BLOQUEA la señal entera (devuelve None).
          - ADX 15m >= CONFIRM_ADX_MIN (pero por debajo del umbral de
            bloqueo) -> tendencia moderada en contra, se PENALIZA el score
            (CONFIRM_SCORE_PENALTY puntos) y se recalcula la probabilidad.
    Añade "htf_trend"/"htf_adx" a la señal para poder mostrarlos en el
    mensaje de Telegram.
    """
    if signal is None or not cfg.CONFIRM_ENABLED:
        return signal

    signal["htf_trend"] = htf["trend"]
    signal["htf_adx"] = htf["adx"]
    signal["htf_penalized"] = False

    is_against = (
        (signal["direction"] == "ALCISTA" and htf["trend"] == "BAJISTA") or
        (signal["direction"] == "BAJISTA" and htf["trend"] == "ALCISTA")
    )
    if not is_against:
        return signal

    if htf["adx"] >= cfg.CONFIRM_BLOCK_ADX_MIN:
        return None  # tendencia de 15m demasiado fuerte en contra -> se descarta

    penalized_score = max(0, signal["score"] - cfg.CONFIRM_SCORE_PENALTY)
    signal["score"] = penalized_score
    signal["prob"] = round(score_to_probability(penalized_score, cfg), 2)
    signal["htf_penalized"] = True
    return signal


def suggest_leverage(df, cfg) -> int:
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
