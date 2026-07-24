# ============================================================
#  CONFIGURACIÓN DEL BOT — VERSIÓN "Synapse" (basada en Synapse Trail Pro)
#  Rellena estos valores antes de ejecutar bot.py
# ============================================================
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# --- Exchange ---
EXCHANGE_ID = "bitget"
MARKET_TYPE = "swap"   # perpetuos

# --- Símbolos a vigilar (formato ccxt para perpetuos con margen USDT) ---
SYMBOLS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "BCH/USDT:USDT",
    "SUI/USDT:USDT",
    "XLM/USDT:USDT",
    "INJ/USDT:USDT",
    "HBAR/USDT:USDT",
    "ADA/USDT:USDT",
    "AVAX/USDT:USDT",
    "LTC/USDT:USDT",
    "AAVE/USDT:USDT",
]

# --- Timeframe principal ---
TIMEFRAME = "15m"

# --- Timeframe de confirmación (HTF bias) ---
CONFIRM_TIMEFRAME = "1h"

# ============================================================
#  SYNAPSE TRAIL (banda de tendencia tipo SuperTrend)
# ============================================================
ATR_LEN = 13             # ATR usado tanto para la banda como para el SL
TRAIL_LEN = 21           # periodo de la EMA que forma el centro de la banda
BASE_MULT = 1.618        # multiplicador base del ATR para el ancho de la banda
USE_ADAPTIVE_MULT = False  # si True, ajusta el multiplicador según percentil de volatilidad
USE_RATCHET = True       # la banda solo se aprieta a favor de la posición

# ============================================================
#  MARKET REGIME (Trending / Choppy / Mixed)
# ============================================================
ADX_PERIOD = 14
CHOPPINESS_LEN = 14
REGIME_LEN = 50          # ventana para el R² (linealidad)

# ============================================================
#  QUALITY SCORE (HTF 30 + Volumen 20 + RSI 20 + Régimen 20 + Ruptura 10 = 100)
# ============================================================
USE_HTF_FILTER = True
HTF_EMA_PERIOD = 50      # EMA usada en el timeframe de confirmación para el HTF bias

USE_VOLUME_FILTER = False   # si False, el componente de volumen da siempre 20/20
VOLUME_THRESHOLD = 1.3      # el volumen debe superar 1.3x su media de 20 velas para confirmar
VOLUME_MA_PERIOD = 20

RSI_PERIOD = 14

# --- Filtros sobre la señal ---
MIN_QUALITY_SCORE = 0    # 0 = mostrar todas las señales; sube esto para exigir más calidad
SKIP_CHOPPY_SIGNALS = False   # si True, descarta señales cuando el régimen es Choppy

# ============================================================
#  GESTIÓN DE RIESGO
# ============================================================
# Presets disponibles: "Conservative", "Balanced", "Aggressive", "Scalping"
RISK_PRESET = "Balanced"
USE_BREAK_EVEN = True    # mover el SL a la entrada tras alcanzar TP1

# --- Persistencia de estado ---
STATE_FILE = "state.json"

# --- Frecuencia de revisión en modo bucle (segundos) ---
CHECK_INTERVAL_SECONDS = 300

# --- Etiqueta para identificar los mensajes de Telegram de esta versión ---
STRATEGY_LABEL = "TEST (Synapse Trail: régimen + quality score + posición viva)"
