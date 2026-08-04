"""
Modelos tipados — Rodri v1.0

Dataclasses que documentan y validan las formas de datos que ya circulan
por el proyecto como diccionarios sueltos: el resultado de una estrategia
individual, la señal del ensemble, los niveles de riesgo, y una posición
abierta.

IMPORTANTE — alcance de esta fase (decisión explícita, ver conversación):
Estas dataclasses son ADITIVAS. El pipeline en vivo (strategies/*.py,
ensemble.py, risk.py, positions.py) sigue trabajando con diccionarios
planos exactamente igual que antes — NO se ha tocado ningún archivo del
motor de señales para que empiece a devolver instancias de estas clases.

¿Por qué no conectarlas ya? Hacerlo tocaría de nuevo ensemble.py, risk.py
y positions.py (que ya pasaron su verificación con el caso dorado y con
tus datos reales de producción), y el beneficio de tipado no compensa el
riesgo de reintroducir un cambio de comportamiento en el motor de
trading real por una mejora de "calidad de código". Quedan disponibles
aquí, ya probadas y con round-trip verificado contra datos reales, para
cuando decidas conectarlas (por ejemplo, en tools/analyze.py, en un
futuro dashboard, o si en algún momento se resuelve conectar el pipeline
completo a tipos fuertes).

Cada clase implementa:
  - to_dict()   -> dict con las mismas claves que ya usa el proyecto hoy
  - from_dict() -> classmethod, reconstruye la instancia desde ese dict
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StrategyResult:
    """
    Contrato rico que devuelve cada detect_* de strategies/ (Fase 3):
    {direction, score, confidence, reason, metadata} | None.
    """
    direction: str          # "ALCISTA" | "BAJISTA"
    score: float
    confidence: float
    reason: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "score": self.score,
            "confidence": self.confidence,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyResult":
        return cls(
            direction=d["direction"],
            score=d["score"],
            confidence=d["confidence"],
            reason=d["reason"],
            metadata=d.get("metadata", {}),
        )


@dataclass
class TpLevel:
    """Un take-profit individual dentro de RiskLevels."""
    label: str    # "TP1" | "TP2" | "TP3"
    price: float
    rr: float

    def to_dict(self) -> dict:
        return {"label": self.label, "price": self.price, "rr": self.rr}

    @classmethod
    def from_dict(cls, d: dict) -> "TpLevel":
        return cls(label=d["label"], price=d["price"], rr=d["rr"])


@dataclass
class RiskLevels:
    """Salida de risk.build_risk_levels() / risk.cap_tp_at_r()."""
    sl: float
    sl_distance: float
    tps: list  # list[TpLevel]
    used_structural_sl: bool = False

    def to_dict(self) -> dict:
        return {
            "sl": self.sl,
            "sl_distance": self.sl_distance,
            "tps": [tp.to_dict() for tp in self.tps],
            "used_structural_sl": self.used_structural_sl,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskLevels":
        return cls(
            sl=d["sl"],
            sl_distance=d["sl_distance"],
            tps=[TpLevel.from_dict(tp) for tp in d["tps"]],
            used_structural_sl=d.get("used_structural_sl", False),
        )


@dataclass
class Signal:
    """Salida de ensemble.compute_ensemble_signal() /
    market_state.apply_htf_confirmation()."""
    direction: str
    score: float
    prob: float
    strategies: list  # list[str]
    confluence: int
    htf_trend: Optional[str] = None
    htf_adx: Optional[float] = None
    htf_penalized: bool = False

    def to_dict(self) -> dict:
        d = {
            "direction": self.direction,
            "score": self.score,
            "prob": self.prob,
            "strategies": self.strategies,
            "confluence": self.confluence,
        }
        # Igual que el diccionario original: htf_trend/htf_adx/htf_penalized
        # solo aparecen si CONFIRM_ENABLED los añadió (apply_htf_confirmation).
        if self.htf_trend is not None:
            d["htf_trend"] = self.htf_trend
            d["htf_adx"] = self.htf_adx
            d["htf_penalized"] = self.htf_penalized
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Signal":
        return cls(
            direction=d["direction"],
            score=d["score"],
            prob=d["prob"],
            strategies=d["strategies"],
            confluence=d["confluence"],
            htf_trend=d.get("htf_trend"),
            htf_adx=d.get("htf_adx"),
            htf_penalized=d.get("htf_penalized", False),
        )


@dataclass
class Position:
    """
    Posición abierta tal como se guarda en state["positions"][symbol]
    (ver positions.check_symbol). NO representa una entrada de
    trade_log (esa tiene forma distinta: exit/r_result/is_win/
    close_reason en vez de tp1/tp2/tp3/tp1_reached/be_active) — trade_log
    se construye aparte en positions.close_position a partir de una
    Position ya cerrada más el resultado.
    """
    dir: str
    entry: float
    entry_candle: str
    sl: float
    tp1: float
    tp2: float
    tp3: float
    tp_rr: list
    score: float
    prob: float
    strategies: list
    confluence: int
    leverage: int
    is_red: bool
    size_factor: float
    tp1_reached: bool = False
    tp2_reached: bool = False
    tp3_reached: bool = False
    be_active: bool = False
    htf_trend: Optional[str] = None
    htf_adx: Optional[float] = None
    htf_penalized: bool = False
    used_structural_sl: bool = False

    def to_dict(self) -> dict:
        return {
            "dir": self.dir,
            "entry": self.entry,
            "entry_candle": self.entry_candle,
            "sl": self.sl,
            "tp1": self.tp1, "tp2": self.tp2, "tp3": self.tp3,
            "tp_rr": self.tp_rr,
            "tp1_reached": self.tp1_reached,
            "tp2_reached": self.tp2_reached,
            "tp3_reached": self.tp3_reached,
            "be_active": self.be_active,
            "score": self.score,
            "prob": self.prob,
            "strategies": self.strategies,
            "confluence": self.confluence,
            "htf_trend": self.htf_trend,
            "htf_adx": self.htf_adx,
            "htf_penalized": self.htf_penalized,
            "used_structural_sl": self.used_structural_sl,
            "leverage": self.leverage,
            "is_red": self.is_red,
            "size_factor": self.size_factor,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(
            dir=d["dir"],
            entry=d["entry"],
            entry_candle=d["entry_candle"],
            sl=d["sl"],
            tp1=d["tp1"], tp2=d["tp2"], tp3=d["tp3"],
            tp_rr=d["tp_rr"],
            tp1_reached=d.get("tp1_reached", False),
            tp2_reached=d.get("tp2_reached", False),
            tp3_reached=d.get("tp3_reached", False),
            be_active=d.get("be_active", False),
            score=d["score"],
            prob=d["prob"],
            strategies=d["strategies"],
            confluence=d["confluence"],
            htf_trend=d.get("htf_trend"),
            htf_adx=d.get("htf_adx"),
            htf_penalized=d.get("htf_penalized", False),
            used_structural_sl=d.get("used_structural_sl", False),
            leverage=d["leverage"],
            is_red=d["is_red"],
            size_factor=d["size_factor"],
        )
