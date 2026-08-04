"""
Contexto de mercado en el timeframe superior de confirmación (15m por
defecto) — Rodri v1.0.

Extraído de strategy.py sin cambios de lógica.
"""
import pandas as pd

from indicators import add_ema, add_adx
from scoring import score_to_probability


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
