"""
NUEVA ESTRATEGIA: BREAKOUT CON CONFIRMACIÓN DE FUERZA

LONG:  Precio > EMA200 + Cruce EMA13 + RSI > 55 + Volumen > 1.5x + ADX > 25
SHORT: Precio < EMA200 + Cruce EMA13 + RSI < 45 + Volumen > 1.5x + ADX > 25

Esta estrategia captura movimientos de continuación con confirmación
de volumen y momentum, filtrando los falsos breakouts.
"""
import pandas as pd
import numpy as np

from indicators import (
    add_ema, add_adx, add_macd, add_rsi, 
    add_volume_ratio, add_ssl_channel
)


def compute_indicators(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                        adx_period: int = 14, macd_fast: int = 12, 
                        macd_slow: int = 26, macd_signal: int = 9,
                        rsi_period: int = 14, volume_ma_period: int = 20,
                        ssl_period: int = 10) -> pd.DataFrame:
    """
    Calcula todos los indicadores necesarios para la estrategia.
    """
    df = add_ema(df, ema_fast, f"EMA{ema_fast}")
    df = add_ema(df, ema_slow, f"EMA{ema_slow}")
    df = add_adx(df, adx_period)
    df = add_macd(df, macd_fast, macd_slow, macd_signal)
    df = add_rsi(df, rsi_period)
    df = add_volume_ratio(df, volume_ma_period)
    df = add_ssl_channel(df, ssl_period)
    return df


