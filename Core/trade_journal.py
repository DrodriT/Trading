"""
Core/trade_journal.py

Diario de operaciones (trade journal). Persiste cada entrada
(BUY/SELL) generada por la estrategia en un archivo JSON, y va
marcando qué TP se ha alcanzado, si se activó el Break-Even, y cómo
se cerró la operación (SL, BE-stop, TP3, o FLIP). Pensado para poder
calcular DESPUÉS, de forma independiente, el % de acierto real del
bot — ver `journal_stats.py`.

Se guarda en JSON plano (no una base de datos) porque encaja con el
modelo "sin proceso persistente" de cron-job.org: se lee, se
modifica, se escribe, en cada ejecución — igual que `state.json`.

── Estructura de cada trade ──
{
  "id": "BTC/USDT|15m|2026-08-20 10:35:00+00:00",
  "symbol": "BTC/USDT",
  "timeframe": "15m",
  "direction": "LONG" | "SHORT",
  "entry_time": "2026-08-20 10:35:00+00:00",
  "entry_price": 65420.5,
  "sl": 65100.0,
  "tp1": 65740.0,
  "tp2": 66060.0,
  "tp3": 66380.0,
  "grade": "A",
  "quality": 82.0,
  "regime": "Trending",

  "tp1_hit": false, "tp1_hit_time": null,
  "tp2_hit": false, "tp2_hit_time": null,
  "tp3_hit": false, "tp3_hit_time": null,
  "be_activated": false, "be_time": null,
  "sl_hit": false, "sl_hit_time": null,

  "closed": false,
  "close_reason": null,   # "sl" | "be_stop" | "tp3" | "flip"
  "close_time": null,
  "result": null          # "win" | "loss" | null (mientras sigue abierta)
}

── Regla de clasificación WIN/LOSS ──
Misma regla que usa el propio Pine en su lógica interna de
estadísticas (sección 10a del script original, `classifyClosedTrade`):
si TP1 se alcanzó en algún momento, la operación es WIN, sin importar
cómo se cerró después (BE-stop, flip, o llegó a TP3). Si TP1 nunca
se alcanzó, es LOSS.
"""

