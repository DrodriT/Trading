"""
Mensajería de Telegram — Rodri v1.0

Extraído de main.py (antes bot_rodri.py) sin cambios de lógica. Agrupa el
envío (texto/foto), el mensaje de arranque, y las utilidades de formato
que solo tienen sentido en el contexto de un mensaje de Telegram
(escapado de Markdown, símbolo para mostrar, porcentaje desde entrada).
"""
import requests

import config
from strategies import STRATEGY_NAMES


def send_telegram(message: str):
    """Envía un mensaje de texto por Telegram (Markdown legacy), con
    reintento en texto plano si falla el parseo de Markdown."""
    if "PON_AQUI" in config.TELEGRAM_TOKEN or "PON_AQUI" in config.TELEGRAM_CHAT_ID:
        print("[AVISO] Configura TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en config.py")
        print(message)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        if resp.status_code != 200:
            print(f"[ERROR Telegram] {resp.status_code}: {resp.text}")
            # Red de seguridad: si el error es de parseo de Markdown (p.ej.
            # un carácter especial que se nos escapó), reintenta en texto
            # plano para que el aviso llegue igualmente en vez de perderse.
            resp2 = requests.post(url, data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": message,
            }, timeout=10)
            if resp2.status_code != 200:
                print(f"[ERROR Telegram, reintento plano] {resp2.status_code}: {resp2.text}")
    except Exception as e:
        print(f"[ERROR Telegram] {e}")


def send_telegram_photo(image_path: str, caption: str = ""):
    """Manda una foto (el gráfico de la señal) con el texto como caption."""
    if "PON_AQUI" in config.TELEGRAM_TOKEN or "PON_AQUI" in config.TELEGRAM_CHAT_ID:
        print("[AVISO] Configura TELEGRAM_TOKEN y TELEGRAM_CHAT_ID en config.py")
        print(caption)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(image_path, "rb") as photo:
            resp = requests.post(url, data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "Markdown",
            }, files={"photo": photo}, timeout=20)
        if resp.status_code != 200:
            print(f"[ERROR Telegram photo] {resp.status_code}: {resp.text}")
            # Red de seguridad: reintenta la misma foto sin parse_mode si
            # el fallo fue por el formato del caption, para no perder el
            # aviso de apertura en silencio.
            with open(image_path, "rb") as photo:
                resp2 = requests.post(url, data={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "caption": caption,
                }, files={"photo": photo}, timeout=20)
            if resp2.status_code != 200:
                print(f"[ERROR Telegram photo, reintento plano] {resp2.status_code}: {resp2.text}")
    except Exception as e:
        print(f"[ERROR Telegram photo] {e}")


def send_startup_message():
    """Mensaje de arranque con el resumen de la config activa (estilo V9)."""
    threshold_mode = "DYNAMIC" if config.USE_DYNAMIC_THRESHOLD else "FIXED"
    msg = (
        f"🤖 Bot \"{config.STRATEGY_LABEL}\" iniciado.\n"
        f"Activos: {len(config.SYMBOLS)} | Estrategias: {md_escape(', '.join(STRATEGY_NAMES))}\n"
        f"Exchange: {config.EXCHANGE_ID} ({config.MARKET_TYPE})\n"
        f"Threshold mode: {threshold_mode}\n"
        f"Escaneo: {config.TIMEFRAME} | Seguimiento: {config.MONITOR_TIMEFRAME}\n"
        f"MIN_SCORE={config.MIN_SCORE} | MIN_PROB={config.MIN_PROB}\n"
        f"Multi: max {config.MAX_CONCURRENT_TRADES} trades | 1 por activo | "
        f"cooldown {config.COOLDOWN_HOURS}h\n"
        f"Rojas: x{config.RED_SIZE_FACTOR}, max {config.RED_MAX_PER_DAY}/día, "
        f"prob≥{config.RED_MIN_PROB}, TP cap {config.RED_TP_CAP_R}R\n"
        f"Ensemble: bonus por confluencia ({config.CONFLUENCE_BONUS} pts/estrategia extra)\n"
        f"Confirmación {config.CONFIRM_TIMEFRAME}: "
        f"{'ON' if config.CONFIRM_ENABLED else 'OFF'}"
        f"{f' (penaliza -{config.CONFIRM_SCORE_PENALTY} si ADX≥{config.CONFIRM_ADX_MIN}, bloquea si ADX≥{config.CONFIRM_BLOCK_ADX_MIN})' if config.CONFIRM_ENABLED else ''}"
    )
    send_telegram(msg)


def display_symbol(symbol: str) -> str:
    """Convierte 'BTC/USDT:USDT' en 'BTCUSDT' para mostrar en mensajes."""
    return symbol.split(":")[0].replace("/", "")


def md_escape(text: str) -> str:
    """
    Escapa los caracteres especiales del Markdown "legacy" de Telegram
    (_ * ` [ ). Es imprescindible para los nombres de estrategia
    (SMC_REVERSAL, TREND_PULLBACK, RSI_DIVERGENCE, LIQUIDITY_GRAB...): al
    llevar un número impar de "_", Telegram no puede emparejar la cursiva
    y devuelve un error 400 "can't parse entities" — y como send_telegram
    solo registra el error sin lanzar excepción, el mensaje se pierde en
    silencio (nunca llega, aunque el bot siga funcionando con normalidad).
    """
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def pct_from_entry(entry: float, level: float) -> str:
    """Formatea el porcentaje de un nivel (SL/TP) respecto al precio de
    entrada, listo para insertar en un mensaje de Telegram."""
    if not entry:
        return ""
    pct = (level - entry) / entry * 100.0
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


def context_line(pos: dict) -> str:
    """
    Línea de contexto de una posición (score/prob/estrategias/lev).

    Nota de la Fase 6: esta función ya no se llamaba desde ningún sitio
    en el main.py original tampoco — se conserva tal cual (sin borrar
    funcionalidad existente), pero no está conectada a ningún flujo activo.
    """
    tag = f" | ⚠️ ROJA (x{config.RED_SIZE_FACTOR})" if pos.get("is_red") else ""
    return (f"Score: *{pos['score']}* | Prob: {pos['prob'] * 100:.0f}% | "
            f"{md_escape('+'.join(pos['strategies']))} | Lev: {pos['leverage']}x{tag}")
