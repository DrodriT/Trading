"""
journal_stats.py

Lee `state/trades.json` (el diario de operaciones que va generando
el bot en cada ejecución) y calcula estadísticas de rendimiento:
% de acierto, desglose por símbolo, por grade (A/B/C), y por motivo
de cierre.

Uso:
    python journal_stats.py
    python journal_stats.py --file otra_ruta/trades.json
    python journal_stats.py --symbol BTC/USDT
    python journal_stats.py --json          # salida en JSON en vez de tabla de texto

Regla de acierto (igual que en el propio Pine / trade_journal.py):
    WIN  = la operación alcanzó al menos TP1 en algún momento.
    LOSS = la operación se cerró (SL, BE-stop o flip) sin llegar a TP1.
    Las operaciones aún ABIERTAS (closed=false) no cuentan para el
    % de acierto — todavía no tienen un resultado definitivo.
"""

from __future__ import annotations
import argparse
import json
import os
from collections import defaultdict
from typing import List, Dict, Any


def load_trades(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        print(f"No existe el archivo de diario: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("trades", [])


def compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    closed = [t for t in trades if t.get("closed")]
    open_trades = [t for t in trades if not t.get("closed")]

    wins = [t for t in closed if t.get("result") == "win"]
    losses = [t for t in closed if t.get("result") == "loss"]

    total_closed = len(closed)
    win_rate = (len(wins) / total_closed * 100.0) if total_closed > 0 else 0.0

    tp1_hits = sum(1 for t in closed if t.get("tp1_hit"))
    tp2_hits = sum(1 for t in closed if t.get("tp2_hit"))
    tp3_hits = sum(1 for t in closed if t.get("tp3_hit"))
    be_saves = sum(
        1 for t in closed
        if t.get("result") == "win" and t.get("close_reason") == "be_stop"
    )

    r_values = [t.get("r_multiple") for t in closed if t.get("r_multiple") is not None]
    avg_r = (sum(r_values) / len(r_values)) if r_values else 0.0

    by_reason = defaultdict(int)
    for t in closed:
        by_reason[t.get("close_reason") or "unknown"] += 1

    by_grade = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in closed:
        g = t.get("grade") or "—"
        if t.get("result") == "win":
            by_grade[g]["wins"] += 1
        elif t.get("result") == "loss":
            by_grade[g]["losses"] += 1

    by_symbol = defaultdict(lambda: {"wins": 0, "losses": 0})
    for t in closed:
        s = t.get("symbol") or "—"
        if t.get("result") == "win":
            by_symbol[s]["wins"] += 1
        elif t.get("result") == "loss":
            by_symbol[s]["losses"] += 1

    return {
        "total_trades": len(trades),
        "total_open": len(open_trades),
        "total_closed": total_closed,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "tp1_hits": tp1_hits,
        "tp2_hits": tp2_hits,
        "tp3_hits": tp3_hits,
        "be_saves": be_saves,
        "avg_r_multiple": round(avg_r, 3),
        "by_close_reason": dict(by_reason),
        "by_grade": {k: v for k, v in by_grade.items()},
        "by_symbol": {k: v for k, v in by_symbol.items()},
    }


def print_report(stats: Dict[str, Any]) -> None:
    print("═" * 50)
    print(" REPORTE DE RENDIMIENTO — Synapse Trail Pro")
    print("═" * 50)
    print(f"Trades totales:      {stats['total_trades']}")
    print(f"  Abiertos:          {stats['total_open']}")
    print(f"  Cerrados:          {stats['total_closed']}")
    print()
    print(f"Wins:                {stats['wins']}")
    print(f"Losses:              {stats['losses']}")
    print(f"% de acierto:        {stats['win_rate_pct']}%")
    print()
    print(f"TP1 alcanzado:       {stats['tp1_hits']}")
    print(f"TP2 alcanzado:       {stats['tp2_hits']}")
    print(f"TP3 alcanzado:       {stats['tp3_hits']}")
    print(f"BE saves:            {stats['be_saves']}  (wins que cerraron en break-even)")
    print(f"Avg R:               {stats['avg_r_multiple']:+.2f}R")
    print()
    print("Por motivo de cierre:")
    for reason, count in stats["by_close_reason"].items():
        print(f"  {reason:10s}: {count}")
    print()
    print("Por grade:")
    for grade, wl in stats["by_grade"].items():
        total = wl["wins"] + wl["losses"]
        pct = (wl["wins"] / total * 100.0) if total > 0 else 0.0
        print(f"  {grade:3s}: {wl['wins']}W / {wl['losses']}L  ({pct:.1f}%)")
    print()
    print("Por símbolo:")
    for symbol, wl in stats["by_symbol"].items():
        total = wl["wins"] + wl["losses"]
        pct = (wl["wins"] / total * 100.0) if total > 0 else 0.0
        print(f"  {symbol:12s}: {wl['wins']}W / {wl['losses']}L  ({pct:.1f}%)")
    print("═" * 50)


def main():
    parser = argparse.ArgumentParser(description="Estadísticas del diario de operaciones")
    parser.add_argument(
        "--file", default=os.path.join("state", "trades.json"),
        help="Ruta al archivo trades.json (default: state/trades.json)",
    )
    parser.add_argument("--symbol", default=None, help="Filtrar por símbolo, ej. BTC/USDT")
    parser.add_argument("--json", action="store_true", help="Salida en JSON en vez de tabla")
    args = parser.parse_args()

    trades = load_trades(args.file)
    if args.symbol:
        trades = [t for t in trades if t.get("symbol") == args.symbol]

    stats = compute_stats(trades)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print_report(stats)


if __name__ == "__main__":
    main()
