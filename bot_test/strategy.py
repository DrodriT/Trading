"""
Lógica ESPECÍFICA de la estrategia: qué combinación de indicadores dispara
una señal, y cómo se calcula el score de confluencia ponderado.

Usa las funciones genéricas de indicators.py, pero decide la parte de
"cuándo es una señal válida" y "cómo de buena es", que indicators.py no
sabe ni debe saber.

=== ESTRATEGIA (continuación de tendencia, no rebote) ===
LONG:  cierre(15m) > EMA200(15m)  Y  Estocástico en SOBRECOMPRA  Y  cierre(1h) > EMA200(1h)
SHORT: cierre(15m) < EMA200(15m)  Y  Estocástico en SOBREVENTA   Y  cierre(1h) < EMA200(1h)

A diferencia de la versión anterior, esto NO exige un cruce del Estocástico:
basta con que esté en la zona, en el momento de la vela cerrada. Es una
estrategia de "comprar fuerza" (el precio ya está por encima de la media
larga y el momentum está fuerte), no de "comprar el rebote".
"""
import pandas as pd

from indicators import add_ema, add_stochastic, add_adx, add_macd, add_rsi, add_volume_ratio, add_ssl_channel


def compute_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                        k_period: int, smooth: int, d_period: int,
                        adx_period: int = 14, macd_fast: int = 12, macd_slow: int = 26,
                        macd_signal: int = 9, rsi_period: int = 14,
                        volume_ma_period: int = 20, ssl_period: int = 10) -> pd.DataFrame:
    """
    Calcula todos los indicadores que esta estrategia necesita:
    EMA rápida (referencia para entradas), EMA lenta (filtro de tendencia),
    Estocástico (disparador), y ADX/MACD/RSI/Volumen/SSL (para el score).
    """
    df = add_ema(df, ema_fast, f"EMA{ema_fast}")
    df = add_ema(df, ema_slow, f"EMA{ema_slow}")
    df = add_stochastic(df, k_period, smooth, d_period)
    df = add_adx(df, adx_period)
    df = add_macd(df, macd_fast, macd_slow, macd_signal)
    df = add_rsi(df, rsi_period)
    df = add_volume_ratio(df, volume_ma_period)
    df = add_ssl_channel(df, ssl_period)
    return df


def detect_signals(df: pd.DataFrame, ema_slow: int, oversold: int, overbought: int,
                    mtf_confirm_bullish=None, mtf_confirm_bearish=None, mtf_label: str = ""):
    """
    Analiza las DOS últimas velas cerradas (estrategia de "comprar el pullback
    en tendencia", no de continuación por ruptura):

      - ALCISTA: cierre > EMA{ema_slow} (tendencia alcista)  Y  %K cruza por
                 ENCIMA de %D estando AMBOS en zona de SOBREVENTA (%K y %D <
                 oversold) — es decir, el precio hace un pullback dentro de
                 una tendencia alcista y el Estocástico rebota desde abajo.
      - BAJISTA: cierre < EMA{ema_slow} (tendencia bajista)  Y  %K cruza por
                 DEBAJO de %D estando AMBOS en zona de SOBRECOMPRA (%K y %D >
                 overbought) — el precio hace un rebote dentro de una
                 tendencia bajista y el Estocástico gira desde arriba.

    La EMA{ema_slow} marca la tendencia de fondo; el cruce del Estocástico en
    la zona opuesta a la dirección de la señal es el disparador del pullback.

    Con confirmación multi-timeframe obligatoria si se pasa (mtf_confirm_bullish/
    bearish): la tendencia en el timeframe de confirmación (ej. 1h) debe ir en
    la misma dirección.

    Devuelve una lista de tuplas (tipo, mensaje).
    """
    if len(df) < ema_slow + 2:
        return []

    prev, last = df.iloc[-2], df.iloc[-1]
    slow_col = f"EMA{ema_slow}"

    price_above = last["close"] > last[slow_col]
    price_below = last["close"] < last[slow_col]

    cross_up_in_oversold = (
        prev["%K"] <= prev["%D"] and last["%K"] > last["%D"]
        and last["%K"] < oversold and last["%D"] < oversold
    )
    cross_down_in_overbought = (
        prev["%K"] >= prev["%D"] and last["%K"] < last["%D"]
        and last["%K"] > overbought and last["%D"] > overbought
    )

    bullish_ok = price_above and cross_up_in_oversold
    bearish_ok = price_below and cross_down_in_overbought

    if bullish_ok and mtf_confirm_bullish is not None and not mtf_confirm_bullish:
        bullish_ok = False
    if bearish_ok and mtf_confirm_bearish is not None and not mtf_confirm_bearish:
        bearish_ok = False

    signals = []

    if bullish_ok:
        msg = (f"Cierre por ENCIMA de EMA{ema_slow} (tendencia alcista) y %K cruza por "
               f"ENCIMA de %D dentro de SOBREVENTA (%K={last['%K']:.1f}, %D={last['%D']:.1f}, "
               f"umbral={oversold}) — pullback en tendencia")
        if mtf_confirm_bullish is not None:
            msg += f" | confirmado: precio también por ENCIMA de EMA{ema_slow} en {mtf_label}"
        signals.append(("ALCISTA", msg))

    if bearish_ok:
        msg = (f"Cierre por DEBAJO de EMA{ema_slow} (tendencia bajista) y %K cruza por "
               f"DEBAJO de %D dentro de SOBRECOMPRA (%K={last['%K']:.1f}, %D={last['%D']:.1f}, "
               f"umbral={overbought}) — rebote en tendencia")
        if mtf_confirm_bearish is not None:
            msg += f" | confirmado: precio también por DEBAJO de EMA{ema_slow} en {mtf_label}"
        signals.append(("BAJISTA", msg))

    return signals


