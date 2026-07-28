# ============================================================
#  CONFIGURACIÓN — BOT EN VIVO (Bitget DEMO, órdenes reales)
# ============================================================
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# --- Bitget (cuenta DEMO) ---
# Claves de la cuenta DEMO de Bitget (NO las de tu cuenta real).
BITGET_API_KEY = os.environ.get("BITGET_DEMO_API_KEY", "")
BITGET_API_SECRET = os.environ.get("BITGET_DEMO_API_SECRET", "")
BITGET_API_PASSWORD = os.environ.get("BITGET_DEMO_API_PASSWORD", "")  # passphrase
DEMO_MODE = True   # True = manda el header PAPTRADING=1 (cuenta demo).
                    # Pon False el día que quieras ir a cuenta real —
                    # y revisa TODO este archivo antes de hacerlo.
MARKET_TYPE = "swap"
MARGIN_MODE = "isolated"   # aislado, tal como pediste

# --- Símbolos y timeframe (mismos que el bot de alertas) ---
SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "XRP/USDT:USDT",
    "BCH/USDT:USDT", "SUI/USDT:USDT", "XLM/USDT:USDT", "INJ/USDT:USDT",
    "HBAR/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT", "LTC/USDT:USDT",
    "AAVE/USDT:USDT",
]
TIMEFRAME = "15m"
CONFIRM_TIMEFRAME = "1h"

# ============================================================
#  SYNAPSE TRAIL — mismos parámetros que bot_test/config.py
# ============================================================
ATR_LEN = 21
TRAIL_LEN = 34
BASE_MULT = 2.0
USE_ADAPTIVE_MULT = True
USE_RATCHET = True

ADX_PERIOD = 14
CHOPPINESS_LEN = 14
REGIME_LEN = 50

USE_HTF_FILTER = True
HTF_HARD_FILTER = True
HTF_EMA_PERIOD = 50

USE_VOLUME_FILTER = True
VOLUME_THRESHOLD = 1.3
VOLUME_MA_PERIOD = 20

RSI_PERIOD = 14

MIN_QUALITY_SCORE = 75
SKIP_CHOPPY_SIGNALS = True
REQUIRE_TRENDING_REGIME = True

RISK_PRESET = "Balanced"
USE_BREAK_EVEN = True

# ============================================================
#  GESTIÓN DE POSICIÓN — apalancamiento automático por riesgo
# ============================================================
# Fórmula: notional = (equity × RISK_PCT_PER_TRADE) / distancia%SL
#          leverage  = notional / (equity × MARGIN_PCT_PER_TRADE)
# Es decir: si el SL salta, se pierde exactamente RISK_PCT_PER_TRADE
# del equity; el margen usado es MARGIN_PCT_PER_TRADE del equity;
# el apalancamiento sale solo de esos dos números y de lo ancho que
# esté el SL (ATR) en cada señal — más ancho -> menos leverage.
RISK_PCT_PER_TRADE = 0.01     # 1% del equity en riesgo si salta el SL
MARGIN_PCT_PER_TRADE = 0.05   # 5% del equity como margen (aislado) por trade
MAX_LEVERAGE = 20             # tope de seguridad, aunque la fórmula pida más
MIN_LEVERAGE = 1

# --- Cierre parcial por TP ---
# 33% en TP1, 33% en TP2, y el TP3 cierra TODO lo que quede (evita
# arrastrar restos de redondeo de contratos por un 34% "a mano").
TP_SPLIT = [0.33, 0.33]  # TP3 = remainder

# --- Persistencia de estado ---
STATE_FILE = "live_state.json"

# --- Bucle de escaneo (segundos entre pasadas de búsqueda de señal) ---
SCAN_INTERVAL_SECONDS = 60          # cada minuto comprueba si hay vela nueva
POSITION_POLL_SECONDS = 15          # cada cuánto revisa fills de TP/SL

STRATEGY_LABEL = "LIVE (Synapse Trail — Bitget DEMO, aislado, riesgo automático)"
