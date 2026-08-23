"""
tests_smoke.py

Tests de humo (no requieren red ni exchange real): generan un
DataFrame OHLCV sintético y comprueban que:
  - Los indicadores no explotan y devuelven tipos/rangos razonables.
  - La estrategia corre de punta a punta sin excepciones.
  - El dedupe de estado funciona (no reenvía la misma alerta).

Ejecutar con:  python tests_smoke.py
"""

import numpy as np
import pandas as pd

from Config.config import PineConfig
from Strategies.synapse_trail_pro import SynapseTrailPro
from Indicators import indicators as ind
from Core.state import StateManager, BotState


def make_synthetic_ohlcv(n=800, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")

    # Random walk con algo de tendencia para generar cruces reales
    steps = rng.normal(loc=0.0, scale=1.0, size=n)
    trend = np.sin(np.linspace(0, 6 * np.pi, n)) * 2.0
    close = 100 + np.cumsum(steps) * 0.5 + trend
    close = np.maximum(close, 1.0)

    high = close + np.abs(rng.normal(0.3, 0.2, n))
    low = close - np.abs(rng.normal(0.3, 0.2, n))
    open_ = close + rng.normal(0, 0.2, n)
    volume = np.abs(rng.normal(1000, 300, n))

    df = pd.DataFrame({
        "timestamp": ts, "open": open_, "high": high,
        "low": low, "close": close, "volume": volume,
    })
    return df


def test_indicators_dont_explode():
    df = make_synthetic_ohlcv()
    atr = ind.atr(df["high"], df["low"], df["close"], 13)
    assert atr.dropna().ge(0).all()

    rsi = ind.rsi(df["close"], 14)
    valid = rsi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()

    r2 = ind.r_squared(df["close"], 50)
    valid_r2 = r2.dropna()
    assert (valid_r2 >= -1e-9).all() and (valid_r2 <= 1 + 1e-9).all()

    _, _, adx = ind.dmi(df["high"], df["low"], df["close"], 14)
    assert adx.dropna().ge(0).all()

    chop = ind.choppiness_index(df["high"], df["low"], df["close"], 14)
    valid_chop = chop.dropna()
    assert (valid_chop >= 0).all() and (valid_chop <= 100).all()

    print("OK - indicadores dentro de rango")


def test_strategy_runs_end_to_end():
    df = make_synthetic_ohlcv()
    cfg = PineConfig()
    strat = SynapseTrailPro(cfg)
    results, alerts = strat.calculate(df, htf_df=None)

    assert len(results) == len(df)
    # Debe generar al menos alguna señal en 800 velas de random walk con tendencia
    signal_alerts = [a for a in alerts if a.type in ("buy", "sell")]
    assert len(signal_alerts) > 0, "No se generó ninguna señal buy/sell"

    # Toda alerta buy debe tener SL por debajo del precio y TP1 por encima
    for a in signal_alerts:
        if a.type == "buy":
            assert a.data["sl"] < a.data["price"] < a.data["tp1"]
        else:
            assert a.data["tp1"] < a.data["price"] < a.data["sl"]

    print(f"OK - estrategia genera {len(signal_alerts)} señales buy/sell en datos sintéticos")


def test_no_lookahead_same_result_on_prefix():
    """
    Comprueba parcialmente ausencia de repainting: si recalculamos la
    estrategia sobre un PREFIJO del historial (por ejemplo, hasta la
    barra 500), el resultado de esa barra 500 debe ser IDÉNTICO al que
    se obtiene calculando sobre el historial completo. Si no lo fuera,
    algo estaría mirando datos futuros.
    """
    df = make_synthetic_ohlcv(n=800)
    cfg = PineConfig()
    strat = SynapseTrailPro(cfg)

    full_results, _ = strat.calculate(df, htf_df=None)
    prefix_results, _ = strat.calculate(df.iloc[:500].reset_index(drop=True), htf_df=None)

    bar_full = full_results[499]
    bar_prefix = prefix_results[499]

    assert bar_full.dir == bar_prefix.dir
    assert bar_full.trail_line == bar_prefix.trail_line or (
        pd.isna(bar_full.trail_line) and pd.isna(bar_prefix.trail_line)
    )
    assert bar_full.buy_passes == bar_prefix.buy_passes
    assert bar_full.sell_passes == bar_prefix.sell_passes

    print("OK - sin lookahead detectable (prefijo vs histórico completo coinciden)")


def test_state_dedup():
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        sm = StateManager(state_file)
        state = sm.load()
        assert state.last_processed_timestamp is None

        aid = sm.alert_id("BTC/USDT", "15m", "2025-01-01T00:00:00Z", "buy")
        assert not sm.already_sent(state, aid)
        sm.mark_sent(state, aid)
        sm.save(state)

        state2 = sm.load()
        assert sm.already_sent(state2, aid)

    print("OK - dedupe de estado funciona correctamente")


def test_state_dedup_multi_symbol():
    """
    Dos monedas distintas no deben pisarse el estado entre sí:
    el last_processed_timestamp de BTC no debe afectar a ETH.
    """
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        state_file = os.path.join(tmp, "state.json")
        sm = StateManager(state_file)
        state = sm.load()

        key_btc = sm.symbol_key("BTC/USDT", "15m")
        key_eth = sm.symbol_key("ETH/USDT", "15m")

        state.last_processed_by_key[key_btc] = "2025-01-01T00:15:00Z"
        sm.save(state)

        state2 = sm.load()
        assert state2.last_processed_by_key.get(key_btc) == "2025-01-01T00:15:00Z"
        assert state2.last_processed_by_key.get(key_eth) is None

        aid_btc = sm.alert_id("BTC/USDT", "15m", "2025-01-01T00:15:00Z", "buy")
        aid_eth = sm.alert_id("ETH/USDT", "15m", "2025-01-01T00:15:00Z", "buy")
        sm.mark_sent(state2, aid_btc)
        assert sm.already_sent(state2, aid_btc)
        assert not sm.already_sent(state2, aid_eth)

    print("OK - el estado multi-símbolo no se pisa entre monedas")


def test_trade_journal_end_to_end():
    """
    Corre la estrategia, aplica TODAS las alertas al diario de
    operaciones (TradeJournal), y comprueba que:
      - Cada BUY/SELL abre un trade.
      - Los TP van marcándose (tp1_hit/tp2_hit/tp3_hit).
      - Los trades cerrados tienen result "win" o "loss" coherente
        con la regla (TP1 alcanzado = win).
      - journal_stats.compute_stats no revienta y produce un
        win_rate_pct entre 0 y 100.
    """
    import tempfile, os
    from Core.trade_journal import TradeJournal
    import journal_stats

    df = make_synthetic_ohlcv(n=800)
    cfg = PineConfig()
    strat = SynapseTrailPro(cfg)
    _, alerts = strat.calculate(df, htf_df=None)

    with tempfile.TemporaryDirectory() as tmp:
        journal_file = os.path.join(tmp, "trades.json")
        journal = TradeJournal(journal_file)
        trades = journal.load()
        assert trades == []

        for alert in alerts:
            journal.apply_alert(trades, "BTC/USDT", "15m", alert)
        journal.save(trades)

        reloaded = journal.load()
        assert len(reloaded) > 0, "El diario no registró ningún trade"

        buy_sell_count = sum(1 for a in alerts if a.type in ("buy", "sell"))
        assert len(reloaded) == buy_sell_count, "Nº de trades != nº de señales BUY/SELL"

        closed = [t for t in reloaded if t["closed"]]
        for t in closed:
            assert t["result"] in ("win", "loss")
            if t["tp1_hit"]:
                assert t["result"] == "win"
            else:
                assert t["result"] == "loss"
            # Un trade cerrado siempre tiene motivo y fecha de cierre
            assert t["close_reason"] in ("sl", "be_stop", "tp3", "flip")
            assert t["close_time"] is not None

        stats = journal_stats.compute_stats(reloaded)
        assert 0.0 <= stats["win_rate_pct"] <= 100.0
        assert stats["total_trades"] == len(reloaded)

    print(f"OK - diario de operaciones: {len(reloaded)} trades, "
          f"win rate {stats['win_rate_pct']}% sobre {stats['total_closed']} cerrados")


if __name__ == "__main__":
    test_indicators_dont_explode()
    test_strategy_runs_end_to_end()
    test_no_lookahead_same_result_on_prefix()
    test_state_dedup()
    test_state_dedup_multi_symbol()
    test_trade_journal_end_to_end()
    print("\nTodos los tests de humo pasaron.")
