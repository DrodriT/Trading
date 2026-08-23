"""
main.py

Punto de entrada. Diseñado para una ejecución única y corta,
disparada periódicamente por cron-job.org (o cron local, o un
scheduler cualquiera). No mantiene ningún proceso en segundo plano.

Uso:
    python main.py

Variables de entorno relevantes (ver Config/config.py):
    EXCHANGE_ID, SYMBOL, TIMEFRAME, LOOKBACK_BARS,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, STATE_FILE, DEBUG

Si se expone como endpoint HTTP (por ejemplo detrás de un pequeño
wrapper Flask/FastAPI para que cron-job.org pueda golpear una URL),
simplemente llama a `run_once()` desde el handler.
"""

from __future__ import annotations
import logging
import sys

from Config.config import INFRA, PINE
from Core.engine import Engine


def _setup_logging():
    level = logging.DEBUG if INFRA.DEBUG else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def run_once() -> int:
    """Devuelve un código de salida (0 = OK, != 0 = error)."""
    logger = logging.getLogger("main")
    try:
        engine = Engine(INFRA, PINE)
        engine.run()
        return 0
    except Exception:
        logger.exception("Fallo no controlado durante la ejecución del bot.")
        return 1


if __name__ == "__main__":
    _setup_logging()
    sys.exit(run_once())
