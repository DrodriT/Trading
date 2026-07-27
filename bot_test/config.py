# ============================================================
#  CONFIGURACIÓN DEL BOT — VERSIÓN "Synapse" (basada en Synapse Trail Pro)
#  Rellena estos valores antes de ejecutar bot.py
# ============================================================
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# --- Bitget Demo ---
BITGET_API_KEY = os.environ.get('BITGET_API_KEY')
BITGET_SECRET_KEY = os.environ.get('BITGET_SECRET_KEY')
BITGET_PASSPHRASE = os.environ.get('BITGET_PASSPHRASE')
BITGET_DEMO = True   # Siempre True para cuenta demo

# Parámetros de orden (ajusta según tu tolerancia al riesgo)
ORDER_AMOUNT_USDT = 50   # cantidad en USDT por operación (demo)
ORDER_TYPE = 'market'    # 'market' o 'limit' (recomiendo market para simplicidad)
# --- Apalancamiento y margen ---
LEVERAGE = 10            # 10x
MARGIN_MODE = 'isolated' # 'isolated' o 'crossed'

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
    "ICP/USDT:USDT",
    "OP/USDT:USDT",
    "NEAR/USDT:USDT",
    "XMR/USDT:USDT",
    "DOGE/USDT:USDT",
]

# --- Timeframe principal ---
TIMEFRAME = "15m"
 
# --- Timeframe de confirmación (HTF bias) ---
# El Pine usa autoHtf() = 4× el timeframe actual, redondeado al bucket
# disponible más cercano. Para 3m: 3×4=12min -> cae en el bucket "15".
CONFIRM_TIMEFRAME = "1h"
 
# ============================================================
#  SYNAPSE TRAIL (banda de tendencia tipo SuperTrend)
# ============================================================
# Valores subidos respecto al default del Pine para reducir la frecuencia
# de flips en 3m (menos operaciones, banda más "lenta" y menos sensible
# al ruido de una vela tan corta).
ATR_LEN = 21              # antes 13 — ATR más suavizado
TRAIL_LEN = 34            # antes 21 — EMA central más lenta
BASE_MULT = 2.0           # antes 1.618 — banda más ancha, menos whipsaws
USE_ADAPTIVE_MULT = True  # antes False — ensancha la banda aún más en picos de volatilidad
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
HTF_HARD_FILTER = True   # nuevo — si el HTF está en contra, descarta la señal
                         # directamente (no solo resta puntos del Quality Score)
HTF_EMA_PERIOD = 50      # EMA usada en el timeframe de confirmación para el HTF bias
 
USE_VOLUME_FILTER = True    # antes False — exige volumen real de respaldo
VOLUME_THRESHOLD = 1.3      # el volumen debe superar 1.3x su media de 20 velas para confirmar
VOLUME_MA_PERIOD = 20
 
RSI_PERIOD = 14
 
# --- Filtros sobre la señal ---
MIN_QUALITY_SCORE = 75   # antes 0 — solo Grado A (máxima selectividad)
SKIP_CHOPPY_SIGNALS = True   # antes False — descarta señales en régimen Choppy
REQUIRE_TRENDING_REGIME = True   # nuevo — exige régimen Trending (>=60), ni
                                 # siquiera Mixed vale; más estricto que
                                 # SKIP_CHOPPY_SIGNALS (que solo descarta <35)
 
# ============================================================
#  GESTIÓN DE RIESGO
# ============================================================
# Presets disponibles: "Conservative", "Balanced", "Aggressive", "Scalping"
RISK_PRESET = "Balanced"
USE_BREAK_EVEN = True    # mover el SL a la entrada tras alcanzar TP1
 
# --- Persistencia de estado ---
STATE_FILE = "state.json"
 
# --- Frecuencia de revisión en modo bucle (segundos) ---
# Solo aplica si corres `python bot.py` sin --once (modo bucle local).
# En GitHub Actions (--once) esto no se usa: la frecuencia real la marca
# quien dispare el workflow (cron-job.org) — debe apuntar cada 3 min.
CHECK_INTERVAL_SECONDS = 180
 
# ============================================================
#  RESUMEN DIARIO DE ESTADÍSTICAS
# ============================================================
# Envía un mensaje con el resumen de la sesión una vez al día.
# Se dispara la primera vez que el bot corre en la hora indicada
# (UTC) y no se ha enviado ya el resumen ese mismo día.
SEND_DAILY_SUMMARY = True
DAILY_SUMMARY_HOUR_UTC = 0  # 0 = medianoche UTC
 
# --- Etiqueta para identificar los mensajes de Telegram de esta versión ---
STRATEGY_LABEL = "RODRI (Bot Rodri v1.1)"