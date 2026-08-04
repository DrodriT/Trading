"""
Scoring — conversión de score (0-100) a probabilidad.

Extraído de strategy.py sin cambios de lógica.
"""


def score_to_probability(score: float, cfg) -> float:
    """Mapea linealmente el score 0-100 al rango [PROB_AT_SCORE_0,
    PROB_AT_SCORE_100] configurado, recortado a [0, 1]."""
    p0, p100 = cfg.PROB_AT_SCORE_0, cfg.PROB_AT_SCORE_100
    prob = p0 + (score / 100.0) * (p100 - p0)
    return max(0.0, min(1.0, prob))
