"""
Ensemble — ejecuta las 6 estrategias y agrega sus resultados en una única
señal (dirección, score, probabilidad, confluencia).

Extraído de strategy.py sin cambios de lógica. Esta es la única
responsabilidad del ensemble: ejecutar + agregar + decidir si hay señal.
Las estrategias individuales nunca deciden por sí mismas si abrir una
operación — eso lo decide exclusivamente esta agregación.
"""
from strategies import DETECTORS
from scoring import score_to_probability


def run_all_strategies(df, cfg):
    """
    Ejecuta las 6 estrategias sobre el DataFrame ya indicadorizado y
    devuelve la lista de "hits" (una por cada estrategia que disparó),
    con el peso y el score ponderado ya aplicados para el ensemble.

    Cada detector devuelve {direction, score, confidence, reason,
    metadata} o None (contrato rico). Aquí solo se usa "direction" y
    "score" para el cálculo del ensemble (igual que antes); confidence,
    reason y metadata se conservan en el hit para inspección/depuración
    (p. ej. desde tools/analyze.py) pero no alteran el score ni el
    resultado del ensemble.
    """
    hits = []
    for name, fn in DETECTORS.items():
        result = fn(df, cfg)
        if result is None:
            continue
        direction = result["direction"]
        score = result["score"]
        weight = cfg.STRATEGY_WEIGHTS.get(name, 1.0)
        hits.append({
            "name": name, "direction": direction, "score": round(score, 1),
            "weight": weight, "weighted_score": round(score * weight, 1),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
            "metadata": result.get("metadata"),
        })
    return hits


def compute_ensemble_signal(df, cfg):
    """
    Agrega los hits de run_all_strategies por dirección (bonus de
    confluencia incluido) y decide la señal ganadora, si la hay.
    Devuelve {direction, score, prob, strategies, confluence} o None.
    """
    hits = run_all_strategies(df, cfg)
    if not hits:
        return None

    by_dir = {"ALCISTA": [], "BAJISTA": []}
    for h in hits:
        by_dir[h["direction"]].append(h)

    def dir_total(hs):
        if not hs:
            return -1.0
        if len(hs) == 1:
            return min(hs[0]["score"], cfg.MAX_SOLO_SCORE)
        total_weight = sum(h["weight"] for h in hs)
        avg = (sum(h["weighted_score"] for h in hs) / total_weight)
        bonus = cfg.CONFLUENCE_BONUS * (len(hs) - 1)
        return min(100.0, avg + bonus)

    total_long = dir_total(by_dir["ALCISTA"])
    total_short = dir_total(by_dir["BAJISTA"])

    if total_long < 0 and total_short < 0:
        return None

    if total_long >= total_short:
        winning_dir, winning_hits, score = "ALCISTA", by_dir["ALCISTA"], total_long
    else:
        winning_dir, winning_hits, score = "BAJISTA", by_dir["BAJISTA"], total_short

    score = round(score)
    prob = round(score_to_probability(score, cfg), 2)

    return {
        "direction": winning_dir,
        "score": score,
        "prob": prob,
        "strategies": [h["name"] for h in winning_hits],
        "confluence": len(winning_hits),
    }
