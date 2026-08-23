"""
Strategies/synapse_trail_pro.py

Réplica en Python de "Synapse Trail Pro [WillyAlgoTrader]" v1.2.0.

Se implementa como un motor SECUENCIAL bar-a-bar (no vectorizado),
porque el Pine original depende fuertemente de estado persistente
(`var`) y de referencias a la barra anterior ([1]). Intentar
vectorizar esto con pandas puro introduciría un riesgo real de
repainting o de desajustes sutiles frente al comportamiento real
de TradingView. Priorizamos fidelidad sobre velocidad.

Lo que SÍ se implementa (porque afecta a las señales / alertas):
  - Secciones 6, 7, 8, 9        -> Trail, régimen, Quality Score, filtros
  - Sección 10 completa         -> gestión de riesgo, SL/TP/BE, ratchet,
                                    lifecycle de la posición activa
  - Sección 12 (texto)          -> contenido informativo de las señales
  - Sección 17                  -> equivalentes exactos de las alertas

Lo que NO se implementa (por ser puramente visual, sin efecto en
señales — y porque el usuario pidió explícitamente omitir la tabla):
  - Sección 11 (líneas/plots), 13 (líneas SL/TP dibujadas),
    15 (dashboard/tabla), 16 (watermark)
  - Sección 10a/14 (contadores de estadísticas para el dashboard:
    win rate, avg R, BE saves, flips acumulados, grade A/B/C...).
    Esto NO afecta qué señal se dispara ni cuándo — solo alimentaba
    la tabla visual que se pidió omitir.

IMPORTANTE sobre no-repainting:
  Todo el cálculo trabaja exclusivamente con velas CERRADAS. El
  `MarketData` (Data/market_data.py) debe entregar un DataFrame sin
  la vela en formación. `barstate.isconfirmed` en Pine se traduce
  aquí simplemente en "esta fila ya es una vela cerrada", lo cual
  se garantiza aguas arriba, no dentro de esta clase.

IMPORTANTE sobre el filtro HTF (request.security):
  El Pine usa `request.security(..., [close[1], ema(close,50)[1]],
  barmerge.gaps_off, barmerge.lookahead_on)`, que es el patrón
  canónico y NO-repintante de TradingView para leer la última vela
  HTF ya cerrada. Aquí se reproduce recibiendo un DataFrame HTF
  aparte (ver Data/market_data.py), calculando su EMA(50), y
  haciendo un merge_asof "backward" usando el HTF **desplazado una
  posición** (equivalente al `[1]`) para no usar la vela HTF que
  aún podría estar en formación en el momento de esa vela base.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

from Config.config import PineConfig
from Indicators import indicators as ind


# ══════════════════════════════════════════════════════════
# Estructuras de salida
# ══════════════════════════════════════════════════════════

@dataclass
class BarResult:
    """Todo lo relevante calculado para una barra (para debug/validación)."""
    timestamp: Any
    close: float
    dir: int
    trail_line: float
    regime_score: float
    regime_label: str
    is_choppy: bool
    is_trending: bool
    rsi: float
    htf_bias: str
    buy_passes: bool
    sell_passes: bool
    buy_quality: Optional[float]
    sell_quality: Optional[float]
    buy_grade: Optional[str]
    sell_grade: Optional[str]
    active_dir: int
    active_entry: Optional[float]
    active_sl: Optional[float]
    active_tp1: Optional[float]
    active_tp2: Optional[float]
    active_tp3: Optional[float]
    be_active: bool


@dataclass
class Alert:
    """Un evento equivalente a un `alert(...)` del Pine (sección 17)."""
    type: str          # "buy" | "sell" | "flip" | "sl_hit" | "be_activated" | "tp1_hit" | "tp2_hit" | "tp3_hit"
    timestamp: Any
    bar_index: int
    data: Dict[str, Any] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════
# Estrategia
# ══════════════════════════════════════════════════════════

class SynapseTrailPro:
    def __init__(self, cfg: PineConfig):
        self.cfg = cfg

    # ────────────────────────────────────────────────────
    # Preparación de indicadores (vectorizado donde es seguro
    # hacerlo — es decir, donde NO hay estado tipo `var`)
    # ────────────────────────────────────────────────────
    def _prepare_indicators(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame]) -> pd.DataFrame:
        cfg = self.cfg
        out = df.copy()

        out["atr"] = ind.atr(out["high"], out["low"], out["close"], cfg.atrLenInput).fillna(0.0)

        if cfg.useAdaptiveMultInput:
            out["vol_rank"] = ind.percentrank(out["atr"], 100).fillna(50.0)
        else:
            out["vol_rank"] = 50.0

        mult_adjust = np.where(
            out["vol_rank"] < 30, 0.8,
            np.where(out["vol_rank"] > 70, 1.25, 1.0),
        )
        out["mult_adjust"] = mult_adjust if cfg.useAdaptiveMultInput else 1.0
        out["effective_mult"] = cfg.baseMultInput * out["mult_adjust"]

        out["trail_center"] = ind.ema(out["close"], cfg.trailLenInput)
        out["raw_upper"] = out["trail_center"] + out["atr"] * out["effective_mult"]
        out["raw_lower"] = out["trail_center"] - out["atr"] * out["effective_mult"]

        # Régimen de mercado
        _, _, adx_raw = ind.dmi(out["high"], out["low"], out["close"], cfg.adxLenInput)
        out["adx"] = adx_raw.fillna(0.0)
        out["adx_score"] = (out["adx"] / 50.0 * 100.0).clip(upper=100.0)

        out["chop_score"] = ind.choppiness_index(
            out["high"], out["low"], out["close"], cfg.choppinessLenInput
        ).fillna(0.0)

        out["r2"] = ind.r_squared(out["close"], cfg.regimeLenInput).fillna(0.0)
        out["r2_score"] = out["r2"] * 100.0

        out["regime_score"] = (
            out["adx_score"] * 0.40 + out["chop_score"] * 0.35 + out["r2_score"] * 0.25
        )
        out["is_trending"] = out["regime_score"] >= cfg.REGIME_TRENDING
        out["is_choppy"] = out["regime_score"] < cfg.REGIME_CHOPPY

        # RSI
        out["rsi"] = ind.rsi(out["close"], 14).fillna(50.0)

        # Volumen
        out["vol_sma20"] = ind.sma(out["volume"], 20)
        out["has_volume"] = (out["volume"].fillna(0) > 0) & (out["vol_sma20"].fillna(0) > 0)

        # HTF bias (no-repaint): EMA50 del HTF, ambos desplazados 1 barra
        # HTF (equivalente a close[1]/ema[1] dentro de request.security),
        # luego merge_asof "backward" contra el timestamp de la vela base.
        if cfg.useHtfFilterInput and htf_df is not None and len(htf_df) > 0:
            htf = htf_df.copy()
            htf["htf_ema50"] = ind.ema(htf["close"], 50)
            htf_shifted = htf[["timestamp", "close", "htf_ema50"]].shift(1)
            htf_shifted["timestamp"] = htf["timestamp"]  # el timestamp de referencia NO se desplaza,
            # solo los valores (close/ema) -> así el merge_asof usa el
            # timestamp real de la vela HTF pero con los datos de la
            # vela HTF ANTERIOR (ya cerrada) -> replica close[1]/ema[1].
            htf_shifted = htf_shifted.rename(
                columns={"close": "htf_close", "htf_ema50": "htf_ema"}
            )
            out = out.sort_values("timestamp")
            htf_shifted = htf_shifted.sort_values("timestamp")
            out = pd.merge_asof(
                out, htf_shifted, on="timestamp", direction="backward"
            )
        else:
            out["htf_close"] = np.nan
            out["htf_ema"] = np.nan

        return out.reset_index(drop=True)

    # ────────────────────────────────────────────────────
    # Motor secuencial (secciones 6-10, 12, 17)
    # ────────────────────────────────────────────────────
    def calculate(
        self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None
    ) -> tuple[List[BarResult], List[Alert]]:
        """
        Ejecuta la réplica completa sobre TODO el historial recibido,
        barra a barra, reconstruyendo el estado (posición activa,
        ratchet, etc.) desde cero. `df` debe contener SOLO velas
        cerradas, ordenadas ascendentemente, con columnas:
        timestamp, open, high, low, close, volume.
        """
        cfg = self.cfg
        data = self._prepare_indicators(df, htf_df)
        n = len(data)

        WARMUP_BARS = max(cfg.atrLenInput, cfg.trailLenInput, cfg.regimeLenInput) + 5

        eff_sl_mult, eff_tp1_mult, eff_tp2_mult, eff_tp3_mult = cfg.resolve_risk_preset()

        def r_multiple(t1_reached: bool, t2_reached: bool, t3_reached: bool,
                        m1: float, m2: float, m3: float) -> float:
            """
            R-múltiplo realizado al cerrar un trade, replicando la regla
            del propio Pine (sección 10a, `classifyClosedTrade`): la
            posición se reparte en 3 tercios iguales, uno por cada TP.
            Si TP1 nunca se alcanzó, la operación es una pérdida plana
            de -1R. Si se alcanzó, cada tercio adicional que llegó a su
            TP aporta (1/3) × su múltiplo; los tercios no alcanzados
            contribuyen 0R (se asume que salieron al precio de cierre).
            """
            if not t1_reached:
                return -1.0
            r = (1.0 / 3.0) * m1
            if t2_reached:
                r += (1.0 / 3.0) * m2
            if t3_reached:
                r += (1.0 / 3.0) * m3
            return r

        # ── Estado persistente (equivalentes a `var`) ──
        upper_band = np.nan
        lower_band = np.nan
        direction = 0
        prev_direction = 0

        active_dir = 0
        active_entry = np.nan
        active_entry_time = None
        active_sl = np.nan
        active_tp1 = np.nan
        active_tp2 = np.nan
        active_tp3 = np.nan
        active_bar = 0
        active_qual = np.nan
        active_grade = ""
        active_tp1_mult = 0.0
        active_tp2_mult = 0.0
        active_tp3_mult = 0.0

        tp1_reached = False
        tp2_reached = False
        tp3_reached = False
        be_active = False

        results: List[BarResult] = []
        alerts: List[Alert] = []

        for i in range(n):
            row = data.iloc[i]
            close = row["close"]
            high = row["high"]
            low = row["low"]
            atr_val = row["atr"]
            timestamp = row["timestamp"]

            is_warmed_up = i >= WARMUP_BARS

            raw_upper = row["raw_upper"]
            raw_lower = row["raw_lower"]

            prev_upper = upper_band  # nz(upperBand[1], close) se resuelve abajo
            prev_lower = lower_band

            # ── Dirección (sección 6) ──
            if is_warmed_up:
                ref_upper = prev_upper if not np.isnan(prev_upper) else close
                ref_lower = prev_lower if not np.isnan(prev_lower) else close
                if close > ref_upper:
                    direction = 1
                elif close < ref_lower:
                    direction = -1
                # si no se cumple ninguna, `direction` NO cambia (var)

            dir_flipped = direction != prev_direction

            # ── Ratchet / bandas (sección 6) ──
            if cfg.useRatchetInput:
                if direction == 1:
                    lower_band = raw_lower if dir_flipped else max(
                        raw_lower, prev_lower if not np.isnan(prev_lower) else raw_lower
                    )
                    upper_band = raw_upper
                elif direction == -1:
                    upper_band = raw_upper if dir_flipped else min(
                        raw_upper, prev_upper if not np.isnan(prev_upper) else raw_upper
                    )
                    lower_band = raw_lower
                else:
                    upper_band = raw_upper
                    lower_band = raw_lower
            else:
                upper_band = raw_upper
                lower_band = raw_lower

            trail_line = lower_band if direction == 1 else (upper_band if direction == -1 else np.nan)

            raw_buy = direction == 1 and prev_direction == -1 and is_warmed_up
            raw_sell = direction == -1 and prev_direction == 1 and is_warmed_up

            # ── Régimen (sección 7) ──
            regime_score = row["regime_score"]
            is_trending = bool(row["is_trending"])
            is_choppy = bool(row["is_choppy"])
            regime_label = "Trending" if is_trending else ("Choppy" if is_choppy else "Mixed")

            # ── HTF bias (sección 8) ──
            htf_close = row.get("htf_close", np.nan)
            htf_ema = row.get("htf_ema", np.nan)
            htf_data_valid = cfg.useHtfFilterInput and not pd.isna(htf_close) and not pd.isna(htf_ema)
            htf_bull = bool(cfg.useHtfFilterInput and htf_data_valid and htf_close > htf_ema)
            htf_bear = bool(cfg.useHtfFilterInput and htf_data_valid and htf_close < htf_ema)
            htf_bias_label = "off" if not cfg.useHtfFilterInput else (
                "Bullish" if htf_bull else ("Bearish" if htf_bear else "Flat")
            )

            # ── Volumen (sección 8) ──
            has_volume = bool(row["has_volume"])
            vol_sma = row["vol_sma20"] if has_volume else np.nan
            vol_confirm = bool(
                cfg.useVolumeFilterInput and has_volume and not pd.isna(vol_sma)
                and row["volume"] > vol_sma * cfg.volMultInput
            )

            # ── RSI (sección 8) ──
            rsi_val = row["rsi"]
            rsi_bull_ok = rsi_val > 50
            rsi_bear_ok = rsi_val < 50

            # ── Breakout strength (sección 8) ──
            ref_upper_break = prev_upper if not np.isnan(prev_upper) else close
            ref_lower_break = prev_lower if not np.isnan(prev_lower) else close
            if direction == 1:
                break_dist = close - ref_upper_break
            elif direction == -1:
                break_dist = ref_lower_break - close
            else:
                break_dist = 0.0
            break_strength = (
                min(abs(break_dist) / atr_val, 3.0) / 3.0 * 100.0 if atr_val != 0 else 0.0
            )

            def calc_quality_score(is_buy: bool) -> float:
                htf_matches = htf_data_valid and ((is_buy and htf_bull) or (not is_buy and htf_bear))
                htf_against = htf_data_valid and ((is_buy and htf_bear) or (not is_buy and htf_bull))
                htf_part = 30.0 if htf_matches else (0.0 if htf_against else 15.0)

                vol_part = 20.0 if (not cfg.useVolumeFilterInput or not has_volume) else (
                    20.0 if vol_confirm else 0.0
                )

                rsi_part = 20.0 if ((is_buy and rsi_bull_ok) or (not is_buy and rsi_bear_ok)) else 0.0
                regime_part = regime_score * 0.20
                break_part = break_strength * 0.10
                return htf_part + vol_part + rsi_part + regime_part + break_part

            buy_quality = calc_quality_score(True) if raw_buy else None
            sell_quality = calc_quality_score(False) if raw_sell else None

            def grade_from_score(s):
                if s is None:
                    return "—"
                if s >= cfg.GRADE_A_THRESHOLD:
                    return "A"
                if s >= cfg.GRADE_B_THRESHOLD:
                    return "B"
                return "C"

            buy_grade = grade_from_score(buy_quality)
            sell_grade = grade_from_score(sell_quality)

            # ── Filtros finales (sección 9) — barstate.isconfirmed=True
            #    siempre aquí, porque `data` ya contiene solo velas cerradas.
            buy_passes = (
                raw_buy
                and (buy_quality is None or buy_quality >= cfg.minQualityInput)
                and not (cfg.skipChoppyInput and is_choppy)
            )
            sell_passes = (
                raw_sell
                and (sell_quality is None or sell_quality >= cfg.minQualityInput)
                and not (cfg.skipChoppyInput and is_choppy)
            )

            chop_flag = " ⚠" if is_choppy else ""

            # ── Riesgo: distancia SL (sección 10) ──
            sl_distance = atr_val * eff_sl_mult

            # ── Flip detection ──
            buy_flip = buy_passes and active_dir == -1
            sell_flip = sell_passes and active_dir == 1
            flip_detected = buy_flip or sell_flip
            flip_from_dir = ("LONG" if active_dir == 1 else "SHORT") if flip_detected else ""
            flip_to_dir = ("LONG" if buy_flip else "SHORT") if flip_detected else ""
            flip_from_entry = active_entry if flip_detected else np.nan

            if flip_detected:
                alerts.append(Alert(
                    type="flip",
                    timestamp=timestamp,
                    bar_index=i,
                    data=dict(
                        from_dir=flip_from_dir,
                        to_dir=flip_to_dir,
                        prior_entry=flip_from_entry,
                        entry_time=active_entry_time,
                        new_entry=close,
                        r_multiple=r_multiple(
                            tp1_reached, tp2_reached, tp3_reached,
                            active_tp1_mult, active_tp2_mult, active_tp3_mult,
                        ),
                        notify=cfg.alertFlipInput,
                    ),
                ))

            # ── Apertura de nueva posición (sección 10b) ──
            if buy_passes:
                active_entry = close
                active_entry_time = timestamp
                active_sl = close - sl_distance
                active_tp1 = close + sl_distance * eff_tp1_mult
                active_tp2 = close + sl_distance * eff_tp2_mult
                active_tp3 = close + sl_distance * eff_tp3_mult
                active_dir = 1
                active_bar = i
                active_qual = buy_quality
                active_grade = buy_grade
                active_tp1_mult, active_tp2_mult, active_tp3_mult = eff_tp1_mult, eff_tp2_mult, eff_tp3_mult
                tp1_reached = tp2_reached = tp3_reached = False
                be_active = False

            if sell_passes:
                active_entry = close
                active_entry_time = timestamp
                active_sl = close + sl_distance
                active_tp1 = close - sl_distance * eff_tp1_mult
                active_tp2 = close - sl_distance * eff_tp2_mult
                active_tp3 = close - sl_distance * eff_tp3_mult
                active_dir = -1
                active_bar = i
                active_qual = sell_quality
                active_grade = sell_grade
                active_tp1_mult, active_tp2_mult, active_tp3_mult = eff_tp1_mult, eff_tp2_mult, eff_tp3_mult
                tp1_reached = tp2_reached = tp3_reached = False
                be_active = False

            current_rr = (
                abs(active_tp1 - active_entry) / abs(active_entry - active_sl)
                if active_dir != 0 and active_entry != active_sl else 0.0
            )

            if buy_passes or sell_passes:
                alert_type = "buy" if buy_passes else "sell"
                grade = buy_grade if buy_passes else sell_grade
                quality = buy_quality if buy_passes else sell_quality
                alerts.append(Alert(
                    type=alert_type,
                    timestamp=timestamp,
                    bar_index=i,
                    data=dict(
                        price=close,
                        sl=active_sl,
                        tp1=active_tp1,
                        tp2=active_tp2,
                        tp3=active_tp3,
                        rr=current_rr,
                        rr1=eff_tp1_mult,
                        rr2=eff_tp2_mult,
                        rr3=eff_tp3_mult,
                        grade=grade,
                        quality=quality,
                        regime=regime_label,
                        regime_score=regime_score,
                        choppy=is_choppy,
                        chop_flag=chop_flag,
                        flip=flip_detected,
                        htf_bias=htf_bias_label,
                        volume_status=(
                            "off" if not cfg.useVolumeFilterInput else
                            ("no data" if not has_volume else ("✓" if vol_confirm else "✗"))
                        ),
                        rsi=rsi_val,
                        notify=True,
                    ),
                ))

            # ── Same-bar guards + hit detection + BE (sección 10c) ──
            be_active_at_bar_start = be_active
            effective_sl = active_sl  # snapshot ANTES de mutación por BE

            can_hit = active_dir != 0 and (i - active_bar) >= cfg.ENTRY_BAR_HOLD

            sl_hit = can_hit and (
                (low <= effective_sl) if active_dir == 1 else (high >= effective_sl)
            )
            tp1_hit = can_hit and (
                (high >= active_tp1) if active_dir == 1 else (low <= active_tp1)
            )
            tp2_hit = can_hit and (
                (high >= active_tp2) if active_dir == 1 else (low <= active_tp2)
            )
            tp3_hit = can_hit and (
                (high >= active_tp3) if active_dir == 1 else (low <= active_tp3)
            )

            tp1_first_touch = tp1_hit and not tp1_reached and not sl_hit
            tp2_first_touch = tp2_hit and not tp2_reached and not sl_hit
            tp3_first_touch = tp3_hit and not tp3_reached and not sl_hit

            if tp1_first_touch:
                tp1_reached = True
            if tp2_first_touch:
                tp2_reached = True
            if tp3_first_touch:
                tp3_reached = True

            be_just_activated = False
            if cfg.useBreakEvenInput and tp1_first_touch and not be_active:
                active_sl = active_entry
                be_active = True
                be_just_activated = True

            # ── Exit snapshots (sección 10d) ──
            exit_entry = active_entry
            exit_sl = effective_sl
            exit_tp1, exit_tp2, exit_tp3 = active_tp1, active_tp2, active_tp3

            # ── Alertas de salida (sección 17) ──
            # Se generan SIEMPRE (para que el diario de operaciones quede
            # completo), y se etiquetan con `notify` según el input
            # correspondiente — así el motor decide si además avisa por
            # Telegram, sin perder el registro para las estadísticas.
            if sl_hit:
                alerts.append(Alert(
                    type="sl_hit",
                    timestamp=timestamp,
                    bar_index=i,
                    data=dict(
                        entry=exit_entry, sl=exit_sl,
                        entry_time=active_entry_time,
                        be_stop=be_active_at_bar_start,
                        r_multiple=r_multiple(
                            tp1_reached, tp2_reached, tp3_reached,
                            active_tp1_mult, active_tp2_mult, active_tp3_mult,
                        ),
                        notify=cfg.alertSlHitInput,
                    ),
                ))
            if be_just_activated:
                alerts.append(Alert(
                    type="be_activated",
                    timestamp=timestamp,
                    bar_index=i,
                    data=dict(
                        entry=exit_entry,
                        entry_time=active_entry_time,
                        notify=cfg.alertTpHitInput,
                    ),
                ))
            if tp1_first_touch:
                alerts.append(Alert(type="tp1_hit", timestamp=timestamp, bar_index=i,
                                     data=dict(price=exit_tp1, entry_time=active_entry_time,
                                               notify=cfg.alertTpHitInput)))
            if tp2_first_touch:
                alerts.append(Alert(type="tp2_hit", timestamp=timestamp, bar_index=i,
                                     data=dict(price=exit_tp2, entry_time=active_entry_time,
                                               notify=cfg.alertTpHitInput)))
            if tp3_first_touch:
                alerts.append(Alert(type="tp3_hit", timestamp=timestamp, bar_index=i,
                                     data=dict(
                                         price=exit_tp3, entry=exit_entry,
                                         entry_time=active_entry_time,
                                         r_multiple=r_multiple(
                                             tp1_reached, tp2_reached, tp3_reached,
                                             active_tp1_mult, active_tp2_mult, active_tp3_mult,
                                         ),
                                         notify=cfg.alertTpHitInput,
                                     )))

            # ── Cierre por SL o TP3 (sección 10e) ──
            reset_condition = (sl_hit or tp3_hit) and active_dir != 0

            results.append(BarResult(
                timestamp=timestamp,
                close=close,
                dir=direction,
                trail_line=trail_line,
                regime_score=regime_score,
                regime_label=regime_label,
                is_choppy=is_choppy,
                is_trending=is_trending,
                rsi=rsi_val,
                htf_bias=htf_bias_label,
                buy_passes=buy_passes,
                sell_passes=sell_passes,
                buy_quality=buy_quality,
                sell_quality=sell_quality,
                buy_grade=buy_grade if raw_buy else None,
                sell_grade=sell_grade if raw_sell else None,
                active_dir=active_dir,
                active_entry=active_entry if active_dir != 0 else None,
                active_sl=active_sl if active_dir != 0 else None,
                active_tp1=active_tp1 if active_dir != 0 else None,
                active_tp2=active_tp2 if active_dir != 0 else None,
                active_tp3=active_tp3 if active_dir != 0 else None,
                be_active=be_active,
            ))

            if reset_condition:
                active_dir = 0
                active_sl = active_tp1 = active_tp2 = active_tp3 = active_entry = np.nan
                active_entry_time = None
                active_bar = 0
                active_qual = np.nan
                active_grade = ""
                active_tp1_mult = active_tp2_mult = active_tp3_mult = 0.0
                tp1_reached = tp2_reached = tp3_reached = False
                be_active = False

            prev_direction = direction

        return results, alerts

    # ────────────────────────────────────────────────────
    # Utilidad para uso en producción (cron): última vela cerrada
    # ────────────────────────────────────────────────────
    def check_latest(
        self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None
    ) -> tuple[Optional[BarResult], List[Alert]]:
        """
        Ejecuta `calculate` sobre todo el historial disponible (necesario
        para reconstruir el estado de la posición activa y del ratchet)
        y devuelve el resultado de la ÚLTIMA barra junto con las alertas
        generadas en esa misma barra.
        """
        results, alerts = self.calculate(df, htf_df)
        if not results:
            return None, []
        last = results[-1]
        last_alerts = [a for a in alerts if a.bar_index == len(results) - 1]
        return last, last_alerts
