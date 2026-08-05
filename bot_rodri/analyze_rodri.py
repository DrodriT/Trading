"""
Análisis de rendimiento por estrategia — Rodri v1.0

Lee el trade_log de state_rodri.json y desglosa el rendimiento (nº de
operaciones, win rate, R medio) por cada una de las 6 estrategias, para
saber cuáles están aportando y cuáles conviene ajustar o retirar.

Como una operación puede tener varias estrategias en confluencia, cada
operación cuenta para TODAS las estrategias que participaron en ella (no
solo la primera) — así una estrategia que casi siempre actúa "acompañada"
también se puede evaluar.

Uso:
    python3 analyze_rodri.py                  # usa state_rodri.json en el directorio actual
    python3 analyze_rodri.py otro_estado.json # o un archivo concreto
"""
import json
import sys
from collections import defaultdict


def load_trade_log(path):
    with open(path, "r") as f:
        state = json.load(f)
    return state.get("trade_log", [])


def analyze(trade_log):
    by_strategy = defaultdict(lambda: {"n": 0, "wins": 0, "r_sum": 0.0})
    by_confluence = defaultdict(lambda: {"n": 0, "wins": 0, "r_sum": 0.0})
    overall = {"n": 0, "wins": 0, "r_sum": 0.0}

    for t in trade_log:
        overall["n"] += 1
        overall["wins"] += 1 if t["is_win"] else 0
        overall["r_sum"] += t["r_result"]

        key_conf = t["confluence"]
        by_confluence[key_conf]["n"] += 1
        by_confluence[key_conf]["wins"] += 1 if t["is_win"] else 0
        by_confluence[key_conf]["r_sum"] += t["r_result"]

        for strat in t["strategies"]:
            by_strategy[strat]["n"] += 1
            by_strategy[strat]["wins"] += 1 if t["is_win"] else 0
            by_strategy[strat]["r_sum"] += t["r_result"]

    return overall, by_strategy, by_confluence


def fmt_row(name, d):
    n = d["n"]
    wr = d["wins"] / n * 100 if n else 0
    avg_r = d["r_sum"] / n if n else 0
    return f"{name:<18} | n={n:<4} | WR={wr:5.1f}% | R total={d['r_sum']:+7.2f} | R medio={avg_r:+.3f}"


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "state_rodri.json"
    trade_log = load_trade_log(path)

    if not trade_log:
        print(f"No hay operaciones en el trade_log de '{path}' todavía "
              f"(recuerda: solo se registran las cerradas DESPUÉS de la actualización "
              f"que añadió el trade_log; las anteriores a eso no aparecen aquí).")
        return

    overall, by_strategy, by_confluence = analyze(trade_log)

    print("=" * 70)
    print(fmt_row("TOTAL", overall))
    print("=" * 70)

    print("\n--- Por estrategia (una operación cuenta para cada estrategia en confluencia) ---")
    for name, d in sorted(by_strategy.items(), key=lambda kv: -kv[1]["r_sum"]):
        print(fmt_row(name, d))

    print("\n--- Por nivel de confluencia (nº de estrategias de acuerdo) ---")
    for conf, d in sorted(by_confluence.items()):
        print(fmt_row(f"Confluencia={conf}", d))


if __name__ == "__main__":
    main()
