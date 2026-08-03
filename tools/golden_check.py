"""
Caso dorado de verificación — Rodri v1.0

Este script NO depende de red ni del exchange: construye datos OHLCV
sintéticos y 100% deterministas (misma salida en cada ejecución), y corre
el pipeline completo tal como lo hace bot_rodri.py en check_symbol():

    compute_base_indicators
      -> run_all_strategies (registra CADA detector, no solo el ganador)
      -> compute_ensemble_signal
      -> compute_htf_context + apply_htf_confirmation (15m sintético)
      -> build_risk_levels (+ variante "roja" con cap_tp_at_r)
      -> suggest_leverage

El resultado completo se vuelca a tools/golden_output.json.

Objetivo: tener una foto de referencia del comportamiento actual para
poder comparar "antes vs. después" en cada fase de la refactorización, y
detectar de inmediato cualquier cambio de comportamiento no intencionado.

Uso (desde la raíz del proyecto, con tools/ como subcarpeta):
    python tools/golden_check.py
"""
import json
import math
import os
import sys

import numpy as np
import pandas as pd

# Permite ejecutar "python tools/golden_check.py" desde la raíz del
# proyecto sin tener que instalar nada como paquete: añade la carpeta
# padre (donde viven config.py / strategy.py / indicators_rodri.py)
# al principio del sys.path.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config  # noqa: E402
from strategy import (  # noqa: E402
    compute_base_indicators, run_all_strategies, compute_ensemble_signal,
    compute_htf_context, apply_htf_confirmation, build_risk_levels,
    cap_tp_at_r, suggest_leverage,
)

OUTPUT_PATH = os.path.join(_THIS_DIR, "golden_output.json")


# ─────────────────────────────────────────────────────────
# Generación de datos sintéticos deterministas
# ─────────────────────────────────────────────────────────

def build_breakout_scenario_5m(n: int = 200) -> pd.DataFrame:
    """
    Construye n velas de 5m: un rango estrecho y estable seguido de una
    última vela que rompe claramente al alza con volumen alto, pensado
    para disparar BREAKOUT de forma determinista (y, de paso, dejar ver
    qué hacen el resto de detectores sobre el mismo dataset).

    Todo se genera con fórmulas fijas (sin np.random), así que el
    resultado es idéntico en cada ejecución.
    """
    idx = np.arange(n)
    # Rango: oscilación pequeña y acotada alrededor de 100.
    base_close = 100.0 + 0.3 * np.sin(idx / 3.0)
    open_ = np.roll(base_close, 1)
    open_[0] = base_close[0]
    close = base_close
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    volume = np.full(n, 1000.0)

    # Última vela: ruptura alcista clara + pico de volumen.
    range_high_est = high[:-1][-30:].max()  # aprox. lo que verá BREAKOUT_LOOKBACK
    open_[-1] = close[-2]
    close[-1] = range_high_est + 1.5
    high[-1] = close[-1] + 0.1
    low[-1] = open_[-1] - 0.1
    volume[-1] = 2500.0

    timestamps = 1_700_000_000_000 + idx * 5 * 60 * 1000
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume,
    })
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


def build_uptrend_scenario_htf(n: int = 100) -> pd.DataFrame:
    """
    Construye n velas (15m) con tendencia alcista limpia y consistente,
    pensadas para que compute_htf_context detecte "ALCISTA" con ADX por
    encima de CONFIRM_ADX_MIN de forma determinista.
    """
    idx = np.arange(n)
    close = 100.0 + idx * 0.3  # subida lineal constante
    open_ = close - 0.2
    high = close + 0.15
    low = open_ - 0.15
    volume = np.full(n, 1000.0)

    timestamps = 1_700_000_000_000 + idx * 15 * 60 * 1000
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": open_, "high": high, "low": low, "close": close,
        "volume": volume,
    })
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


# ─────────────────────────────────────────────────────────
# Utilidades de serialización
# ─────────────────────────────────────────────────────────

def _round_floats(obj, ndigits=6):
    """Redondea recursivamente floats para que el JSON sea estable y
    legible (evita ruido de precisión binaria entre ejecuciones/entornos)."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return None
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


# ─────────────────────────────────────────────────────────
# Ejecución del pipeline completo
# ─────────────────────────────────────────────────────────

def main():
    result = {"config_snapshot": {
        "STRATEGY_LABEL": config.STRATEGY_LABEL,
        "RISK_PRESET": config.RISK_PRESET,
        "MIN_SCORE": config.MIN_SCORE,
        "MIN_PROB": config.MIN_PROB,
        "CONFIRM_ENABLED": config.CONFIRM_ENABLED,
        "STRUCTURAL_SL_ENABLED": config.STRUCTURAL_SL_ENABLED,
    }}

    # 1. Indicadores base (5m) — idéntico a compute_base_indicators en check_symbol()
    df = build_breakout_scenario_5m()
    df = compute_base_indicators(df, config)
    last = df.iloc[-1]
    result["last_candle_5m"] = {
        "close": last["close"], "ATR": last["ATR"],
        f"EMA{config.EMA_FAST}": last[f"EMA{config.EMA_FAST}"],
        f"EMA{config.EMA_SLOW}": last[f"EMA{config.EMA_SLOW}"],
        "ADX": last["ADX"], "RSI": last["RSI"], "VOL_RATIO": last["VOL_RATIO"],
    }

    # 2. Cada detector por separado (no solo el ganador del ensemble)
    hits = run_all_strategies(df, config)
    result["strategy_hits"] = hits

    # 3. Señal ensemble (agregación + score + probabilidad)
    signal = compute_ensemble_signal(df, config)
    result["ensemble_signal_pre_htf"] = signal

    if signal is None:
        print("[AVISO] El escenario sintético no generó señal de ensemble. "
              "Revisa build_breakout_scenario_5m() si esperabas una señal.")

    # 4. Confirmación multi-timeframe (15m sintético, tendencia alcista clara)
    df_htf = build_uptrend_scenario_htf()
    htf_context = compute_htf_context(df_htf, config)
    result["htf_context"] = htf_context

    signal_after_htf = apply_htf_confirmation(dict(signal) if signal else None, htf_context, config)
    result["ensemble_signal_post_htf"] = signal_after_htf

    # 5. Niveles de riesgo (SL/TP) + apalancamiento, si hay señal utilizable
    working_signal = signal_after_htf or signal
    if working_signal is not None:
        atr_val = last["ATR"]
        risk = build_risk_levels(
            entry_price=last["close"], atr_val=atr_val,
            signal_type=working_signal["direction"], preset=config.RISK_PRESET,
            df=df, cfg=config,
        )
        result["risk_levels_normal"] = risk

        risk_red = cap_tp_at_r(risk, last["close"], working_signal["direction"], config.RED_TP_CAP_R)
        result["risk_levels_red_capped"] = risk_red

        result["suggested_leverage"] = suggest_leverage(df, config)
    else:
        result["risk_levels_normal"] = None
        result["risk_levels_red_capped"] = None
        result["suggested_leverage"] = None

    result = _round_floats(result)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Caso dorado generado en: {OUTPUT_PATH}")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
