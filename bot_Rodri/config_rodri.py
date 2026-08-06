# ============================================================
#  CONFIGURACIÓN — Estrategia "Rodri v1.0" (ensemble multi-estrategia)
#  Inspirada en la ficha de parámetros de "Bot Portero V9 Sniper".
#  Archivo AUTOCONTENIDO: no depende de ningún otro config.py.
# ============================================================
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "PON_AQUI_TU_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "PON_AQUI_TU_CHAT_ID")

# --- Exchange ---
EXCHANGE_ID = "bitget"
MARKET_TYPE = "swap"   # perpetuos

# --- Símbolos a vigilar (formato ccxt para perpetuos con margen USDT) ---
# El V9 vigila 30 activos. De momento son los mismos 18 que ya usabas;
# añade aquí los que falten cuando quieras llegar a los 30.
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
HIGHER_TIMEFRAME = "15m"   # Filtro macro de tendencia (confirmación)
MONITOR_TIMEFRAME = "1m"   # seguimiento de SL/TP de posiciones abiertas

# --- Filtro Macro ---
MACRO_EMA_PERIOD = 200     # Periodo de la EMA para tendencia macro (15m)

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
SMC_LOOKBACK = 50          # velas hacia atrás para buscar el swing a barrer
LG_LOOKBACK = 20           # ventana corta para LIQUIDITY_GRAB
BREAKOUT_LOOKBACK = 30     # ventana del rango para BREAKOUT
BREAKOUT_VOL_THRESHOLD = 1.3
TREND_ADX_MIN = 20         # ADX mínimo para considerar "tendencia establecida"
DIVERGENCE_LOOKBACK = 30   # ventana para buscar los 2 swings de la divergencia
VP_LOOKBACK = 100          # velas para construir el Volume Profile
VP_BINS = 24

# --- Ensemble / Score / Probabilidad ---
MAX_SOLO_SCORE = 70            # techo de score cuando dispara UNA sola estrategia (sin confluencia)
MIN_CONFLUENCE_FOR_NORMAL = 2  # una señal "normal" (tamaño completo) necesita >=2 estrategias de acuerdo;
                                # con solo 1 estrategia, la señal SIEMPRE se trata como "roja" como mucho
CONFLUENCE_BONUS = 5           # puntos extra por cada estrategia adicional en la misma dirección
PROB_AT_SCORE_0 = 0.30         # probabilidad heurística cuando score=0
PROB_AT_SCORE_100 = 0.85       # probabilidad heurística cuando score=100
# NOTA: esta "Prob" es una transformación del score, NO una probabilidad
# estadística basada en backtest (no existe ese modelo en los archivos
# originales). Ajusta PROB_AT_SCORE_0/100 si más adelante calibras con
# resultados reales.

# --- Umbrales de filtrado ---
MIN_SCORE = 60
MIN_PROB = 0.40

# --- Señales "rojas" (baja confianza, no descartadas del todo) ---
RED_MIN_PROB = 0.40        # por debajo de esto, la señal se descarta directamente
RED_SIZE_FACTOR = 0.30     # tamaño de posición reducido para señales rojas
RED_MAX_PER_DAY = 2        # máximo de señales rojas ejecutadas por día (global)
RED_TP_CAP_R = 1.7         # TP capado a 1.7R en señales rojas

# --- Threshold dinámico ---
USE_DYNAMIC_THRESHOLD = True
DYNAMIC_THRESHOLD_LOOKBACK_TRADES = 10   # nº de resultados recientes que se recuerdan
DYNAMIC_THRESHOLD_STEP = 5               # cuánto sube/baja MIN_SCORE cada vez
DYNAMIC_THRESHOLD_MIN = 50
DYNAMIC_THRESHOLD_MAX = 75
DYNAMIC_LOSING_STREAK_TO_RAISE = 3       # N pérdidas seguidas -> sube el umbral
DYNAMIC_WINNING_STREAK_TO_LOWER = 3      # N ganancias seguidas -> baja el umbral

# --- Gestión de posiciones ---
MAX_CONCURRENT_TRADES = 2   # máximo de posiciones abiertas a la vez (todos los símbolos)
MAX_TRADES_PER_SYMBOL = 1   # máximo 1 posición por activo
COOLDOWN_HOURS = 4          # horas de espera en un símbolo tras cerrar un trade

# --- Riesgo / TP (reutiliza los presets de strategy.py) ---
RISK_PRESET = "Balanced"
USE_BREAK_EVEN = True

# --- Apalancamiento sugerido (según volatilidad ATR%) ---
LEVERAGE_MIN = 5
LEVERAGE_MAX = 20
LEV_ATR_PCT_LOW = 0.3       # ATR%/precio <= esto -> leverage máximo
LEV_ATR_PCT_HIGH = 2.0      # ATR%/precio >= esto -> leverage mínimo

# --- Gráfico de señal (imagen adjunta al mensaje de apertura, estilo V9) ---
CHART_LOOKBACK_CANDLES = 150   # nº de velas mostradas en el gráfico de cada señal

# --- Persistencia y ritmo ---
TRADE_LOG_MAX = 300           # nº máximo de operaciones cerradas que se guardan en el historial
STATE_FILE = "state_rodri.json"
CHECK_INTERVAL_SECONDS = 60   # solo aplica en modo bucle local (sin --once)

# --- Resumen diario ---
SEND_DAILY_SUMMARY = True
DAILY_SUMMARY_HOUR_UTC = 0

STRATEGY_LABEL = "Rodri v1.0 (Multi-Estrategia)"
