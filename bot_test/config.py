# ============================================================
# CONFIGURACIÓN — Rodri Bot
# ============================================================
import os

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# ============================================================
# EXCHANGE (Bitget Futuros USDT-M)
# ============================================================
EXCHANGE_ID = "bitget"
API_KEY = os.environ.get("BITGET_API_KEY", "")
API_SECRET = os.environ.get("BITGET_API_SECRET", "")
API_PASSWORD = os.environ.get("BITGET_API_PASSWORD", "")  # Bitget requiere passphrase
MARKET_TYPE = "swap"

# Símbolos a vigilar
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
]

# ============================================================
# TIMEFRAMES
# ============================================================
TIMEFRAME = "5m"
CONFIRM_TIMEFRAME = "1h"  # HTF para el filtro de sesgo

# ============================================================
# SYNAPSE TRAIL (banda de tendencia)
# ============================================================
ATR_LEN = 13
TRAIL_LEN = 21
BASE_MULT = 1.618
USE_ADAPTIVE_MULT = True   # Ajusta el multiplicador según volatilidad
USE_RATCHET = True         # La banda solo se aprieta a favor de la posición

# ============================================================
# MARKET REGIME (Trending / Choppy / Mixed)
# ============================================================
ADX_PERIOD = 14
CHOPPINESS_LEN = 14
REGIME_LEN = 50            # Ventana para R² (linealidad)

# Umbrales (del indicador original)
REGIME_TRENDING = 60
REGIME_CHOPPY = 35

# ============================================================
# QUALITY SCORE (HTF 30 + Vol 20 + RSI 20 + Regime 20 + Break 10 = 100)
# ============================================================
USE_HTF_FILTER = True
HTF_EMA_PERIOD = 50        # EMA en timeframe de confirmación

USE_VOLUME_FILTER = True   # Activado como pediste
VOLUME_THRESHOLD = 1.3
VOLUME_MA_PERIOD = 20

RSI_PERIOD = 14

# Filtros de señal
MIN_QUALITY_SCORE = 0      # 0 = todas las señales (A, B, C)
SKIP_CHOPPY_SIGNALS = False  # False = muestra warning, no suprime
GRADE_A_THRESHOLD = 75
GRADE_B_THRESHOLD = 55

# ============================================================
# GESTIÓN DE RIESGO — Balanced Preset
# ============================================================
RISK_PRESET = "Balanced"
SL_MULT = 1.5              # SL = 1.5 × ATR
TP1_MULT = 1.0             # TP1 = 1.0R
TP2_MULT = 2.0             # TP2 = 2.0R
TP3_MULT = 3.0             # TP3 = 3.0R

USE_BREAK_EVEN = True      # Mover SL a entrada tras TP1

# Tamaño de posición (% del capital por operación)
RISK_PER_TRADE_PCT = 1.0   # Arriesgar 1% del capital por trade
LEVERAGE = 3               # Leverage fijo

# Entrada escalonada: 3 órdenes de igual tamaño
ENTRY_SPLITS = 3           # Dividir entrada en 3 partes iguales

# ============================================================
# PERSISTENCIA
# ============================================================
STATE_FILE = "synapse_state.json"

# ============================================================
# LOOP
# ============================================================
CHECK_INTERVAL_SECONDS = 60  # Revisar cada 60s (suficiente para 5m)

# Etiqueta para mensajes de Telegram
STRATEGY_LABEL = "RODRI BOT"