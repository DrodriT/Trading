"""
Config/config.py

Configuración centralizada del bot.

REGLA: Los parámetros de la ESTRATEGIA (sección PINE_*) son una copia
exacta de los `input.*()` del Pine Script original, con sus mismos
valores por defecto. NO deben cambiarse salvo que el Pine Script
original cambie. Si quieres experimentar con otros valores, hazlo
sabiendo que dejas de ser fiel al indicador de TradingView.

Los parámetros de INFRAESTRUCTURA (exchange, símbolo, telegram, etc.)
sí están pensados para configurarse vía variables de entorno, porque
no existen en Pine (TradingView no necesita saber el exchange o el
bot de Telegram).
"""

import os
from dataclasses import dataclass, field
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv es opcional; si no está instalado simplemente
    # se leen las variables de entorno del sistema (cron-job.org
    # normalmente las inyecta directamente).
    pass


def _env_str(name: str, default: str) -> str:
    """
    Como os.getenv(name, default), pero trata también la cadena vacía
    como "no definida" -> usa el default. Esto es importante porque
    en GitHub Actions, si una Repository Variable no existe,
    `${{ vars.ALGO }}` se resuelve como cadena vacía "" (no como
    variable ausente) — así que `docker run -e ALGO=""` SOBREESCRIBE
    silenciosamente el valor por defecto de Python con una cadena
    vacía en lugar de dejarlo caer al default. os.getenv(name, default)
    a secas NO protege contra esto porque la variable sí "existe"
    (solo que vacía). Usa _env_str en vez de os.getenv directo para
    cualquier config que pueda venir vacía desde CI/CD.
    """
    val = os.getenv(name)
    return val if val not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _env_list(name: str, default: list) -> list:
    """
    Lee una lista separada por comas desde una variable de entorno.
    Ej: SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT
    """
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return [s.strip() for s in val.split(",") if s.strip()]


# ══════════════════════════════════════════════════════════
# ⭐ MONEDAS A ANALIZAR — edita esta lista directamente aquí,
#    o defínela por entorno con SYMBOLS="BTC/USDT,ETH/USDT,SOL/USDT"
#    (formato ccxt: BASE/QUOTE, tal como lo lista tu exchange)
# ══════════════════════════════════════════════════════════
DEFAULT_SYMBOLS = [
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

# ══════════════════════════════════════════════════════════
# ⭐ TIMEFRAME — edita este valor directamente aquí, o defínelo
#    por entorno con TIMEFRAME="15m". Debe ser un timeframe
#    reconocido por tu exchange (ccxt): 1m, 5m, 15m, 30m, 1h,
#    2h, 4h, 6h, 8h, 12h, 1d, 1w...
# ══════════════════════════════════════════════════════════
DEFAULT_TIMEFRAME = "5m"

# ══════════════════════════════════════════════════════════
# ⭐ EXCHANGE — edita este valor directamente aquí (recomendado), o
#    defínelo por entorno con EXCHANGE_ID="bitget" (si defines la
#    variable de entorno, ESA tiene prioridad sobre este default).
#    Debe ser un id de exchange reconocido por ccxt: 'binance',
#    'bitget', 'okx', 'bybit', etc.
# ══════════════════════════════════════════════════════════
DEFAULT_EXCHANGE_ID = "bitget"
 
# ══════════════════════════════════════════════════════════
# INFRAESTRUCTURA (no existe en Pine — configurable por entorno)
# ══════════════════════════════════════════════════════════

@dataclass
class InfraConfig:
    # Exchange / datos de mercado (ccxt)
    EXCHANGE_ID: str = field(default_factory=lambda: _env_str("EXCHANGE_ID", DEFAULT_EXCHANGE_ID))

    # Lista de monedas a analizar en cada ejecución. El bot corre la
    # estrategia completa para CADA símbolo de esta lista, de forma
    # independiente (cada uno con su propio estado/dedupe).
    SYMBOLS: list = field(default_factory=lambda: _env_list("SYMBOLS", DEFAULT_SYMBOLS))

    TIMEFRAME: str = field(default_factory=lambda: _env_str("TIMEFRAME", DEFAULT_TIMEFRAME))  # timeframe base = "current TF" en Pine

    # Cuántas velas históricas se piden en cada ejecución.
    # Debe ser generoso: el Trail ratchet, el R² (regimeLen hasta 200),
    # el ADX, la Choppiness y el percentrank(100) necesitan warm-up,
    # y además el estado de la "posición activa" (SL/TP/BE) se
    # reconstruye desde cero en cada ejecución, así que cuantas más
    # velas de historia, más fiel es la réplica del estado real.
    LOOKBACK_BARS: int = _env_int("LOOKBACK_BARS", 1500)

    # Telegram
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: Optional[str] = os.getenv("TELEGRAM_CHAT_ID")

    # Estado (dedupe de señales)
    STATE_FILE: str = field(default_factory=lambda: _env_str("STATE_FILE", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "state", "state.json"
    )))

    # Diario de operaciones (para calcular % de acierto después)
    JOURNAL_FILE: str = field(default_factory=lambda: _env_str("JOURNAL_FILE", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "state", "trades.json"
    )))

    # Debug
    DEBUG: bool = _env_bool("DEBUG", False)

    # Nombre para mostrar en el mensaje de Telegram
    STRATEGY_NAME: str = "Synapse Trail Pro [WillyAlgoTrader]"


