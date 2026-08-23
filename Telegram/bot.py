"""
Telegram/bot.py

Envío de mensajes a Telegram. Completamente desacoplado de la
estrategia: solo sabe formatear y enviar. Usa las variables de
entorno TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (nunca hardcodeadas).
"""

from __future__ import annotations
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


class TelegramBot:
    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.is_configured:
            logger.warning(
                "Telegram no configurado (faltan TELEGRAM_BOT_TOKEN / "
                "TELEGRAM_CHAT_ID). Mensaje NO enviado:\n%s", text
            )
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code != 200:
                logger.error("Telegram respondió %s: %s", resp.status_code, resp.text)
                return False
            return True
        except requests.RequestException as e:
            logger.error("Error de red enviando a Telegram: %s", e)
            return False


def send_signal(bot: TelegramBot, text: str) -> bool:
    """Punto de entrada simple usado por el resto del sistema."""
    return bot.send_message(text)
