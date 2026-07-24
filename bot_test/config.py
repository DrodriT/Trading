# ============================================================
# CONFIGURACIÓN — Synapse Trail Signal Bot
# GitHub Actions + Seguimiento de SL/TP/BE
# ============================================================
import os

# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ============================================================
# SÍMBOLOS A VIGILAR
# ============================================================
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
CONFIRM_TIMEFRAME = "1h"

# ============================================================
# SYNAPSE TRAIL
# ============================================================
ATR_LEN = 13
TRAIL_LEN = 21
BASE_MULT = 1.618
USE_ADAPTIVE_MULT = True
USE_RATCHET = True

# ============================================================
# MARKET REGIME
# ============================================================
ADX_PERIOD = 14
CHOPPINESS_LEN = 14
REGIME_LEN = 50
REGIME_TRENDING = 60
REGIME_CHOPPY = 35

# ============================================================
# QUALITY SCORE
# ============================================================
USE_HTF_FILTER = True
HTF_EMA_PERIOD = 50
USE_VOLUME_FILTER = True
VOLUME_THRESHOLD = 1.3
VOLUME_MA_PERIOD = 20
RSI_PERIOD = 14
MIN_QUALITY_SCORE = 55
GRADE_A_THRESHOLD = 75
GRADE_B_THRESHOLD = 55

# ============================================================
# GESTIÓN DE RIESGO
# ============================================================
RISK_PRESET = "Balanced"
SL_MULT = 1.5
TP1_MULT = 1.0
TP2_MULT = 2.0
TP3_MULT = 3.0
USE_BREAK_EVEN = True

# ============================================================
# PERSISTENCIA
# ============================================================
STATE_FILE = "state.json"

# ============================================================
# ETIQUETA
# ============================================================
STRATEGY_LABEL = "RODRI SIGNALS v1.0"