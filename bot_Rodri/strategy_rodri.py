"""
Motor de estrategias ENSEMBLE — "Rodri v1.0"
"""
import pandas as pd

from indicators_rodri import (
    add_ema, add_atr, add_adx, add_rsi, add_volume_ratio,
    add_swings, add_volume_profile, rsi_divergence, last_confirmed_swing,
)

STRATEGY_NAMES = [
    "SMC_REVERSAL", "BREAKOUT", "TREND_PULLBACK",
    "RSI_DIVERGENCE", "VP_MEAN_REVERT", "LIQUIDITY_GRAB",
]

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
# 1. SMC_REVERSAL — barrido de liquidez + cambio de estructura
# ─────────────────────────────────────────────────────────
def detect_smc_reversal(df, cfg):
    last = df.iloc[-1]
    last_pos = len(df) - 1
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None, 0.0

    pos_low, swing_low_price = last_confirmed_swing(df, "low", last_pos, cfg.SMC_LOOKBACK)
    if (pos_low is not None and last["low"] < swing_low_price
            and last["close"] > swing_low_price and last["close"] > last["open"]):
        _, swing_high_price = last_confirmed_swing(df, "high", pos_low, cfg.SMC_LOOKBACK)
        structure_shift = swing_high_price is not None and last["close"] > swing_high_price
        if not structure_shift:
            return None, 0.0
        
        wick = swing_low_price - last["low"]
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT

        rejection = max(last["close"] - swing_low_price, 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT

        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT

        choch_score = cfg.SMC_CHOCH_WEIGHT 

        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT

        strength = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return "ALCISTA", strength

    pos_high, swing_high_price = last_confirmed_swing(df, "high", last_pos, cfg.SMC_LOOKBACK)
    if (pos_high is not None and last["high"] > swing_high_price
            and last["close"] < swing_high_price and last["close"] < last["open"]):
        _, swing_low_price2 = last_confirmed_swing(df, "low", pos_high, cfg.SMC_LOOKBACK)
        structure_shift = swing_low_price2 is not None and last["close"] < swing_low_price2
        if not structure_shift:
            return None, 0.0
        
        wick = last["high"] - swing_high_price
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT

        rejection = max(swing_high_price - last["close"], 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT

        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT

        choch_score = cfg.SMC_CHOCH_WEIGHT 

        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT

        strength = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return "BAJISTA", strength

    return None, 0.0

# ─────────────────────────────────────────────────────────
# 2. LIQUIDITY_GRAB
# ─────────────────────────────────────────────────────────
def detect_liquidity_grab(df, cfg):
    if len(df) < cfg.LG_LOOKBACK + 2:
        return None, 0.0
    last = df.iloc[-1]
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None, 0.0

    window = df.iloc[-(cfg.LG_LOOKBACK + 1):-1]
    recent_low = window["low"].min()
    recent_high = window["high"].max()

    if last["low"] < recent_low and last["close"] > recent_low:
        wick = recent_low - last["low"]
        if wick / atr < cfg.LG_MIN_WICK_ATR_RATIO:
            return None, 0.0
        strength = min(wick / atr, 1.5) / 1.5 * 100.0
        return "ALCISTA", strength

    if last["high"] > recent_high and last["close"] < recent_high:
        wick = last["high"] - recent_high
        if wick / atr < cfg.LG_MIN_WICK_ATR_RATIO:
            return None, 0.0
        strength = min(wick / atr, 1.5) / 1.5 * 100.0
        return "BAJISTA", strength

    return None, 0.0

# ─────────────────────────────────────────────────────────
# 3. BREAKOUT
# ─────────────────────────────────────────────────────────
def detect_breakout(df, cfg):
    if len(df) < cfg.BREAKOUT_LOOKBACK + 2:
        return None, 0.0
    last = df.iloc[-1]
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None, 0.0

    window = df.iloc[-(cfg.BREAKOUT_LOOKBACK + 1):-1]
    range_high = window["high"].max()
    range_low = window["low"].min()
    vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0

    if last["close"] > range_high and vol_ratio >= cfg.BREAKOUT_VOL_THRESHOLD:
        break_dist = last["close"] - range_high
        strength = min(break_dist / atr, 1.5) / 1.5 * 60.0
        strength += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        return "ALCISTA", min(strength, 100.0)

    if last["close"] < range_low and vol_ratio >= cfg.BREAKOUT_VOL_THRESHOLD:
        break_dist = range_low - last["close"]
        strength = min(break_dist / atr, 1.5) / 1.5 * 60.0
        strength += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        return "BAJISTA", min(strength, 100.0)

    return None, 0.0


# ─────────────────────────────────────────────────────────
# 4. TREND_PULLBACK
# ─────────────────────────────────────────────────────────
def detect_trend_pullback(df, cfg):
    if len(df) < 3:
        return None, 0.0
    last = df.iloc[-1]
    prev = df.iloc[-2]
    ema_fast_col = f"EMA{cfg.EMA_FAST}"
    ema_slow_col = f"EMA{cfg.EMA_SLOW}"
    adx = last["ADX"]
    if pd.isna(adx) or pd.isna(last[ema_fast_col]) or pd.isna(prev[ema_fast_col]):
        return None, 0.0

    is_uptrend = last[ema_fast_col] > last[ema_slow_col] and adx >= cfg.TREND_ADX_MIN
    is_downtrend = last[ema_fast_col] < last[ema_slow_col] and adx >= cfg.TREND_ADX_MIN

    if (is_uptrend and prev["low"] <= prev[ema_fast_col]
            and last["close"] > last[ema_fast_col] and last["close"] > last["open"]):
        strength = min(adx / 50.0, 1.0) * 100.0
        return "ALCISTA", strength

    if (is_downtrend and prev["high"] >= prev[ema_fast_col]
            and last["close"] < last[ema_fast_col] and last["close"] < last["open"]):
        strength = min(adx / 50.0, 1.0) * 100.0
        return "BAJISTA", strength

    return None, 0.0


# ─────────────────────────────────────────────────────────
# 5. RSI_DIVERGENCE
# ─────────────────────────────────────────────────────────
def detect_rsi_divergence(df, cfg):
    return rsi_divergence(df, "RSI", cfg.DIVERGENCE_LOOKBACK)


# ─────────────────────────────────────────────────────────
# 6. VP_MEAN_REVERT
# ─────────────────────────────────────────────────────────
def detect_vp_mean_revert(df, cfg):
    if len(df) < cfg.VP_LOOKBACK:
        return None, 0.0
    last = df.iloc[-1]
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None, 0.0

    vp = add_volume_profile(df, cfg.VP_LOOKBACK, cfg.VP_BINS)
    if vp is None:
        return None, 0.0

    if last["close"] < vp["val"] and last["close"] > last["open"]:
        dist = vp["poc"] - last["close"]
        strength = min(dist / atr, 3.0) / 3.0 * 100.0
        return "ALCISTA", strength

    if last["close"] > vp["vah"] and last["close"] < last["open"]:
        dist = last["close"] - vp["poc"]
        strength = min(dist / atr, 3.0) / 3.0 * 100.0
        return "BAJISTA", strength

    return None, 0.0


DETECTORS = {
    "SMC_REVERSAL": detect_smc_reversal,
    "BREAKOUT": detect_breakout,
    "TREND_PULLBACK": detect_trend_pullback,
    "RSI_DIVERGENCE": detect_rsi_divergence,
    "VP_MEAN_REVERT": detect_vp_mean_revert,
    "LIQUIDITY_GRAB": detect_liquidity_grab,
}


def run_all_strategies(df, cfg):
    hits = []
    for name, fn in DETECTORS.items():
        direction, score = fn(df, cfg)
        if direction:
            weight = cfg.STRATEGY_WEIGHTS.get(name, 1.0)
            hits.append({
                "name": name, "direction": direction, "score": round(score, 1),
                "weight": weight, "weighted_score": round(score * weight, 1),
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