def build_score(df: pd.DataFrame, signal_type: str, trend_strength_1h_pct: float,
                weights: dict = None):
    """
    Score de 0 a 100 según 6 indicadores ponderados:

        ADX                       20 pts  (fuerza de la tendencia + dirección +DI/-DI)
        MACD                      15 pts  (¿confirma la dirección de la señal?)
        RSI                       15 pts  (momentum a favor de la dirección)
        Volumen                   10 pts  (¿hay más participación de lo normal?)
        Fuerza tendencia 1H       15 pts  (cuánto se aleja el precio de su EMA200 en 1h)
        SSL                       25 pts  (canal SSL alineado con la dirección de la señal)
        ------------------------------
        Total                    100 pts

    Cada componente aporta 0 si NO confirma la dirección de la señal, y una
    puntuación proporcional (hasta el máximo de su peso) cuanto más fuerte
    sea la confirmación. Devuelve (score, desglose, semaforo).
    """
    w = weights or {"adx": 20, "macd": 15, "rsi": 15, "volumen": 10, "tendencia_1h": 15, "ssl": 25}
    last = df.iloc[-1]
    is_long = signal_type == "ALCISTA"
    breakdown = {}

    # --- ADX (fuerza + dirección) ---
    adx_val = last["ADX"]
    plus_di, minus_di = last["ADX_plusDI"], last["ADX_minusDI"]
    direction_aligned = (plus_di > minus_di) if is_long else (minus_di > plus_di)
    if direction_aligned and pd.notna(adx_val):
        pts = min(w["adx"], (adx_val / 50) * w["adx"])
    else:
        pts = 0
    breakdown["ADX"] = round(pts, 1)

    # --- MACD (¿confirma dirección?) ---
    macd_aligned = (last["MACD"] > last["MACD_signal"]) if is_long else (last["MACD"] < last["MACD_signal"])
    if macd_aligned:
        hist_pct = abs(last["MACD_hist"]) / last["close"] * 100
        pts = min(w["macd"], (hist_pct / 0.5) * w["macd"])
    else:
        pts = 0
    breakdown["MACD"] = round(pts, 1)

    # --- RSI (momentum a favor) ---
    rsi_val = last["RSI"]
    if is_long:
        pts = min(w["rsi"], max(0, (rsi_val - 50) / 30 * w["rsi"]))
    else:
        pts = min(w["rsi"], max(0, (50 - rsi_val) / 30 * w["rsi"]))
    breakdown["RSI"] = round(pts, 1)

    # --- Volumen (participación por encima de lo normal) ---
    vol_ratio = last["VOL_RATIO"]
    if pd.notna(vol_ratio):
        pts = min(w["volumen"], max(0, (vol_ratio - 1) * w["volumen"]))
    else:
        pts = 0
    breakdown["Volumen"] = round(pts, 1)

    # --- Fuerza de la tendencia en 1H ---
    pts = min(w["tendencia_1h"], max(0, trend_strength_1h_pct / 4 * w["tendencia_1h"]))
    breakdown["Tendencia 1H"] = round(pts, 1)

    # --- SSL Channel (alineación de tendencia) ---
    ssl_up, ssl_down = last["SSL_up"], last["SSL_down"]
    ssl_aligned = (ssl_up > ssl_down) if is_long else (ssl_up < ssl_down)
    if ssl_aligned and pd.notna(ssl_up) and pd.notna(ssl_down):
        ssl_distance_pct = abs(ssl_up - ssl_down) / last["close"] * 100
        pts = min(w["ssl"], (ssl_distance_pct / 2) * w["ssl"])
    else:
        pts = 0
    breakdown["SSL"] = round(pts, 1)

    score = round(min(100, sum(breakdown.values())))

    if score >= 70:
        semaforo = "🟢 VERDE"
    elif score >= 40:
        semaforo = "🟡 AMARILLO"
    else:
        semaforo = "🔴 ROJO"

    return score, breakdown, semaforo