INFRA = InfraConfig()


# ══════════════════════════════════════════════════════════
# ESTRATEGIA — copia exacta de los inputs de Pine (sección 3)
# ══════════════════════════════════════════════════════════

@dataclass
class PineConfig:
    # ── Constantes (sección 2 del Pine) ────────────────────
    GRADE_A_THRESHOLD: int = 75
    GRADE_B_THRESHOLD: int = 55

    REGIME_TRENDING: int = 60
    REGIME_CHOPPY: int = 35

    ENTRY_BAR_HOLD: int = 1  # same-bar guard

    # ── Main ────────────────────────────────────────────────
    atrLenInput: int = 21
    baseMultInput: float = 1.618
    trailLenInput: int = 21
    useAdaptiveMultInput: bool = False
    useRatchetInput: bool = True

    # ── Filters ─────────────────────────────────────────────
    minQualityInput: int = 0
    skipChoppyInput: bool = False
    useHtfFilterInput: bool = True
    htfTfInput: str = ""          # "" = auto 4x
    useVolumeFilterInput: bool = False
    volMultInput: float = 1.3

    # ── Market Regime ───────────────────────────────────────
    adxLenInput: int = 14
    choppinessLenInput: int = 14
    regimeLenInput: int = 50

    # ── Risk Management ─────────────────────────────────────
    riskPresetInput: str = "Balanced"  # Conservative|Balanced|Aggressive|Scalping|Custom
    slMultInput: float = 1.5
    tp1MultInput: float = 1.0
    tp2MultInput: float = 2.0
    tp3MultInput: float = 3.0
    useBreakEvenInput: bool = True

    # ── Alerts (equivalentes -> qué se manda a Telegram) ────
    # NOTA: alertTpHitInput=False es el valor por defecto del Pine
    # original, pero aquí se activa a True porque el usuario quiere
    # ser avisado también de cada TP y de cada activación de Break-Even.
    # Esto es una decisión de NOTIFICACIÓN (capa Telegram), no cambia
    # ninguna condición de la estrategia ni de las señales BUY/SELL.
    alertTpHitInput: bool = True
    alertSlHitInput: bool = True
    alertFlipInput: bool = True

    def resolve_risk_preset(self):
        """Replica exactamente los ternarios de la sección 10 del Pine."""
        preset = self.riskPresetInput
        if preset == "Conservative":
            return 2.5, 1.0, 2.0, 4.0
        if preset == "Aggressive":
            return 1.0, 1.5, 2.5, 4.0
        if preset == "Scalping":
            return 0.8, 0.8, 1.5, 2.0
        if preset == "Custom":
            return self.slMultInput, self.tp1MultInput, self.tp2MultInput, self.tp3MultInput
        # "Balanced" (default / fallback, igual que el Pine)
        return 1.5, 1.0, 2.0, 3.0


PINE = PineConfig()