def detect_signals(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                    rsi_min_long: float = 55, rsi_max_short: float = 45,
                    volume_threshold: float = 1.5, adx_threshold: float = 25,
                    mtf_confirm_bullish=None, mtf_confirm_bearish=None, 
                    mtf_label: str = ""):
    """
    Detecta señales de BREAKOUT con confirmación de fuerza.
    
    LONG: 
      - Tendencia: close > EMA200
      - Aceleración: close > EMA13 (precio por encima de la rápida)
      - Cruce confirmado: EMA13 cruza por ENCIMA de precio (cruce de cierre)
      - Momentum: RSI > rsi_min_long
      - Volumen: VOL_RATIO > volume_threshold
      - Fuerza: ADX > adx_threshold y +DI > -DI
      - Estructura: SSL_up > SSL_down
    
    SHORT:
      - Tendencia: close < EMA200
      - Aceleración: close < EMA13 (precio por debajo de la rápida)
      - Cruce confirmado: EMA13 cruza por DEBAJO de precio
      - Momentum: RSI < rsi_max_short
      - Volumen: VOL_RATIO > volume_threshold
      - Fuerza: ADX > adx_threshold y -DI > +DI
      - Estructura: SSL_up < SSL_down
    """
    if len(df) < ema_slow + 50:
        return []
    
    prev, last = df.iloc[-2], df.iloc[-1]
    slow_col = f"EMA{ema_slow}"
    fast_col = f"EMA{ema_fast}"
    
    signals = []
    
    # --- CONDICIONES LONG ---
    price_above_ema200 = last["close"] > last[slow_col]
    price_above_ema13 = last["close"] > last[fast_col]
    
    # Cruce confirmado: precio cruza por encima de EMA13
    ema13_cross_up = prev["close"] <= prev[fast_col] and last["close"] > last[fast_col]
    
    rsi_ok = last["RSI"] > rsi_min_long
    volume_ok = pd.notna(last["VOL_RATIO"]) and last["VOL_RATIO"] > volume_threshold
    adx_ok = last["ADX"] > adx_threshold and last["ADX_plusDI"] > last["ADX_minusDI"]
    ssl_ok = last["SSL_up"] > last["SSL_down"]
    
    # Todas las condiciones deben cumplirse
    bullish_ok = (
        price_above_ema200 and 
        price_above_ema13 and 
        ema13_cross_up and
        rsi_ok and 
        volume_ok and 
        adx_ok and 
        ssl_ok
    )
    
    # Confirmación multi-timeframe
    if bullish_ok and mtf_confirm_bullish is not None:
        bullish_ok = mtf_confirm_bullish
    
    if bullish_ok:
        msg = (
            f"🚀 BREAKOUT ALCISTA CONFIRMADO\n"
            f"  • Precio por ENCIMA de EMA{ema_slow} (tendencia alcista)\n"
            f"  • Cruce de EMA{ema_fast} al alza\n"
            f"  • RSI={last['RSI']:.1f} (> {rsi_min_long})\n"
            f"  • Volumen {last['VOL_RATIO']:.2f}x (> {volume_threshold}x)\n"
            f"  • ADX={last['ADX']:.1f} (> {adx_threshold}) | +DI={last['ADX_plusDI']:.1f} > -DI={last['ADX_minusDI']:.1f}\n"
            f"  • SSL: UP={last['SSL_up']:.4f} > DOWN={last['SSL_down']:.4f}"
        )
        if mtf_confirm_bullish is not None:
            msg += f"\n  • Confirmado en {mtf_label}"
        signals.append(("ALCISTA", msg))
    
    # --- CONDICIONES SHORT ---
    price_below_ema200 = last["close"] < last[slow_col]
    price_below_ema13 = last["close"] < last[fast_col]
    
    # Cruce confirmado: precio cruza por debajo de EMA13
    ema13_cross_down = prev["close"] >= prev[fast_col] and last["close"] < last[fast_col]
    
    rsi_ok = last["RSI"] < rsi_max_short
    volume_ok = pd.notna(last["VOL_RATIO"]) and last["VOL_RATIO"] > volume_threshold
    adx_ok = last["ADX"] > adx_threshold and last["ADX_minusDI"] > last["ADX_plusDI"]
    ssl_ok = last["SSL_up"] < last["SSL_down"]
    
    bearish_ok = (
        price_below_ema200 and 
        price_below_ema13 and 
        ema13_cross_down and
        rsi_ok and 
        volume_ok and 
        adx_ok and 
        ssl_ok
    )
    
    if bearish_ok and mtf_confirm_bearish is not None:
        bearish_ok = mtf_confirm_bearish
    
    if bearish_ok:
        msg = (
            f"🚨 BREAKOUT BAJISTA CONFIRMADO\n"
            f"  • Precio por DEBAJO de EMA{ema_slow} (tendencia bajista)\n"
            f"  • Cruce de EMA{ema_fast} a la baja\n"
            f"  • RSI={last['RSI']:.1f} (< {rsi_max_short})\n"
            f"  • Volumen {last['VOL_RATIO']:.2f}x (> {volume_threshold}x)\n"
            f"  • ADX={last['ADX']:.1f} (> {adx_threshold}) | -DI={last['ADX_minusDI']:.1f} > +DI={last['ADX_plusDI']:.1f}\n"
            f"  • SSL: UP={last['SSL_up']:.4f} < DOWN={last['SSL_down']:.4f}"
        )
        if mtf_confirm_bearish is not None:
            msg += f"\n  • Confirmado en {mtf_label}"
        signals.append(("BAJISTA", msg))
    
    return signals


