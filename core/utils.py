"""
Utilidades compartidas — Rodri v1.0

Dos grupos de funciones, antes duplicadas o "enterradas" en otros
archivos:

1. Formato de mensajes (display_symbol, md_escape, pct_from_entry):
   antes vivían dentro de main.py/bot_rodri.py, y display_symbol estaba
   además duplicada literalmente en chart_rodri.py/charting.py. Ahora
   viven aquí una sola vez.

2. Guardianes repetidos en las estrategias (is_atr_valid,
   safe_vol_ratio): el patrón
       atr = last["ATR"]
       if pd.isna(atr) or atr == 0:
           return None
   se repetía igual en 4 de los 6 detectores (SMC_REVERSAL,
   LIQUIDITY_GRAB, BREAKOUT, VP_MEAN_REVERT), y el patrón
       vol_ratio = last["VOL_RATIO"] if pd.notna(last["VOL_RATIO"]) else 1.0
   se repetía en SMC_REVERSAL (x2) y BREAKOUT. Sin cambiar ningún
   criterio, solo se centraliza la comprobación.
"""
import pandas as pd


# ─────────────────────────────────────────────────────────
# Formato de mensajes
# ─────────────────────────────────────────────────────────

def display_symbol(symbol: str) -> str:
    """Convierte 'BTC/USDT:USDT' en 'BTCUSDT' para mostrar en mensajes
    y en el título de los gráficos."""
    return symbol.split(":")[0].replace("/", "")


def md_escape(text: str) -> str:
    """
    Escapa los caracteres especiales del Markdown "legacy" de Telegram
    (_ * ` [ ). Es imprescindible para los nombres de estrategia
    (SMC_REVERSAL, TREND_PULLBACK, RSI_DIVERGENCE, LIQUIDITY_GRAB...): al
    llevar un número impar de "_", Telegram no puede emparejar la cursiva
    y devuelve un error 400 "can't parse entities" — y como send_telegram
    solo registra el error sin lanzar excepción, el mensaje se pierde en
    silencio (nunca llega, aunque el bot siga funcionando con normalidad).
    """
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def pct_from_entry(entry: float, level: float) -> str:
    """Formatea el porcentaje de un nivel (SL/TP) respecto al precio de
    entrada, listo para insertar en un mensaje de Telegram."""
    if not entry:
        return ""
    pct = (level - entry) / entry * 100.0
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


# ─────────────────────────────────────────────────────────
# Guardianes repetidos en las estrategias
# ─────────────────────────────────────────────────────────

def is_atr_valid(atr) -> bool:
    """True si el ATR es un número utilizable (no NaN, no cero). Mismo
    criterio que se repetía inline en 4 de los 6 detectores."""
    return not (pd.isna(atr) or atr == 0)


def safe_vol_ratio(vol_ratio, default: float = 1.0) -> float:
    """Devuelve vol_ratio si es un número válido, o 'default' si es NaN.
    Mismo criterio que se repetía inline en SMC_REVERSAL y BREAKOUT."""
    return vol_ratio if pd.notna(vol_ratio) else default
