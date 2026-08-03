"""
RSI_DIVERGENCE — envoltorio de estrategia sobre el indicador de
divergencia RSI (indicators/divergence.py).

Extraída de strategy.py sin cambios de cálculo. El indicador de bajo
nivel (rsi_divergence) sigue devolviendo (direction, strength) tal cual
siempre; esta estrategia solo adapta ese resultado al contrato rico
{direction, score, confidence, reason, metadata}.
"""
from indicators import rsi_divergence


def detect_rsi_divergence(df, cfg):
    """Divergencia clásica entre precio y RSI en los dos últimos swings
    confirmados (ver indicators/divergence.py)."""
    direction, score = rsi_divergence(df, "RSI", cfg.DIVERGENCE_LOOKBACK)
    if direction is None:
        return None
    reason = (
        "Divergencia alcista: mínimo de precio más bajo con RSI más alto"
        if direction == "ALCISTA" else
        "Divergencia bajista: máximo de precio más alto con RSI más bajo"
    )
    return {
        "direction": direction,
        "score": score,
        "confidence": score / 100.0,
        "reason": reason,
        "metadata": {"lookback": cfg.DIVERGENCE_LOOKBACK},
    }
