"""
Lógica ESPECÍFICA de la estrategia — inspirada en "Synapse Trail Pro"
(WillyAlgoTrader), adaptada a un bot de alertas de Telegram (sin las partes
puramente visuales: líneas, colores, dashboard en el gráfico).

=== RESUMEN DE LA ESTRATEGIA ===

1. SEÑAL (Synapse Trail): banda de tendencia tipo SuperTrend
   trail_center = EMA(close, TRAIL_LEN)
   banda = trail_center ± ATR(ATR_LEN) × multiplicador
   Con "ratchet": la banda solo se aprieta a favor de la posición (nunca
   se afloja) hasta que la dirección cambia.
   Señal = cambio de dirección (flip) de la banda.

2. MARKET REGIME (0-100): ADX(40%) + Choppiness Index invertido(35%) + R²(25%)
   Trending si >=60, Choppy si <35.

3. QUALITY SCORE (0-100) una vez detectada la señal:
   HTF bias 30 | Volumen 20 | RSI 20 | Régimen 20 | Fuerza de ruptura 10
   Grado: A (>=75), B (>=55), C (resto)

4. GESTIÓN DE POSICIÓN VIVA: el bot recuerda la posición abierta (entry,
   SL, TP1/TP2/TP3) entre ejecuciones. Al tocar TP1 activa break-even
   (SL -> entrada). Se cierra al tocar el SL o el TP3. Un flip (señal
   contraria mientras hay posición abierta) cierra la posición actual y
   abre la nueva.

5. PRESETS DE RIESGO: SL en múltiplos de ATR, TP1/TP2/TP3 en múltiplos-R
   (relativos a la distancia del SL).
"""
import pandas as pd
import numpy as np

from indicators import (
    add_ema, add_atr, add_adx, add_rsi, add_volume_ratio,
    add_choppiness_index, add_r_squared
)

# ── Presets de riesgo (SL en xATR, TP1/TP2/TP3 en múltiplos-R) ──
RISK_PRESETS = {
    "Conservative": {"sl_mult": 2.5, "tp_mults": [1.0, 2.0, 4.0]},
    "Balanced":     {"sl_mult": 1.5, "tp_mults": [1.0, 2.0, 3.0]},
    "Aggressive":   {"sl_mult": 1.0, "tp_mults": [1.5, 2.5, 4.0]},
    "Scalping":     {"sl_mult": 0.8, "tp_mults": [0.8, 1.5, 2.0]},
}

GRADE_A_THRESHOLD = 75
GRADE_B_THRESHOLD = 55
REGIME_TRENDING = 60
REGIME_CHOPPY = 35


def compute_indicators(df: pd.DataFrame, atr_len: int, trail_len: int,
                        adx_period: int, chop_period: int, regime_len: int,
                        rsi_period: int, volume_ma_period: int) -> pd.DataFrame:
    """Calcula todos los indicadores base necesarios para esta estrategia."""
    df = add_atr(df, atr_len, col_name="ATR")
    df = add_ema(df, trail_len, col_name="TRAIL_EMA")
    df = add_adx(df, adx_period)
    df = add_choppiness_index(df, chop_period)
    df = add_r_squared(df, regime_len)
    df = add_rsi(df, rsi_period)
    df = add_volume_ratio(df, volume_ma_period)
    return df


