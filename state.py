"""
Persistencia de estado — Rodri v1.0

Extraído de main.py (antes bot_rodri.py) sin cambios de lógica de negocio.

Único cambio de comportamiento en esta fase (aprobado explícitamente):
las claves sueltas "{symbol}_last_processed_candle" que antes vivían
directamente en la raíz de state.json se anidan ahora bajo
state["last_processed_candle"][symbol]. La migración es automática y
retrocompatible: al cargar un state.json con el formato antiguo, se leen
esas claves sueltas una sola vez, se anidan, y se eliminan — a partir de
ahí el archivo se guarda siempre en el formato nuevo. Ningún otro dato
(positions, cooldowns, stats, trade_log...) se toca.
"""
import json
import os
from datetime import datetime, timedelta

import config


# ══════════════════════════════════════════════════════════
# Estado por defecto / carga / guardado
# ══════════════════════════════════════════════════════════

def default_state():
    return {
        "positions": {},
        "cooldowns": {},
        "red_signals_today": {"date": None, "count": 0},
        "recent_results": [],
        "dynamic_min_score": config.MIN_SCORE,
        "trade_log": [],
        "stats": {},
        "last_daily_summary_date": None,
        "startup_notified": False,
        "last_processed_candle": {},
    }


def _migrate_last_processed_candle(state: dict) -> dict:
    """
    Compatibilidad hacia atrás: migra las claves sueltas
    "{symbol}_last_processed_candle" (formato antiguo, una por símbolo en
    la raíz del estado) al diccionario anidado
    state["last_processed_candle"][symbol] (formato nuevo). Se ejecuta en
    cada load_state(); si no encuentra claves del formato antiguo, no
    hace nada. Es idempotente: una vez migrado, las siguientes cargas no
    encuentran claves sueltas y no repiten el trabajo.
    """
    nested = state.setdefault("last_processed_candle", {})
    stale_keys = [k for k in state.keys() if k.endswith("_last_processed_candle")]
    for key in stale_keys:
        symbol = key[: -len("_last_processed_candle")]
        nested[symbol] = state.pop(key)
    return state


def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            state = json.load(f)
        for k, v in default_state().items():
            state.setdefault(k, v)
        _migrate_last_processed_candle(state)
        return state
    return default_state()


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_stats(state):
    stats = state.setdefault("stats", {})
    defaults = {
        "total_signals": 0, "normal_signals": 0, "red_signals": 0,
        "long_signals": 0, "short_signals": 0,
        "sl_hits": 0, "tp1_hits": 0, "tp2_hits": 0, "tp3_hits": 0,
        "flips": 0, "wins": 0, "losses": 0, "be_saves": 0, "r_sum": 0.0,
    }
    for k, v in defaults.items():
        stats.setdefault(k, v)
    return stats


# ══════════════════════════════════════════════════════════
# Última vela procesada por símbolo (formato nuevo, anidado)
# ══════════════════════════════════════════════════════════

def get_last_processed_candle(state, symbol):
    """Devuelve el timestamp (ISO) de la última vela de 5m ya procesada
    para 'symbol', o None si aún no se procesó ninguna."""
    return state.setdefault("last_processed_candle", {}).get(symbol)


def set_last_processed_candle(state, symbol, candle_time):
    """Registra 'candle_time' como la última vela de 5m procesada para
    'symbol'."""
    state.setdefault("last_processed_candle", {})[symbol] = candle_time


# ══════════════════════════════════════════════════════════
# Threshold dinámico
# ══════════════════════════════════════════════════════════

def update_dynamic_threshold(state):
    if not config.USE_DYNAMIC_THRESHOLD:
        state["dynamic_min_score"] = config.MIN_SCORE
        return

    current = state.get("dynamic_min_score", config.MIN_SCORE)
    results = state.get("recent_results", [])

    if len(results) >= config.DYNAMIC_LOSING_STREAK_TO_RAISE:
        if all(r is False for r in results[-config.DYNAMIC_LOSING_STREAK_TO_RAISE:]):
            current = min(config.DYNAMIC_THRESHOLD_MAX, current + config.DYNAMIC_THRESHOLD_STEP)

    if len(results) >= config.DYNAMIC_WINNING_STREAK_TO_LOWER:
        if all(r is True for r in results[-config.DYNAMIC_WINNING_STREAK_TO_LOWER:]):
            current = max(config.DYNAMIC_THRESHOLD_MIN, current - config.DYNAMIC_THRESHOLD_STEP)

    state["dynamic_min_score"] = current


def register_result(state, is_win: bool):
    results = state.setdefault("recent_results", [])
    results.append(bool(is_win))
    if len(results) > config.DYNAMIC_THRESHOLD_LOOKBACK_TRADES:
        del results[0]


# ══════════════════════════════════════════════════════════
# Cooldown / límites de posiciones / señales rojas
# ══════════════════════════════════════════════════════════

def is_in_cooldown(state, symbol, now):
    until = state.get("cooldowns", {}).get(symbol)
    return bool(until) and now < datetime.fromisoformat(until)


def set_cooldown(state, symbol, now):
    until = now + timedelta(hours=config.COOLDOWN_HOURS)
    state.setdefault("cooldowns", {})[symbol] = until.isoformat()


def can_open_new_trade(state, symbol, now):
    if is_in_cooldown(state, symbol, now):
        return False
    positions = state.get("positions", {})
    if symbol in positions:
        return False
    if len(positions) >= config.MAX_CONCURRENT_TRADES:
        return False
    return True


def _red_tracker(state, now):
    today_str = now.strftime("%Y-%m-%d")
    tracker = state.setdefault("red_signals_today", {"date": None, "count": 0})
    if tracker["date"] != today_str:
        tracker["date"] = today_str
        tracker["count"] = 0
    return tracker


def red_signals_used_today(state, now):
    return _red_tracker(state, now)["count"]


def register_red_signal(state, now):
    _red_tracker(state, now)["count"] += 1
