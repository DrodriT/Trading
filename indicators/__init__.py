"""
Paquete de indicadores — Rodri v1.0

Re-exporta cada función de indicador con su nombre original, de forma que
el resto del proyecto (strategy.py) pueda seguir haciendo:

    from indicators import (
        add_ema, add_atr, add_adx, add_rsi, add_volume_ratio,
        add_swings, add_volume_profile, rsi_divergence, last_confirmed_swing,
    )

exactamente igual que antes, cuando todo vivía en un único
indicators_rodri.py. Ningún cálculo cambia: esto es solo el punto de
entrada del paquete.
"""
from indicators.ema import add_ema
from indicators.atr import add_atr
from indicators.adx import add_adx
from indicators.rsi import add_rsi
from indicators.volume import add_volume_ratio
from indicators.swings import add_swings, last_confirmed_swing
from indicators.volume_profile import add_volume_profile
from indicators.divergence import rsi_divergence

__all__ = [
    "add_ema", "add_atr", "add_adx", "add_rsi", "add_volume_ratio",
    "add_swings", "last_confirmed_swing", "add_volume_profile", "rsi_divergence",
]