def compute_synapse_trail(df: pd.DataFrame, atr_len: int, trail_len: int,
                           base_mult: float = 1.618, use_adaptive_mult: bool = False,
                           use_ratchet: bool = True) -> pd.DataFrame:
    """
    Calcula la banda de tendencia (Synapse Trail) bar a bar, con ratchet
    opcional. Necesita recorrer el DataFrame en orden porque cada banda
    depende de su propio valor en la vela anterior (igual que un SuperTrend).

    Añade columnas: TRAIL_upper, TRAIL_lower, TRAIL_dir (1/-1/0), TRAIL_line.
    """
    if use_adaptive_mult:
        vol_rank = df["ATR"].rank(pct=True) * 100
    else:
        vol_rank = pd.Series(50.0, index=df.index)

    mult_adjust = vol_rank.apply(lambda r: 0.8 if r < 30 else (1.25 if r > 70 else 1.0))
    effective_mult = base_mult * mult_adjust

    raw_upper = df["TRAIL_EMA"] + df["ATR"] * effective_mult
    raw_lower = df["TRAIL_EMA"] - df["ATR"] * effective_mult

    dirs, uppers, lowers = [], [], []
    dir_state = 0
    upper_state, lower_state = np.nan, np.nan

    closes = df["close"].values
    ru = raw_upper.values
    rl = raw_lower.values

    for i in range(len(df)):
        prev_upper = upper_state
        prev_lower = lower_state
        prev_dir = dir_state

        if not np.isnan(prev_upper) and closes[i] > prev_upper:
            dir_state = 1
        elif not np.isnan(prev_lower) and closes[i] < prev_lower:
            dir_state = -1
        # si no se cumple ninguna, dir_state se mantiene igual (persiste)

        flipped = dir_state != prev_dir

        if use_ratchet:
            if dir_state == 1:
                lower_state = rl[i] if flipped else (max(rl[i], prev_lower) if not np.isnan(prev_lower) else rl[i])
                upper_state = ru[i]
            elif dir_state == -1:
                upper_state = ru[i] if flipped else (min(ru[i], prev_upper) if not np.isnan(prev_upper) else ru[i])
                lower_state = rl[i]
            else:
                upper_state = ru[i]
                lower_state = rl[i]
        else:
            upper_state = ru[i]
            lower_state = rl[i]

        dirs.append(dir_state)
        uppers.append(upper_state)
        lowers.append(lower_state)

    df["TRAIL_dir"] = dirs
    df["TRAIL_upper"] = uppers
    df["TRAIL_lower"] = lowers
    df["TRAIL_line"] = [
        lowers[i] if dirs[i] == 1 else (uppers[i] if dirs[i] == -1 else np.nan)
        for i in range(len(df))
    ]
    return df


def compute_regime(df: pd.DataFrame) -> pd.DataFrame:
    """
    Market Regime Score (0-100): ADX(40%) + Choppiness invertido(35%) + R²(25%).
    Añade columnas: REGIME_score, REGIME_is_trending, REGIME_is_choppy.
    Requiere que ya se hayan calculado ADX, CHOP y R2 (ver compute_indicators).
    """
    adx_score = (df["ADX"] / 50 * 100).clip(upper=100)
    chop_score = (100 - df["CHOP"]).clip(lower=0, upper=100)
    r2_score = (df["R2"] * 100).clip(lower=0, upper=100)

    regime_score = adx_score * 0.40 + chop_score * 0.35 + r2_score * 0.25
    df["REGIME_score"] = regime_score
    df["REGIME_is_trending"] = regime_score >= REGIME_TRENDING
    df["REGIME_is_choppy"] = regime_score < REGIME_CHOPPY
    return df


def detect_raw_signal(df: pd.DataFrame):
    """
    Detecta si en la ÚLTIMA vela cerrada se ha producido un flip de dirección
    del Synapse Trail. Devuelve "ALCISTA", "BAJISTA" o None.
    """
    if len(df) < 3:
        return None
    prev_dir = df.iloc[-2]["TRAIL_dir"]
    last_dir = df.iloc[-1]["TRAIL_dir"]
    if last_dir == 1 and prev_dir == -1:
        return "ALCISTA"
    if last_dir == -1 and prev_dir == 1:
        return "BAJISTA"
    return None


