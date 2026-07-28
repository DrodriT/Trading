"""
Listener de comandos de Telegram por long-polling (getUpdates), en su
propio hilo — permite responder al instante a /posiciones y /stats sin
depender de la frecuencia de escaneo del bot.

No usa ninguna librería extra (python-telegram-bot, etc.) para mantener
las dependencias mínimas: solo `requests`, que ya usa el resto del bot.
"""
import threading
import time

import requests

import live_config as config


def send_telegram(message: str):
    if "PON_AQUI" in config.TELEGRAM_TOKEN or "PON_AQUI" in config.TELEGRAM_CHAT_ID:
        print("[AVISO] Configura TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en live_config.py")
        print(message)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR Telegram] {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[ERROR Telegram] {e}")


class TelegramCommandListener:
    """
    Hilo en segundo plano que hace polling a getUpdates cada pocos
    segundos y despacha comandos reconocidos a los handlers registrados.

    Uso:
        listener = TelegramCommandListener()
        listener.register("/posiciones", handler_posiciones)
        listener.register("/stats", handler_stats)
        listener.start()
        ...
        listener.stop()
    """

    def __init__(self, poll_interval_seconds: float = 2.0):
        self.poll_interval_seconds = poll_interval_seconds
        self.handlers = {}
        self._offset = None
        self._stop_event = threading.Event()
        self._thread = None

    def register(self, command: str, handler):
        """handler: función sin argumentos que devuelve el string a enviar."""
        self.handlers[command.lower()] = handler

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
        while not self._stop_event.is_set():
            try:
                params = {"timeout": 20}
                if self._offset is not None:
                    params["offset"] = self._offset
                resp = requests.get(url, params=params, timeout=25)
                data = resp.json()
                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    message = update.get("message") or update.get("channel_post")
                    if not message:
                        continue
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    text = (message.get("text") or "").strip()
                    # Solo responde al chat configurado — evita que
                    # cualquiera que escriba al bot dispare comandos.
                    if chat_id != str(config.TELEGRAM_CHAT_ID):
                        continue
                    command = text.split()[0].lower() if text else ""
                    handler = self.handlers.get(command)
                    if handler:
                        try:
                            reply = handler()
                        except Exception as e:
                            reply = f"⚠️ Error ejecutando {command}: {e}"
                        send_telegram(reply)
            except Exception as e:
                print(f"[WARN] TelegramCommandListener poll: {e}")
                time.sleep(self.poll_interval_seconds)
                continue
            time.sleep(self.poll_interval_seconds)
