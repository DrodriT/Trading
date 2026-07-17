# ============================================================
#  CONFIGURACIÓN DEL BOT
#  Rellena estos valores antes de ejecutar bot.py
# ============================================================
import os

# --- Telegram ---
# 1. Habla con @BotFather en Telegram, crea un bot con /newbot y copia el TOKEN.
# 2. Escríbele algo a tu bot (o añádelo a un grupo) y luego visita:
#    https://api.telegram.org/bot<TU_TOKEN>/getUpdates
#    para localizar tu "chat_id" (aparece en result -> message -> chat -> id).
#
# Para uso LOCAL: puedes escribir los valores directamente aquí abajo.
# Para GitHub Actions: NO los escribas aquí. Se leen de los "Secrets" del repo
# (TELEGRAM_TOKEN y TELEGRAM_CHAT_ID) a través de variables de entorno, y
# tienen prioridad sobre lo que pongas en este archivo.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# --- Exchange (fuente de precios, no necesita API key para datos públicos) ---
EXCHANGE_ID = "bitget"   # otras opciones válidas de ccxt: "kraken", "coinbase", "kucoin", etc.
# EXCHANGE_ID = "binance"   # otras opciones válidas de ccxt: "kraken", "coinbase", "kucoin", etc.

# --- Lista de criptos a vigilar ---
# Usa el formato de ccxt: "BASE/QUOTE", ej. "BTC/USDT", "ETH/USDT"
SYMBOLS = [
   "BTC/USDT",
    "ETH/USDT",
    # añade aquí tus monedas, ej:
     "SOL/USDT",
     "XRP/USDT",
     "BCH/USDT",
     "XLM/USDT",
     "HBAR/USDT",
     "ADA/USDT",
]

# --- Timeframe ---
# Valores típicos de ccxt: "5m", "15m", "1h", "4h", "1d"
TIMEFRAME = "15m"

# --- Parámetros de los indicadores ---
EMA_FAST = 13
EMA_SLOW = 200

STOCH_K_PERIOD = 8      # periodo para %K
STOCH_D_PERIOD = 3       # suavizado de %D (media móvil de %K)
STOCH_SMOOTH = 3         # suavizado adicional de %K (estocástico "lento")
STOCH_OVERSOLD = 20
STOCH_OVERBOUGHT = 80

# --- Lógica de la señal (fija) ---
# ALCISTA: Estocástico cruza al alza en sobreventa (%K < STOCH_OVERSOLD) Y precio > EMA200
# BAJISTA: Estocástico cruza a la baja en sobrecompra (%K > STOCH_OVERBOUGHT) Y precio < EMA200
REQUIRE_CONFLUENCE = False  # se mantiene por compatibilidad, ya no afecta a la lógica

# --- Frecuencia de revisión (segundos) ---
CHECK_INTERVAL_SECONDS = 300  # cada 5 minutos revisa si hay una vela nueva cerrada

# --- Persistencia de estado (para no repetir el mismo aviso) ---
STATE_FILE = "state.json"
