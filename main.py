"""
Bot de alertas — Estrategia "Rodri v1.0" (ensemble multi-estrategia)

Motor de 6 estrategias (SMC_REVERSAL, BREAKOUT, TREND_PULLBACK,
RSI_DIVERGENCE, VP_MEAN_REVERT, LIQUIDITY_GRAB) combinadas en un score +
probabilidad (ver ensemble.py), con:
  - Gestión de posiciones multi-trade (máx N simultáneas, 1 por activo)
  - Cooldown por símbolo tras cerrar un trade
  - Señales "rojas" de baja confianza (tamaño reducido, TP capado, límite diario)
  - Threshold de score dinámico según rachas de resultados recientes
  - Apalancamiento sugerido según volatilidad

Es una versión NUEVA e independiente del bot "Synapse" (bot.py): usa su
propio archivo de estado (state.json) y no modifica nada del bot
original.

Tras la Fase 6 de la refactorización, este archivo es solo el
orquestador de alto nivel (bucle principal). El resto de responsabilidades
vive en:
  - exchange.py    (conexión ccxt, descarga de velas)
  - telegram.py     (envío de mensajes, formato)
  - state.py         (persistencia, cooldowns, threshold dinámico)
  - positions.py      (apertura/cierre/flip de posiciones, check_symbol,
                        resumen diario)
  - strategy.py, ensemble.py, scoring.py, market_state.py, risk.py,
    strategies/, indicators/ (motor de señales y riesgo)

Uso:
    python3 main.py            # corre en bucle
    python3 main.py --once     # ejecuta una sola pasada (GitHub Actions)
"""
import sys
import time
from datetime import datetime, timezone

import config
from exchange import create_exchange
from state import load_state, save_state, update_dynamic_threshold
from positions import check_symbol, maybe_send_daily_summary
from telegram import send_startup_message
from core.logger import get_logger

logger = get_logger(__name__)


def run_once():
    exchange = create_exchange(config)
    state = load_state()
    now = datetime.now(timezone.utc)

    update_dynamic_threshold(state)

    for symbol in config.SYMBOLS:
        try:
            check_symbol(exchange, symbol, state, now)
        except Exception as e:
            logger.error(f"{symbol}: {e}")

    maybe_send_daily_summary(state)
    save_state(state)


def notify_startup_once():
    """
    Manda el mensaje de arranque (resumen de config) solo la primera vez
    que el bot corre — se recuerda en state.json, así que en modo
    --once (GitHub Actions, un proceso nuevo cada vez) no se repite en
    cada ejecución programada.
    """
    state = load_state()
    if not state.get("startup_notified"):
        send_startup_message()
        state["startup_notified"] = True
        save_state(state)


def main():
    logger.info(f"[{config.STRATEGY_LABEL}] Bot iniciado {datetime.now(timezone.utc).isoformat()} | "
                f"Símbolos: {config.SYMBOLS} | Timeframe: {config.TIMEFRAME}")
    notify_startup_once()

    if "--once" in sys.argv:
        run_once()
        return

    while True:
        run_once()
        time.sleep(config.CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
