"""
Logging centralizado — Rodri v1.0

Sustituye los print() sueltos que había por todo el proyecto (main.py,
telegram.py, positions.py) por un logger estructurado con timestamp y
nivel. No cambia NINGÚN mensaje de texto ni su contenido — solo cómo se
emite: antes iba directo a stdout con print(), ahora pasa por el logger
(que también escribe a stdout, así que en GitHub Actions se sigue viendo
igual, solo que con timestamp y nivel delante).

tools/analyze.py NO usa este logger a propósito: es un script de
informe para humanos pensado para leerse en la terminal tal cual, no un
componente del bot en ejecución — su salida debe quedarse como print()
plano, sin timestamps ni niveles de por medio.
"""
import logging
import sys

_CONFIGURED_LOGGERS = set()


def get_logger(name: str = "rodri") -> logging.Logger:
    """
    Devuelve un logger configurado para escribir a stdout (igual que los
    print() que sustituye) con formato "HH:MM:SS [NIVEL] mensaje".
    Idempotente: si ya se configuró un logger con ese nombre, devuelve el
    mismo sin añadir handlers duplicados (importante porque get_logger()
    se puede llamar desde varios módulos).
    """
    logger = logging.getLogger(name)
    if name not in _CONFIGURED_LOGGERS:
        handler = logging.StreamHandler(stream=sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _CONFIGURED_LOGGERS.add(name)
    return logger
