# ============================================================
# STRATEGY — Rodri Bot
# Máquina de estados: FLAT, LONG, SHORT
# Gestiona: entradas escalonadas, SL/TP/BE, tracking parcial
# ============================================================
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict

import config as cfg
from indicators import (
    compute_atr, compute_synapse_trail, compute_regime_score,
    compute_quality_score, grade_from_score
)

logger = logging.getLogger(__name__)


# ============================================================
# ESTRUCTURA DE DATOS DE LA POSICIÓN
# ============================================================

@dataclass
class PositionState:
    """Estado de una posición abierta para un símbolo."""
    symbol: str
    direction: int = 0          # 1=LONG, -1=SHORT, 0=FLAT
    entry_price: float = 0.0
    entry_bar_time: int = 0     # timestamp de la vela de entrada
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    quality_score: float = 0.0
    grade: str = ""
    tp1_reached: bool = False
    tp2_reached: bool = False
    tp3_reached: bool = False
    be_active: bool = False     # Break-even activo (SL en entrada)
    orders_ids: list = field(default_factory=list)  # IDs de órdenes de entrada
    tp1_order_id: str = ""
    tp2_order_id: str = ""
    tp3_order_id: str = ""


# ============================================================
# ESTADO GLOBAL
# ============================================================

class StateManager:
    """
    Almacena y persiste el estado de todas las posiciones abiertas.
    """
    def __init__(self, filepath: str = cfg.STATE_FILE):
        self.filepath = filepath
        self.positions: Dict[str, PositionState] = {}  # symbol → PositionState
        self.stats = {
            "total_signals": 0,
            "grade_a": 0, "grade_b": 0, "grade_c": 0,
            "wins": 0, "losses": 0, "be_saves": 0, "flips": 0,
            "r_sum": 0.0
        }
        self.load()

    def load(self):
        """Carga el estado desde JSON."""
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
                for sym, pos_data in data.get("positions", {}).items():
                    self.positions[sym] = PositionState(**pos_data)
                self.stats = data.get("stats", self.stats)
            logger.info(f"Estado cargado: {len(self.positions)} posiciones activas")
        except FileNotFoundError:
            logger.info("No se encontró archivo de estado. Empezando limpio.")
        except Exception as e:
            logger.error(f"Error cargando estado: {e}")

    def save(self):
        """Persiste el estado a JSON."""
        try:
            data = {
                "positions": {sym: asdict(pos) for sym, pos in self.positions.items()},
                "stats": self.stats,
                "updated_at": datetime.now().isoformat()
            }
            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error guardando estado: {e}")

    def get_position(self, symbol: str) -> Optional[PositionState]:
        return self.positions.get(symbol)

    def set_position(self, symbol: str, pos: PositionState):
        self.positions[symbol] = pos
        self.save()

    def close_position(self, symbol: str):
        if symbol in self.positions:
            del self.positions[symbol]
            self.save()

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions and self.positions[symbol].direction != 0


# ============================================================
# MOTOR DE SEÑALES
# ============================================================