from __future__ import annotations
import json
import os
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class TradeJournal:
    def __init__(self, journal_file: str):
        self.journal_file = journal_file
        os.makedirs(os.path.dirname(journal_file), exist_ok=True)

    # ── Persistencia ────────────────────────────────────────
    def load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.journal_file):
            return []
        try:
            with open(self.journal_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("trades", [])
        except (json.JSONDecodeError, OSError) as e:
            logger.error("No se pudo leer el diario de operaciones (%s). Se usa uno vacío.", e)
            return []

    def save(self, trades: List[Dict[str, Any]]) -> None:
        tmp_path = self.journal_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump({"trades": trades}, f, indent=2, default=str)
            os.replace(tmp_path, self.journal_file)
        except OSError as e:
            logger.error("No se pudo guardar el diario de operaciones: %s", e)

    # ── Identificación de trades ─────────────────────────────
    @staticmethod
    def trade_id(symbol: str, timeframe: str, entry_time) -> str:
        return f"{symbol}|{timeframe}|{entry_time}"

    @staticmethod
    def _find_open(trades: List[Dict[str, Any]], symbol: str, timeframe: str, entry_time) -> Optional[dict]:
        if entry_time is None:
            return None
        tid = TradeJournal.trade_id(symbol, timeframe, entry_time)
        for t in trades:
            if t["id"] == tid and not t["closed"]:
                return t
        return None

    @staticmethod
    def _exists(trades: List[Dict[str, Any]], trade_id: str) -> bool:
        return any(t["id"] == trade_id for t in trades)

    @staticmethod
    def find_trade(trades: List[Dict[str, Any]], symbol: str, timeframe: str, entry_time) -> Optional[dict]:
        """Busca un trade por id, esté abierto o cerrado (a diferencia de
        `_find_open`). Lo usa el motor para construir los mensajes de
        Telegram de cierre (TP3/SL/flip), que necesitan datos del trade
        ya actualizado (entry_price, r_multiple, result...)."""
        if entry_time is None:
            return None
        tid = TradeJournal.trade_id(symbol, timeframe, entry_time)
        for t in trades:
            if t["id"] == tid:
                return t
        return None

    # ── Apertura de un trade nuevo ───────────────────────────
    def _open_trade(self, trades: List[Dict[str, Any]], symbol: str, timeframe: str, alert) -> None:
        tid = self.trade_id(symbol, timeframe, alert.timestamp)
        if self._exists(trades, tid):
            # Ya registrado (ejecución repetida sobre la misma vela) -> idempotente
            return
        d = alert.data
        direction = "LONG" if alert.type == "buy" else "SHORT"
        trades.append({
            "id": tid,
            "symbol": symbol,
            "timeframe": timeframe,
            "direction": direction,
            "entry_time": str(alert.timestamp),
            "entry_price": d.get("price"),
            "sl": d.get("sl"),
            "tp1": d.get("tp1"),
            "tp2": d.get("tp2"),
            "tp3": d.get("tp3"),
            "grade": d.get("grade"),
            "quality": d.get("quality"),
            "regime": d.get("regime"),
            # R-múltiplo de cada TP (= su multiplicador de riesgo, ya que
            # SL siempre está a 1R). Se usa al cerrar para calcular el
            # resultado en R, igual que `classifyClosedTrade` en el Pine.
            "tp1_mult": d.get("rr1"),
            "tp2_mult": d.get("rr2"),
            "tp3_mult": d.get("rr3"),
            "tp1_hit": False, "tp1_hit_time": None,
            "tp2_hit": False, "tp2_hit_time": None,
            "tp3_hit": False, "tp3_hit_time": None,
            "be_activated": False, "be_time": None,
            "sl_hit": False, "sl_hit_time": None,
            "closed": False,
            "close_reason": None,
            "close_time": None,
            "result": None,
            "r_multiple": None,
        })

    # ── R-múltiplo al cierre (misma fórmula que el Pine original) ──
    # Cada TP alcanzado aporta 1/3 de posición a su propio R-múltiplo
    # (tp*_mult). Si no llegó a TP1, la operación es una pérdida plana
    # de -1R. Ejemplo con TP1=1R, TP2=2R, TP3=3R y los tres alcanzados:
    # (1/3)*1 + (1/3)*2 + (1/3)*3 = 2.00R.
    @staticmethod
    def _compute_r_multiple(trade: Dict[str, Any]) -> float:
        if not trade["tp1_hit"]:
            return -1.0
        r = (1.0 / 3.0) * (trade.get("tp1_mult") or 0.0)
        if trade["tp2_hit"]:
            r += (1.0 / 3.0) * (trade.get("tp2_mult") or 0.0)
        if trade["tp3_hit"]:
            r += (1.0 / 3.0) * (trade.get("tp3_mult") or 0.0)
        return r

    # ── Aplicar un evento de la estrategia al trade correspondiente ──
    def apply_alert(self, trades: List[Dict[str, Any]], symbol: str, timeframe: str, alert) -> None:
        if alert.type in ("buy", "sell"):
            self._open_trade(trades, symbol, timeframe, alert)
            return

        entry_time = alert.data.get("entry_time")
        trade = self._find_open(trades, symbol, timeframe, entry_time)
        if trade is None:
            # No se pudo vincular (p.ej. el trade se abrió antes de existir
            # el diario, o ya estaba cerrado). No hay nada que actualizar.
            return

        if alert.type == "tp1_hit":
            trade["tp1_hit"] = True
            trade["tp1_hit_time"] = str(alert.timestamp)

        elif alert.type == "tp2_hit":
            trade["tp2_hit"] = True
            trade["tp2_hit_time"] = str(alert.timestamp)

        elif alert.type == "tp3_hit":
            trade["tp3_hit"] = True
            trade["tp3_hit_time"] = str(alert.timestamp)
            trade["closed"] = True
            trade["close_reason"] = "tp3"
            trade["close_time"] = str(alert.timestamp)
            trade["result"] = "win"
            trade["r_multiple"] = round(self._compute_r_multiple(trade), 4)

        elif alert.type == "be_activated":
            trade["be_activated"] = True
            trade["be_time"] = str(alert.timestamp)

        elif alert.type == "sl_hit":
            trade["sl_hit"] = True
            trade["sl_hit_time"] = str(alert.timestamp)
            trade["closed"] = True
            trade["close_reason"] = "be_stop" if alert.data.get("be_stop") else "sl"
            trade["close_time"] = str(alert.timestamp)
            trade["result"] = "win" if trade["tp1_hit"] else "loss"
            trade["r_multiple"] = round(self._compute_r_multiple(trade), 4)

        elif alert.type == "flip":
            trade["closed"] = True
            trade["close_reason"] = "flip"
            trade["close_time"] = str(alert.timestamp)
            trade["result"] = "win" if trade["tp1_hit"] else "loss"
            trade["r_multiple"] = round(self._compute_r_multiple(trade), 4)
