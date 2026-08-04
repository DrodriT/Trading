"""
Indicadores base compartidos — Rodri v1.0

Tras las Fases 3-5 de la refactorización, este archivo solo conserva
compute_base_indicators: no encaja como responsabilidad única en
ensemble.py, scoring.py, market_state.py ni risk.py, así que se queda
aquí hasta que se decida su ubicación definitiva (posiblemente como
fachada dentro de indicators/).

El resto de lo que vivía en este archivo se movió sin cambios de lógica a:
  - strategies/   (las 6 estrategias, con contrato rico)
  - ensemble.py    (run_all_strategies, compute_ensemble_signal)
  - scoring.py      (score_to_probability)
  - market_state.py  (compute_htf_context, apply_htf_confirmation)
  - risk.py          (RISK_PRESETS, compute_structural_sl, build_risk_levels,
                       suggest_leverage, cap_tp_at_r)
"""
import pandas as pd

from indicators import add_ema, add_atr, add_adx, add_rsi, add_volume_ratio, add_swings


def compute_base_indicators(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Calcula, una sola vez por símbolo, los indicadores base que
    comparten las 6 estrategias (ATR, EMA rápida/lenta, ADX, RSI, ratio
    de volumen, swings)."""
    df = add_atr(df, cfg.ATR_LEN, col_name="ATR")
    df = add_ema(df, cfg.EMA_FAST, col_name=f"EMA{cfg.EMA_FAST}")
    df = add_ema(df, cfg.EMA_SLOW, col_name=f"EMA{cfg.EMA_SLOW}")
    df = add_adx(df, cfg.ADX_PERIOD)
    df = add_rsi(df, cfg.RSI_PERIOD)
    df = add_volume_ratio(df, cfg.VOLUME_MA_PERIOD)
    df = add_swings(df, cfg.SWING_LEFT, cfg.SWING_RIGHT)
    return df