class SynapseStrategy:
    """
    Implementa la lógica completa de Synapse Trail Pro:
    - Cálculo de bandas con ratchet
    - Market regime
    - Quality score
    - Señales de entrada/salida
    - Gestión de SL/TP/BE
    """

    def __init__(self, state: StateManager, exchange=None):
        self.state = state
        self.exchange = exchange
        # Historial de bandas por símbolo (para el ratchet)
        self.trail_state: Dict[str, dict] = {}

    # ============================================================
    # CÁLCULO DE SEÑALES
    # ============================================================

    def get_signal(
        self,
        symbol: str,
        df: pd.DataFrame,
        htf_df: Optional[pd.DataFrame]
    ) -> dict:
        """
        Calcula la señal actual para un símbolo.

        Devuelve:
            {
                "direction": 1 (LONG) / -1 (SHORT) / 0 (FLAT),
                "trail_line": float,
                "upper_band": float,
                "lower_band": float,
                "regime_score": float,
                "regime_label": str,
                "is_trending": bool,
                "is_choppy": bool,
                "quality_score": float,
                "grade": str,
                "flip": bool  # True si es señal contraria con posición abierta
            }
        """
        result = {
            "direction": 0,
            "trail_line": np.nan,
            "upper_band": np.nan,
            "lower_band": np.nan,
            "regime_score": 0.0,
            "regime_label": "Mixed",
            "is_trending": False,
            "is_choppy": False,
            "quality_score": 0.0,
            "grade": "—",
            "flip": False
        }

        if len(df) < max(cfg.ATR_LEN, cfg.TRAIL_LEN, cfg.REGIME_LEN) + 5:
            return result

        close = df["close"].values[-1]
        prev_close = df["close"].values[-2] if len(df) >= 2 else close
        atr = compute_atr(df, cfg.ATR_LEN)

        # --- Market Regime ---
        regime_score, regime_label, is_trending, is_choppy = compute_regime_score(
            df, cfg.ADX_PERIOD, cfg.CHOPPINESS_LEN, cfg.REGIME_LEN
        )
        result["regime_score"] = regime_score
        result["regime_label"] = regime_label
        result["is_trending"] = is_trending
        result["is_choppy"] = is_choppy

        # --- Synapse Trail ---
        direction, trail_line, upper, lower, center = compute_synapse_trail(
            df, cfg.ATR_LEN, cfg.TRAIL_LEN, cfg.BASE_MULT,
            cfg.USE_ADAPTIVE_MULT, cfg.USE_RATCHET
        )

        # --- Dirección real con estado (ratchet necesita historial) ---
        trail_st = self.trail_state.get(symbol, {
            "dir": 0, "upper": upper, "lower": lower
        })

        prev_dir = trail_st["dir"]
        prev_upper = trail_st["upper"]
        prev_lower = trail_st["lower"]

        # Determinar nueva dirección
        if close > prev_upper and not np.isnan(prev_upper):
            new_dir = 1
        elif close < prev_lower and not np.isnan(prev_lower):
            new_dir = -1
        else:
            new_dir = prev_dir if prev_dir != 0 else 0

        dir_flipped = new_dir != prev_dir

        # Aplicar ratchet
        if cfg.USE_RATCHET:
            if new_dir == 1:
                lower = max(lower, prev_lower) if not dir_flipped and prev_lower else lower
                upper = upper  # upper flota libre en long
            elif new_dir == -1:
                upper = min(upper, prev_upper) if not dir_flipped and prev_upper else upper
                lower = lower  # lower flota libre en short
        else:
            pass  # Sin ratchet: usar raw_upper/raw_lower

        # Actualizar estado de trail
        self.trail_state[symbol] = {
            "dir": new_dir,
            "upper": upper,
            "lower": lower
        }

        # Trailing line activa
        if new_dir == 1:
            trail_line = lower
        elif new_dir == -1:
            trail_line = upper
        else:
            trail_line = np.nan

        # ¿Señal nueva?
        raw_buy = new_dir == 1 and prev_dir == -1
        raw_sell = new_dir == -1 and prev_dir == 1

        result["direction"] = new_dir
        result["trail_line"] = trail_line
        result["upper_band"] = upper
        result["lower_band"] = lower

        # --- Quality Score (solo en señal nueva) ---
        if raw_buy or raw_sell:
            signal_dir = 1 if raw_buy else -1
            quality = compute_quality_score(
                df, htf_df, signal_dir, regime_score,
                cfg.USE_HTF_FILTER, cfg.USE_VOLUME_FILTER,
                cfg.VOLUME_THRESHOLD, cfg.VOLUME_MA_PERIOD,
                cfg.RSI_PERIOD, atr, prev_upper, prev_lower
            )
            result["quality_score"] = quality
            result["grade"] = grade_from_score(quality)

            # Filtros
            passes_quality = quality >= cfg.MIN_QUALITY_SCORE
            passes_choppy = not (cfg.SKIP_CHOPPY_SIGNALS and is_choppy)

            if passes_quality and passes_choppy:
                result["direction"] = signal_dir  # Señal confirmada

                # ¿Flip?
                existing_pos = self.state.get_position(symbol)
                if existing_pos and existing_pos.direction == -signal_dir:
                    result["flip"] = True
            else:
                result["direction"] = 0  # Señal suprimida

        return result

    # ============================================================
    # GESTIÓN DE POSICIÓN
    # ============================================================

    def open_position(self, symbol: str, direction: int, entry_price: float,
                      quality_score: float, grade: str,
                      bar_time: int, atr_value: float):
        """
        Abre una nueva posición (o flip).
        Calcula SL/TP según preset Balanced.
        """
        sl_distance = atr_value * cfg.SL_MULT

        if direction == 1:  # LONG
            sl = entry_price - sl_distance
            tp1 = entry_price + sl_distance * cfg.TP1_MULT
            tp2 = entry_price + sl_distance * cfg.TP2_MULT
            tp3 = entry_price + sl_distance * cfg.TP3_MULT
        else:  # SHORT
            sl = entry_price + sl_distance
            tp1 = entry_price - sl_distance * cfg.TP1_MULT
            tp2 = entry_price - sl_distance * cfg.TP2_MULT
            tp3 = entry_price - sl_distance * cfg.TP3_MULT

        pos = PositionState(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            entry_bar_time=bar_time,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            tp3=tp3,
            quality_score=quality_score,
            grade=grade
        )

        self.state.set_position(symbol, pos)
        logger.info(f"NUEVA POSICIÓN {symbol}: {'LONG' if direction==1 else 'SHORT'} "
                     f"Entry={entry_price:.4f} SL={sl:.4f} "
                     f"TP1={tp1:.4f} TP2={tp2:.4f} TP3={tp3:.4f} "
                     f"Grade={grade} Quality={quality_score:.0f}")
        return pos

    def update_sl_if_be(self, pos: PositionState):
        """Activa Break-Even: mueve SL a entrada tras TP1."""
        if cfg.USE_BREAK_EVEN and pos.tp1_reached and not pos.be_active:
            pos.sl = pos.entry_price
            pos.be_active = True
            logger.info(f"BE ACTIVO {pos.symbol}: SL movido a entrada {pos.entry_price:.4f}")

    def check_exits(self, symbol: str, df: pd.DataFrame) -> Optional[dict]:
        """
        Revisa si el precio tocó SL, TP1, TP2 o TP3.
        Devuelve dict con el evento de salida, o None.
        """
        pos = self.state.get_position(symbol)
        if not pos or pos.direction == 0:
            return None

        high = df["high"].values[-1]
        low = df["low"].values[-1]
        bar_index = len(df) - 1

        # Misma barra de entrada: ignorar
        if bar_index - pos.entry_bar_time < cfg.ENTRY_BAR_HOLD if hasattr(cfg, 'ENTRY_BAR_HOLD') else True:
            # Simplificación: ignoramos la vela de entrada
            if len(df) <= 2:
                return None

        result = {"event": None, "price": 0.0}

        # SL Hit
        sl_hit = (pos.direction == 1 and low <= pos.sl) or \
                 (pos.direction == -1 and high >= pos.sl)
        # TP hits (first touch)
        tp1_hit = (pos.direction == 1 and high >= pos.tp1) or \
                  (pos.direction == -1 and low <= pos.tp1)
        tp2_hit = (pos.direction == 1 and high >= pos.tp2) or \
                  (pos.direction == -1 and low <= pos.tp2)
        tp3_hit = (pos.direction == 1 and high >= pos.tp3) or \
                  (pos.direction == -1 and low <= pos.tp3)

        # Prioridad: SL tiene preferencia sobre TP en misma vela
        if sl_hit and pos.direction != 0:
            result["event"] = "sl"
            result["price"] = pos.sl
            return result

        if tp3_hit and not pos.tp3_reached:
            pos.tp3_reached = True
            result["event"] = "tp3"
            result["price"] = pos.tp3
            return result

        if tp2_hit and not pos.tp2_reached:
            pos.tp2_reached = True
            result["event"] = "tp2"
            result["price"] = pos.tp2
            return result

        if tp1_hit and not pos.tp1_reached:
            pos.tp1_reached = True
            self.update_sl_if_be(pos)
            result["event"] = "tp1"
            result["price"] = pos.tp1
            return result

        return None if result["event"] is None else result

    def classify_closed_trade(self, pos: PositionState, close_reason: str,
                              was_be: bool) -> Tuple[int, int, int, float]:
        """
        Clasifica un trade cerrado.
        Devuelve: (wins, losses, be_saves, r_multiple)
        """
        wins, losses, be_saves = 0, 0, 0
        r = 0.0

        if pos.tp1_reached:
            # WIN bucket
            r1 = (1.0 / 3.0) * cfg.TP1_MULT
            r2 = (1.0 / 3.0) * cfg.TP2_MULT if pos.tp2_reached else 0.0
            r3 = (1.0 / 3.0) * cfg.TP3_MULT if pos.tp3_reached else 0.0
            r = r1 + r2 + r3
            wins = 1
            if close_reason == "sl" and was_be:
                be_saves = 1
        else:
            r = -1.0
            losses = 1

        return wins, losses, be_saves, r