def build_risk_management(df: pd.DataFrame, signal_type: str, entry_price: float,
                           atr_col: str = "ATR", sl_atr_mult: float = 1.5,
                           risk_target_pct: float = 10.0,
                           rr_ratios=(1.0, 1.7, 2.5),
                           max_leverage: float = 20.0):
    """
    Calcula Stop Loss, Take Profits escalonados (con ratio riesgo/recompensa)
    y un apalancamiento sugerido, a partir del ATR (volatilidad real reciente).
    """
    last_atr = df.iloc[-1][atr_col]
    is_long = signal_type == "ALCISTA"

    if is_long:
        sl = entry_price - sl_atr_mult * last_atr
    else:
        sl = entry_price + sl_atr_mult * last_atr

    risk_distance = abs(entry_price - sl)
    sl_pct = (risk_distance / entry_price) * 100

    leverage_suggested = min(risk_target_pct / sl_pct, max_leverage) if sl_pct > 0 else None

    tps = []
    for i, rr in enumerate(rr_ratios, start=1):
        tp_price = entry_price + rr * risk_distance if is_long else entry_price - rr * risk_distance
        tp_pct = (abs(tp_price - entry_price) / entry_price) * 100
        tps.append({"label": f"TP{i}", "price": tp_price, "pct": tp_pct, "rr": rr})

    return {
        "sl": sl,
        "sl_pct": sl_pct,
        "leverage_suggested": leverage_suggested,
        "tps": tps,
    }


def build_limit_entries(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                         signal_type: str, swing_lookback: int = 50):
    """
    Calcula de 2 a 4 niveles de entrada escalonados (limit orders):
      Entry 1 -> precio actual
      Entry 2 -> retest de EMA{ema_fast}
      Entry 3 -> Fibonacci 0.618 del swing reciente
      Entry 4 -> EMA{ema_slow} (invalidación)

    Solo se incluyen los niveles con sentido direccional; se renumeran sin
    huecos según lo que realmente se muestra.
    """
    last = df.iloc[-1]
    price = last["close"]
    ema_fast_val = last[f"EMA{ema_fast}"]
    ema_slow_val = last[f"EMA{ema_slow}"]

    window = df.tail(swing_lookback)
    swing_high = window["high"].max()
    swing_low = window["low"].min()
    diff = swing_high - swing_low

    entries = []
    is_long = signal_type == "ALCISTA"

    entries.append({"price": price, "basis": "precio actual"})

    if is_long:
        fib_618 = swing_high - diff * 0.618
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast}"),
            (fib_618, "Fibonacci 0.618 del swing reciente"),
            (ema_slow_val, f"soporte mayor EMA{ema_slow}, invalidación"),
        ]
        for lvl, basis in candidates:
            if lvl < entries[-1]["price"]:
                entries.append({"price": lvl, "basis": basis})
    else:
        fib_618 = swing_low + diff * 0.618
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast}"),
            (fib_618, "Fibonacci 0.618 del swing reciente"),
            (ema_slow_val, f"resistencia mayor EMA{ema_slow}, invalidación"),
        ]
        for lvl, basis in candidates:
            if lvl > entries[-1]["price"]:
                entries.append({"price": lvl, "basis": basis})

    for i, e in enumerate(entries, start=1):
        e["label"] = f"Entry {i} ({e['basis']})"

    return entries
