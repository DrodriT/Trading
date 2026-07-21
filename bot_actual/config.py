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

# --- Tipo de mercado ---
# "spot" -> mercado al contado (compra/venta real del activo)
# "swap" -> futuros perpetuos (perpetuals) con margen USDT
MARKET_TYPE = "swap"

# --- Lista de criptos a vigilar ---
# Formato ccxt para PERPETUOS con margen USDT: "BASE/USDT:USDT"
# (el ":USDT" final indica a ccxt que es el contrato perpetuo, no el par spot).
# Si algún día quieres volver a spot, sería "BASE/USDT" y MARKET_TYPE = "spot".
SYMBOLS = [
   "BTC/USDT:USDT",
   "ETH/USDT:USDT",
   # añade aquí tus monedas, ej:
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
   "AAVE/USDT:USDDT",
]
# --- Timeframe ---
# Valores típicos de ccxt: "5m", "15m", "1h", "4h", "1d"
TIMEFRAME = "15m"
# --- Confirmación multi-timeframe ---
# Si está activado, además de cumplirse la señal en TIMEFRAME, se exige que en
# CONFIRM_TIMEFRAME el precio esté también por encima (señal ALCISTA) o por
# debajo (señal BAJISTA) de su propia EMA200. Si TIMEFRAME ya es igual a
# CONFIRM_TIMEFRAME, la confirmación no aporta nada extra (son los mismos datos).
ENABLE_MTF_CONFIRMATION = True
CONFIRM_TIMEFRAME = "1h"
 
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

# --- Gestión de riesgo (SL / TP / apalancamiento sugerido) ---
ATR_PERIOD = 14           # periodo para calcular el ATR (volatilidad reciente)
SL_ATR_MULT = 1.5         # el SL se coloca a 1.5x el ATR de distancia de la entrada
RISK_TARGET_PCT = 10.0    # % de riesgo objetivo sobre el margen para sugerir apalancamiento
TP_RR_RATIOS = [1.0, 1.7, 2.5]   # ratios riesgo/recompensa para TP1, TP2, TP3
MAX_LEVERAGE = 20.0       # tope de apalancamiento sugerido, por seguridad

# --- Cooldown por activo/dirección ---
# Evita recibir avisos del mismo símbolo+dirección demasiado seguido, aunque
# cada vela nueva cumpla técnicamente la condición otra vez.
COOLDOWN_HOURS = 4

# --- Etiqueta para identificar los mensajes de Telegram de esta versión ---
STRATEGY_LABEL = "ACTUAL (stochastico+ema200)"
