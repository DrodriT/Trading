"""
Motor de estrategias ENSEMBLE — "Rodri v1.0"

Inspirado en la ficha de parámetros de "Bot Portero V9 Sniper" (activos,
umbrales, gestión de riesgo). Ese documento NO traía la lógica interna de
cada estrategia — solo los nombres y los parámetros globales — así que las
6 estrategias de abajo son una propuesta estándar y razonable para cada
nombre, pensada para poder ajustarse fácilmente en cuanto veas resultados
reales o me pases una definición más concreta de alguna de ellas.

Cada detect_* función mira SOLO la última vela cerrada y devuelve:
    (direction, score_parcial)
donde direction está en {"ALCISTA", "BAJISTA", None} y score_parcial es la
fuerza 0-100 de ESA señal en concreto (no el score final del ensemble).

compute_ensemble_signal() las combina: agrupa por dirección, aplica un
bonus por confluencia (varias estrategias de acuerdo), calcula el score
final 0-100 y deriva de ahí una probabilidad heurística 0-1 (NO es una
probabilidad estadística real: no hay backtest/modelo detrás, ver
score_to_probability).
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

# ── Presets de riesgo (SL en xATR, TP1/TP2/TP3 en múltiplos-R) ──
RISK_PRESETS = {
    "Conservative": {"sl_mult": 2.5, "tp_mults": [1.0, 2.0, 4.0]},
    "Balanced":     {"sl_mult": 1.5, "tp_mults": [1.0, 2.0, 3.0]},
    "Aggressive":   {"sl_mult": 1.0, "tp_mults": [1.5, 2.5, 4.0]},
    "Scalping":     {"sl_mult": 0.8, "tp_mults": [0.8, 1.5, 2.0]},
}


def build_risk_levels(entry_price: float, atr_val: float, signal_type: str, preset: str):
    """
    Calcula SL y TP1/TP2/TP3 según el preset de riesgo elegido.
    SL = entry -/+ (sl_mult × ATR). TP_n = entry +/- (tp_mult_n × distancia_SL).
    """
    cfg = RISK_PRESETS[preset]
    is_long = signal_type == "ALCISTA"
    sl_distance = atr_val * cfg["sl_mult"]

    sl = entry_price - sl_distance if is_long else entry_price + sl_distance
    tps = []
    for i, mult in enumerate(cfg["tp_mults"], start=1):
        tp_price = entry_price + sl_distance * mult if is_long else entry_price - sl_distance * mult
        tps.append({"label": f"TP{i}", "price": tp_price, "rr": mult})

    return {"sl": sl, "sl_distance": sl_distance, "tps": tps}


def compute_base_indicators(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Indicadores compartidos que necesitan varias de las 6 estrategias."""
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

    # Barrido alcista: mecha por debajo del último swing low confirmado,
    # pero cierre de vuelta por encima de ese nivel (vela de rechazo).
    pos_low, swing_low_price = last_confirmed_swing(df, "low", last_pos, cfg.SMC_LOOKBACK)
    if (pos_low is not None and last["low"] < swing_low_price
            and last["close"] > swing_low_price and last["close"] > last["open"]):
        # Confirmación de cambio de estructura (CHoCH simplificado): el
        # cierre supera el swing high previo a ese swing low.
        _, swing_high_price = last_confirmed_swing(df, "high", pos_low, cfg.SMC_LOOKBACK)
        structure_shift = swing_high_price is not None and last["close"] > swing_high_price

        # ===== Score por componentes =====
        # 1) Sweep (0-40)
        wick = swing_low_price - last["low"]
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT  # 40.0

        # 2) Rechazo (0-20)
        rejection = max(last["close"] - swing_low_price, 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT  # 20.0

        # 3) Fuerza del cuerpo (0-15)
        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT  # 15.0

        # 4) CHoCH (0 ó 15)
        choch_score = cfg.SMC_CHOCH_WEIGHT if structure_shift else 0.0

        # 5) Volumen (0-10)
        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT  # 10.0

        strength = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return "ALCISTA", strength

    # Barrido bajista simétrico
    pos_high, swing_high_price = last_confirmed_swing(df, "high", last_pos, cfg.SMC_LOOKBACK)
    if (pos_high is not None and last["high"] > swing_high_price
            and last["close"] < swing_high_price and last["close"] < last["open"]):
        _, swing_low_price2 = last_confirmed_swing(df, "low", pos_high, cfg.SMC_LOOKBACK)
        structure_shift = swing_low_price2 is not None and last["close"] < swing_low_price2

        # ===== Score por componentes =====
        # 1) Sweep (0-40)
        wick = last["high"] - swing_high_price
        sweep_score = min(wick / atr, 1.0) * cfg.SMC_SWEEP_WEIGHT  # 40.0

        # 2) Rechazo (0-20)
        rejection = max(swing_high_price - last["close"], 0.0)
        rejection_score = min(rejection / atr, 1.0) * cfg.SMC_REJECTION_WEIGHT  # 20.0

        # 3) Fuerza del cuerpo (0-15)
        body = abs(last["close"] - last["open"])
        body_score = min(body / atr, 1.0) * cfg.SMC_BODY_WEIGHT  # 15.0

        # 4) CHoCH (0 ó 15)
        choch_score = cfg.SMC_CHOCH_WEIGHT if structure_shift else 0.0

        # 5) Volumen (0-10)
        vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
        volume_score = min(max(vol_ratio - 1.0, 0.0), 1.0) * cfg.SMC_VOLUME_WEIGHT  # 10.0

        strength = min(sweep_score + rejection_score + body_score + choch_score + volume_score, 100.0)

        return "BAJISTA", strength

    return None, 0.0

# ─────────────────────────────────────────────────────────
# 2. LIQUIDITY_GRAB — barrido simple de un extremo reciente
#    (versión más corta/rápida que SMC_REVERSAL, sin exigir CHoCH)
# ─────────────────────────────────────────────────────────
def detect_liquidity_grab(df, cfg):
    if len(df) < cfg.LG_LOOKBACK + 2:
        return None, 0.0
    last = df.iloc[-1]
    atr = last["ATR"]
    if pd.isna(atr) or atr == 0:
        return None, 0.0

    window = df.iloc[-(cfg.LG_LOOKBACK + 1):-1]  # excluye la vela actual
    recent_low = window["low"].min()
    recent_high = window["high"].max()

    if last["low"] < recent_low and last["close"] > recent_low:
        wick = recent_low - last["low"]
        strength = min(wick / atr, 1.5) / 1.5 * 100.0
        return "ALCISTA", strength

    if last["high"] > recent_high and last["close"] < recent_high:
        wick = last["high"] - recent_high
        strength = min(wick / atr, 1.5) / 1.5 * 100.0
        return "BAJISTA", strength

    return None, 0.0


# ─────────────────────────────────────────────────────────
# 3. BREAKOUT — ruptura de rango con confirmación de volumen
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

    if last["close"] > range_high:
        break_dist = last["close"] - range_high
        strength = min(break_dist / atr, 1.5) / 1.5 * 60.0
        strength += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        return "ALCISTA", min(strength, 100.0)

    if last["close"] < range_low:
        break_dist = range_low - last["close"]
        strength = min(break_dist / atr, 1.5) / 1.5 * 60.0
        strength += min(vol_ratio / cfg.BREAKOUT_VOL_THRESHOLD, 1.0) * 40.0
        return "BAJISTA", min(strength, 100.0)

    return None, 0.0


# ─────────────────────────────────────────────────────────
# 4. TREND_PULLBACK — retroceso a favor de una tendencia establecida
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

    # Uptrend: la vela anterior tocó/perforó la EMA rápida (retroceso) y la
    # última vela cierra de nuevo por encima, en verde -> continuación.
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
# 6. VP_MEAN_REVERT — reversión hacia el POC del Volume Profile
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

    if last["close"] < vp["val"]:
        dist = vp["poc"] - last["close"]
        strength = min(dist / atr, 3.0) / 3.0 * 100.0
        return "ALCISTA", strength

    if last["close"] > vp["vah"]:
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
    """
    Ejecuta las 6 estrategias sobre la última vela cerrada.
    Devuelve una lista de dicts {"name", "direction", "score"} — solo las
    que efectivamente dispararon señal.
    """
    hits = []
    for name, fn in DETECTORS.items():
        direction, score = fn(df, cfg)
        if direction:
           weight = cfg.STRATEGY_WEIGHTS.get(name, 1.0)
           hits.append({"name": name,"direction": direction,"score": round(score, 1),"weight": weight,"weighted_score": round(score * weight, 1),})
    return hits


def score_to_probability(score: float, cfg) -> float:
    """
    Transformación heurística score -> probabilidad. IMPORTANTE: no hay
    backtest ni modelo estadístico detrás (a diferencia de un "Prob" real
    calculado sobre histórico); es solo una segunda medida de confianza,
    correlacionada con el score, igual que muestra el V9 en sus mensajes.
    Lineal entre PROB_AT_SCORE_0 y PROB_AT_SCORE_100.
    """
    p0, p100 = cfg.PROB_AT_SCORE_0, cfg.PROB_AT_SCORE_100
    prob = p0 + (score / 100.0) * (p100 - p0)
    return max(0.0, min(1.0, prob))


def compute_ensemble_signal(df, cfg):
    """
    Combina las 6 estrategias:
      1. Agrupa los hits por dirección.
      2. Si ambas direcciones dispararon a la vez, gana la de mayor score
         combinado (no tiene sentido abrir long y short a la vez).
      3. score_final = media de los scores parciales de esa dirección
         + CONFLUENCE_BONUS por cada estrategia extra de acuerdo.
      4. Probabilidad derivada del score (ver score_to_probability).
    Devuelve None si no hay ninguna señal, o un dict con toda la info.
    """
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
            # Sin confluencia: se capa el score, ninguna estrategia sola
            # puede alcanzar el máximo (evita falsa sensación de "Score 100"
            # cuando en realidad solo hay UNA señal detrás, sin confirmación
            # de ninguna otra).
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


def suggest_leverage(df, cfg) -> int:
    """
    Apalancamiento sugerido según volatilidad relativa (ATR% sobre precio):
    más volátil -> leverage más bajo. Interpolación lineal invertida entre
    LEVERAGE_MAX (a ATR% <= LEV_ATR_PCT_LOW) y LEVERAGE_MIN (a ATR% >=
    LEV_ATR_PCT_HIGH).
    """
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
    """
    Para señales "rojas": recalcula los TP para que ningún RR supere
    cap_rr (ej. 1.7R), manteniendo el mismo SL/sl_distance.
    """
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
