"""
Core/state.py

Control de estado entre ejecuciones (cron-job.org lanza el proceso
de forma independiente cada vez, así que el "estado" de qué señales
ya se enviaron tiene que persistir en disco).

Estrategia de dedupe:
  Cada alerta generada por la estrategia tiene un `timestamp` (de la
  vela que la originó) y un `type` (buy/sell/flip/sl_hit/tp1_hit/...).
  Guardamos un identificador único `symbol|timeframe|timestamp|type`
  en una lista de "ya enviadas". Si el cron se ejecuta varias veces
  dentro de la misma vela, el motor recalculará la misma alerta una
  y otra vez, pero el `already_sent()` la filtrará.

  Para que el archivo no crezca sin límite, solo se conservan los
  últimos N identificadores (por defecto 500).
"""

from __future__ import annotations
import json
import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

MAX_SENT_HISTORY = 500


@dataclass
class BotState:
    # Última vela procesada, POR SÍMBOLO+TIMEFRAME (clave "SYMBOL|TIMEFRAME"),
    # para que analizar varias monedas en la misma ejecución no se pisen
    # entre sí. Se mantiene también `last_processed_timestamp` (legacy,
    # global) por compatibilidad con estados guardados antes de soportar
    # múltiples símbolos.
    last_processed_by_key: dict = field(default_factory=dict)
    last_processed_timestamp: Optional[str] = None  # legacy / no usado en multi-símbolo
    sent_alert_ids: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "last_processed_by_key": self.last_processed_by_key,
            "last_processed_timestamp": self.last_processed_timestamp,
            "sent_alert_ids": self.sent_alert_ids,
        }

    @staticmethod
    def from_dict(d: dict) -> "BotState":
        return BotState(
            last_processed_by_key=d.get("last_processed_by_key", {}),
            last_processed_timestamp=d.get("last_processed_timestamp"),
            sent_alert_ids=d.get("sent_alert_ids", []),
        )


class StateManager:
    def __init__(self, state_file: str):
        self.state_file = state_file
        os.makedirs(os.path.dirname(state_file), exist_ok=True)

    def load(self) -> BotState:
        if not os.path.exists(self.state_file):
            return BotState()
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return BotState.from_dict(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.error("No se pudo leer el estado (%s). Se usa estado vacío.", e)
            return BotState()

    def save(self, state: BotState) -> None:
        # Recorta el historial para no crecer indefinidamente
        state.sent_alert_ids = state.sent_alert_ids[-MAX_SENT_HISTORY:]
        tmp_path = self.state_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, default=str)
            os.replace(tmp_path, self.state_file)
        except OSError as e:
            logger.error("No se pudo guardar el estado: %s", e)

    @staticmethod
    def alert_id(symbol: str, timeframe: str, timestamp, alert_type: str) -> str:
        return f"{symbol}|{timeframe}|{timestamp}|{alert_type}"

    @staticmethod
    def symbol_key(symbol: str, timeframe: str) -> str:
        return f"{symbol}|{timeframe}"

    @staticmethod
    def already_sent(state: BotState, alert_id: str) -> bool:
        return alert_id in state.sent_alert_ids

    @staticmethod
    def mark_sent(state: BotState, alert_id: str) -> None:
        state.sent_alert_ids.append(alert_id)
