# ============================================================
#  CONFIGURACIÓN — Estrategia "Rodri v1.0" (ensemble multi-estrategia)
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
    "ICP/USDT:USDT",
    "OP/USDT:USDT",
    "NEAR/USDT:USDT",
    "XMR/USDT:USDT",
    "DOGE/USDT:USDT",
]

# --- Timeframes ---
TIMEFRAME = "5m"           # escaneo de señales (detección del ensemble)
MONITOR_TIMEFRAME = "1m"   # seguimiento de SL/TP de posiciones abiertas

# --- Indicadores base compartidos ---
ATR_LEN = 14
EMA_FAST = 20
EMA_SLOW = 50
ADX_PERIOD = 14
RSI_PERIOD = 14
VOLUME_MA_PERIOD = 20
SWING_LEFT = 3             # velas a cada lado para confirmar un fractal/swing
SWING_RIGHT = 3

# --- Parámetros específicos por estrategia ---
SMC_LOOKBACK = 50           # velas hacia atrás para buscar el swing a barrer
LG_LOOKBACK = 20            # ventana corta para LIQUIDITY_GRAB
LG_MIN_WICK_ATR_RATIO = 0.3 # mínimo de mecha (relativa al ATR) para considerar el barrido válido
BREAKOUT_LOOKBACK = 30      # ventana del rango para BREAKOUT
BREAKOUT_VOL_THRESHOLD = 1.3
TREND_ADX_MIN = 20          # ADX mínimo para considerar "tendencia establecida"
DIVERGENCE_LOOKBACK = 30    # ventana para buscar los 2 swings de la divergencia
VP_LOOKBACK = 100           # velas para construir el Volume Profile
VP_BINS = 24

STRATEGY_WEIGHTS = {
    "SMC_REVERSAL":     1.40,
    "BREAKOUT":         1.10,
    "TREND_PULLBACK":   1.25,
    "RSI_DIVERGENCE":   0.80,
    "VP_MEAN_REVERT":   0.50,
    "LIQUIDITY_GRAB":   1.00,
}

# SMC REVERSAL
SMC_SWEEP_WEIGHT      = 40.0
SMC_REJECTION_WEIGHT  = 20.0
SMC_BODY_WEIGHT       = 15.0
SMC_CHOCH_WEIGHT      = 15.0
SMC_VOLUME_WEIGHT     = 10.0

# --- Ensemble / Score / Probabilidad ---
MAX_SOLO_SCORE = 70            # techo de score cuando dispara UNA sola estrategia (sin confluencia)
MIN_CONFLUENCE_FOR_NORMAL = 2  # una señal "normal" (tamaño completo) necesita >=2 estrategias de acuerdo
CONFLUENCE_BONUS = 5           # puntos extra por cada estrategia adicional en la misma dirección
PROB_AT_SCORE_0 = 0.30
PROB_AT_SCORE_100 = 0.85

# --- Umbrales de filtrado ---
MIN_SCORE = 75
MIN_PROB = 0.40

# --- Señales "rojas" (baja confianza, no descartadas del todo) ---
RED_MIN_PROB = 0.40
RED_SIZE_FACTOR = 0.30
RED_MAX_PER_DAY = 2
RED_TP_CAP_R = 1.7

# --- Threshold dinámico ---
USE_DYNAMIC_THRESHOLD = True
DYNAMIC_THRESHOLD_LOOKBACK_TRADES = 10
DYNAMIC_THRESHOLD_STEP = 5
DYNAMIC_THRESHOLD_MIN = 50
DYNAMIC_THRESHOLD_MAX = 75
DYNAMIC_LOSING_STREAK_TO_RAISE = 3
DYNAMIC_WINNING_STREAK_TO_LOWER = 3

# --- Gestión de posiciones ---
MAX_CONCURRENT_TRADES = 2
MAX_TRADES_PER_SYMBOL = 1
COOLDOWN_HOURS = 4

# --- Riesgo / TP ---
RISK_PRESET = "Balanced"
USE_BREAK_EVEN = True

# --- Stop Loss estructural (swing anterior en vez de ATR fijo) ---
# Motivado por casos reales donde el SL por ATR cerraba la operación
# justo antes de que el precio girara, mientras que un SL colocado bajo
# el swing structural anterior la habría dejado correr hasta ganar.
STRUCTURAL_SL_ENABLED = True
STRUCTURAL_SL_ATR_BUFFER = 0.2     # colchón en múltiplos de ATR por debajo/encima del swing
STRUCTURAL_SL_LOOKBACK = 50        # velas hacia atrás para buscar el swing de referencia
STRUCTURAL_SL_MAX_ATR_MULT = 3.0   # si la distancia estructural supera esto (x ATR) -> fallback a SL por ATR

# --- Apalancamiento sugerido (según volatilidad ATR%) ---
LEVERAGE_MIN = 5
LEVERAGE_MAX = 20
LEV_ATR_PCT_LOW = 0.3
LEV_ATR_PCT_HIGH = 2.0

# --- Gráfico de señal (imagen adjunta al mensaje de apertura, estilo V9) ---
CHART_LOOKBACK_CANDLES = 150

# ============================================================
# --- Confirmación multi-timeframe (15m) ---
# Idea: no repetir las 6 estrategias en 15m, solo mirar si hay una
# tendencia clara (EMA rápida/lenta + ADX) que respalde o contradiga la
# dirección detectada en 5m, y penalizar o bloquear en consecuencia.
# ============================================================
CONFIRM_ENABLED = True
CONFIRM_TIMEFRAME = "15m"
CONFIRM_EMA_FAST = 20
CONFIRM_EMA_SLOW = 50
CONFIRM_ADX_PERIOD = 14
CONFIRM_LOOKBACK_CANDLES = 100   # velas de 15m a descargar para EMA/ADX

CONFIRM_ADX_MIN = 20            # ADX 15m mínimo para considerar que hay tendencia clara
CONFIRM_BLOCK_ADX_MIN = 30      # ADX 15m a partir del cual, si va en contra, se BLOQUEA la señal
CONFIRM_SCORE_PENALTY = 15      # puntos que se restan si el score va contra-tendencia (moderado)

# --- Persistencia y ritmo ---
TRADE_LOG_MAX = 300
STATE_FILE = "state_rodri.json"
CHECK_INTERVAL_SECONDS = 60

# --- Resumen diario ---
SEND_DAILY_SUMMARY = True
DAILY_SUMMARY_HOUR_UTC = 0

STRATEGY_LABEL = "Rodri v1.0 (Multi-Estrategia)"
