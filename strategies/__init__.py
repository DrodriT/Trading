"""
Paquete de estrategias — Rodri v1.0

Cada módulo implementa detect(df, cfg) -> {direction, score, confidence,
reason, metadata} | None. Este paquete re-exporta STRATEGY_NAMES y
DETECTORS para que el resto del proyecto (strategy.py, y en el futuro
ensemble.py) no tengan que conocer en qué archivo vive cada detector.
"""
from strategies.smc import detect_smc_reversal
from strategies.breakout import detect_breakout
from strategies.trend_pullback import detect_trend_pullback
from strategies.rsi_divergence import detect_rsi_divergence
from strategies.vp_mean_revert import detect_vp_mean_revert
from strategies.liquidity import detect_liquidity_grab

STRATEGY_NAMES = [
    "SMC_REVERSAL", "BREAKOUT", "TREND_PULLBACK",
    "RSI_DIVERGENCE", "VP_MEAN_REVERT", "LIQUIDITY_GRAB",
]

DETECTORS = {
    "SMC_REVERSAL": detect_smc_reversal,
    "BREAKOUT": detect_breakout,
    "TREND_PULLBACK": detect_trend_pullback,
    "RSI_DIVERGENCE": detect_rsi_divergence,
    "VP_MEAN_REVERT": detect_vp_mean_revert,
    "LIQUIDITY_GRAB": detect_liquidity_grab,
}

__all__ = [
    "STRATEGY_NAMES", "DETECTORS",
    "detect_smc_reversal", "detect_breakout", "detect_trend_pullback",
    "detect_rsi_divergence", "detect_vp_mean_revert", "detect_liquidity_grab",
]