def build_score(df: pd.DataFrame, signal_type: str, trend_strength_1h_pct: float,
                weights: dict = None):
    """
    Score de 0 a 100 ponderado por 6 factores.
    PESOS ACTUALIZADOS para la nueva estrategia.
    """
    w = weights or {
        "adx": 25,          # Más peso a la fuerza de la tendencia
        "macd": 20,         # Momentum
        "rsi": 15,          # Momento del precio
        "volumen": 20,      # Participación real
        "tendencia_1h": 10, # Confirmación en mayor timeframe
        "ssl": 10,          # Estructura
    }
    
    last = df.iloc[-1]
    is_long = signal_type == "ALCISTA"
    breakdown = {}
    
    # --- ADX (25 pts) ---
    adx_val = last["ADX"]
    plus_di, minus_di = last["ADX_plusDI"], last["ADX_minusDI"]
    direction_aligned = (plus_di > minus_di) if is_long else (minus_di > plus_di)
    
    if direction_aligned and pd.notna(adx_val):
        # ADX 25 = 50% del peso, ADX 50+ = 100%
        pts = min(w["adx"], max(0, (adx_val - 20) / 30 * w["adx"]))
    else:
        pts = 0
    breakdown["ADX"] = round(pts, 1)
    
    # --- MACD (20 pts) ---
    macd_aligned = (last["MACD"] > last["MACD_signal"]) if is_long else (last["MACD"] < last["MACD_signal"])
    if macd_aligned:
        # Distancia del histograma como % del precio
        hist_pct = abs(last["MACD_hist"]) / last["close"] * 100
        pts = min(w["macd"], (hist_pct / 0.3) * w["macd"])
    else:
        pts = 0
    breakdown["MACD"] = round(pts, 1)
    
    # --- RSI (15 pts) ---
    rsi_val = last["RSI"]
    if is_long:
        # RSI 55-70 = 50-100% del peso
        pts = min(w["rsi"], max(0, (rsi_val - 50) / 20 * w["rsi"]))
    else:
        # RSI 30-45 = 50-100% del peso
        pts = min(w["rsi"], max(0, (50 - rsi_val) / 20 * w["rsi"]))
    breakdown["RSI"] = round(pts, 1)
    
    # --- Volumen (20 pts) ---
    vol_ratio = last["VOL_RATIO"]
    if pd.notna(vol_ratio):
        # 1.5x = 50%, 3x+ = 100%
        pts = min(w["volumen"], max(0, (vol_ratio - 1) / 2 * w["volumen"]))
    else:
        pts = 0
    breakdown["Volumen"] = round(pts, 1)
    
    # --- Tendencia 1H (10 pts) ---
    # Distancia a EMA200 en el timeframe superior
    pts = min(w["tendencia_1h"], max(0, trend_strength_1h_pct / 3 * w["tendencia_1h"]))
    breakdown["Tendencia 1H"] = round(pts, 1)
    
    # --- SSL (10 pts) ---
    ssl_up, ssl_down = last["SSL_up"], last["SSL_down"]
    ssl_aligned = (ssl_up > ssl_down) if is_long else (ssl_up < ssl_down)
    if ssl_aligned and pd.notna(ssl_up) and pd.notna(ssl_down):
        # Distancia SSL como % del precio
        ssl_distance_pct = abs(ssl_up - ssl_down) / last["close"] * 100
        pts = min(w["ssl"], (ssl_distance_pct / 1.5) * w["ssl"])
    else:
        pts = 0
    breakdown["SSL"] = round(pts, 1)
    
    score = round(min(100, sum(breakdown.values())))
    
    # Umbrales más exigentes para una estrategia de breakouts
    if score >= 75:
        semaforo = "🟢 VERDE (Fuerte)"
    elif score >= 55:
        semaforo = "🟡 AMARILLO (Moderado)"
    else:
        semaforo = "🔴 ROJO (Débil)"
    
    return score, breakdown, semaforo


# Las funciones build_risk_management y build_limit_entries se mantienen igual
# Solo necesitas actualizar la lógica de entradas para la nueva estrategia

def build_limit_entries(df: pd.DataFrame, ema_fast: int, ema_slow: int,
                         signal_type: str, swing_lookback: int = 50):
    """
    Niveles de entrada para la estrategia de breakouts.
    Ahora incluye el nivel de ruptura como punto de entrada principal.
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
    
    # Entrada principal: precio actual (breakout)
    entries.append({"price": price, "basis": "breakout confirmado"})
    
    if is_long:
        # Niveles de soporte para añadir en pullback
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast} (soporte dinámico)"),
            (price - diff * 0.382, "retroceso 0.382 del swing"),
            (ema_slow_val, f"soporte mayor EMA{ema_slow} (invalidación)"),
        ]
        for lvl, basis in candidates:
            if lvl < entries[-1]["price"] and lvl > ema_slow_val:
                entries.append({"price": lvl, "basis": basis})
    else:
        # Niveles de resistencia para añadir en rebote
        candidates = [
            (ema_fast_val, f"retest EMA{ema_fast} (resistencia dinámica)"),
            (price + diff * 0.382, "retroceso 0.382 del swing"),
            (ema_slow_val, f"resistencia mayor EMA{ema_slow} (invalidación)"),
        ]
        for lvl, basis in candidates:
            if lvl > entries[-1]["price"] and lvl < ema_slow_val:
                entries.append({"price": lvl, "basis": basis})
    
    # Limitar a máximo 4 entradas y renumerar
    entries = entries[:4]
    for i, e in enumerate(entries, start=1):
        e["label"] = f"Entry {i} ({e['basis']})"
    
    return entries