def compute_quality_score(df: pd.DataFrame, signal_type: str,
                           htf_bull, htf_bear, use_htf_filter: bool,
                           use_volume_filter: bool, volume_threshold: float,
                           has_volume: bool):
    """
    Quality Score (0-100):
      HTF bias        30 pts (alineado) / 15 (plano o filtro apagado) / 0 (en contra)
      Volumen         20 pts (si hay confirmación, o si el filtro está apagado / sin datos)
      RSI momentum    20 pts (RSI>50 para LONG, <50 para SHORT)
      Régimen         20 pts (REGIME_score × 0.20)
      Fuerza ruptura  10 pts (cuánto ha perforado el precio la banda, hasta 3×ATR)

    Devuelve (score, grade, breakdown).
    """
    last = df.iloc[-1]
    is_long = signal_type == "ALCISTA"
    breakdown = {}

    # --- HTF bias ---
    htf_data_valid = use_htf_filter and htf_bull is not None and htf_bear is not None
    htf_matches = htf_data_valid and ((is_long and htf_bull) or (not is_long and htf_bear))
    htf_against = htf_data_valid and ((is_long and htf_bear) or (not is_long and htf_bull))
    htf_pts = 30.0 if htf_matches else (0.0 if htf_against else 15.0)
    breakdown["HTF"] = round(htf_pts, 1)

    # --- Volumen ---
    if (not use_volume_filter) or (not has_volume):
        vol_pts = 20.0
    else:
        vol_confirm = last["VOL_RATIO"] > volume_threshold if pd.notna(last["VOL_RATIO"]) else False
        vol_pts = 20.0 if vol_confirm else 0.0
    breakdown["Volumen"] = round(vol_pts, 1)

    # --- RSI ---
    rsi_ok = (last["RSI"] > 50) if is_long else (last["RSI"] < 50)
    rsi_pts = 20.0 if rsi_ok else 0.0
    breakdown["RSI"] = round(rsi_pts, 1)

    # --- Régimen ---
    regime_pts = last["REGIME_score"] * 0.20
    breakdown["Régimen"] = round(regime_pts, 1)

    # --- Fuerza de ruptura ---
    prev = df.iloc[-2]
    if is_long:
        break_dist = last["close"] - prev["TRAIL_upper"]
    else:
        break_dist = prev["TRAIL_lower"] - last["close"]
    atr_val = last["ATR"]
    break_strength = min(abs(break_dist) / atr_val, 3.0) / 3.0 * 100.0 if atr_val else 0.0
    break_pts = break_strength * 0.10
    breakdown["Ruptura"] = round(break_pts, 1)

    score = round(min(100, sum(breakdown.values())))
    grade = "A" if score >= GRADE_A_THRESHOLD else ("B" if score >= GRADE_B_THRESHOLD else "C")

    return score, grade, breakdown


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


def build_limit_entries(df: pd.DataFrame, ema_fast_col: str, ema_slow: int,
                         signal_type: str, swing_lookback: int = 50):
    """
    Calcula de 2 a 4 niveles de entrada escalonados (limit orders), igual
    que en versiones anteriores del bot: precio actual, retest EMA rápida,
    Fibonacci 0.618 del swing reciente, y EMA lenta (invalidación).
    """
    last = df.iloc[-1]
    price = last["close"]
    ema_fast_val = last[ema_fast_col] if ema_fast_col in df.columns else None
    ema_slow_val = last[f"EMA{ema_slow}"] if f"EMA{ema_slow}" in df.columns else None

    window = df.tail(swing_lookback)
    swing_high = window["high"].max()
    swing_low = window["low"].min()
    diff = swing_high - swing_low

    entries = [{"price": price, "basis": "precio actual"}]
    is_long = signal_type == "ALCISTA"

    candidates = []
    if ema_fast_val is not None:
        candidates.append((ema_fast_val, "retest EMA rápida"))
    fib = (swing_high - diff * 0.618) if is_long else (swing_low + diff * 0.618)
    candidates.append((fib, "Fibonacci 0.618 del swing reciente"))
    if ema_slow_val is not None:
        candidates.append((ema_slow_val, f"EMA{ema_slow}, invalidación"))

    for lvl, basis in candidates:
        if is_long and lvl < entries[-1]["price"]:
            entries.append({"price": lvl, "basis": basis})
        elif not is_long and lvl > entries[-1]["price"]:
            entries.append({"price": lvl, "basis": basis})

    for i, e in enumerate(entries, start=1):
        e["label"] = f"Entry {i} ({e['basis']})"

    return entries
