"""
Core/engine.py

Coordina una ejecución completa del bot (pensada para ser disparada
por cron-job.org):

  1. Obtener OHLCV (TF base + HTF) — solo velas cerradas.
  2. Ejecutar la estrategia sobre TODO el histórico disponible
     (para reconstruir fielmente el estado de la posición activa
     y del trail ratchet).
  3. Filtrar las alertas que ya se enviaron en ejecuciones previas.
  4. Enviar por Telegram las alertas nuevas.
  5. Guardar el estado actualizado.
"""

from __future__ import annotations
import logging
from typing import List, Dict

import pandas as pd

from Config.config import InfraConfig, PineConfig
from Data.market_data import MarketData
from Strategies.synapse_trail_pro import SynapseTrailPro, Alert
from Telegram.bot import TelegramBot, send_signal
from Core.state import StateManager
from Core.trade_journal import TradeJournal

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# Formateo de mensajes (equivalente a la sección 17 del Pine,
# variante "texto" — no la variante JSON/webhook, que no aplica aquí
# porque el destino es Telegram, no un webhook genérico)
# ══════════════════════════════════════════════════════════

def _fmt_price(v) -> str:
    if v is None:
        return "n/a"
    try:
        if v != v:  # NaN
            return "n/a"
    except TypeError:
        return "n/a"
    return f"{v:,.5g}"


def _fmt_pct(level, entry) -> str:
    if level is None or entry is None or entry == 0:
        return ""
    try:
        if level != level or entry != entry:  # NaN
            return ""
    except TypeError:
        return ""
    pct = (level - entry) / entry * 100.0
    sign = "+" if pct >= 0 else ""
    return f" ({sign}{pct:.2f}%)"


def _fmt_r(r) -> str:
    if r is None:
        return "n/a"
    sign = "+" if r >= 0 else ""
    return f"{sign}{r:.2f}R"


def _footer(strategy_name: str) -> str:
    return f"\n\n🤖 <i>{strategy_name}</i>"


def format_alert_message(
    alert: Alert, symbol: str, timeframe: str, strategy_name: str,
    journal_trades: list | None = None,
) -> str:
    """
    Formatea un evento individual. Para los eventos de CIERRE
    (tp3_hit, sl_hit, flip) necesita `journal_trades` para poder leer
    el precio de entrada real y el R-múltiplo ya calculado por
    `TradeJournal` — esos datos no viajan en la propia alerta, viven
    en el registro del diario una vez aplicada.

    Todos los mensajes llevan al final la firma del bot (nombre
    configurado en `infra.STRATEGY_NAME`), para poder distinguirlos
    si el mismo chat de Telegram recibe alertas de más de un bot.
    """
    d = alert.data
    ts = alert.timestamp
    symbol_clean = symbol.replace("/", "")
    footer = _footer(strategy_name)

    if alert.type in ("buy", "sell"):
        is_long = alert.type == "buy"
        dot = "⬆️" if is_long else "⬇️"
        direction = "LONG" if is_long else "SHORT"
        flip_tag = " ⚡FLIP" if d.get("flip") else ""
        chop_tag = d.get("chop_flag", "")

        entry = d.get("price")
        sl = d.get("sl")
        tp1, tp2, tp3 = d.get("tp1"), d.get("tp2"), d.get("tp3")

        sl_pct = _fmt_pct(sl, entry)
        tp1_pct = _fmt_pct(tp1, entry)
        tp2_pct = _fmt_pct(tp2, entry)
        tp3_pct = _fmt_pct(tp3, entry)

        rr1 = d.get("rr1", 0.0)
        rr2 = d.get("rr2", 0.0)
        rr3 = d.get("rr3", 0.0)

        return (
            f"{dot} <b>{symbol_clean} | {direction}</b>{flip_tag}\n"
            f"Score {d.get('quality'):.0f} | Grade {d.get('grade')} | "
            f"{d.get('regime')}{chop_tag}\n\n"
            f"💰 <b>Entrada:</b> {_fmt_price(entry)}\n"
            f"🛑 <b>Stop Loss:</b> {_fmt_price(sl)}{sl_pct}\n\n"
            f"🎯 <b>TP1:</b> {_fmt_price(tp1)}{tp1_pct} · RR {rr1:.2f}\n"
            f"🎯 <b>TP2:</b> {_fmt_price(tp2)}{tp2_pct} · RR {rr2:.2f}\n"
            f"🏆 <b>TP3:</b> {_fmt_price(tp3)}{tp3_pct} · RR {rr3:.2f}\n\n"
            f"⏰ {symbol} · {timeframe} · {ts}"
            f"{footer}"
        )

    if alert.type == "tp1_hit":
        return (
            f"✅ <b>{symbol_clean} — TP1 alcanzado ({_fmt_price(d.get('price'))})</b>."
            f"{footer}"
        )

    if alert.type == "tp2_hit":
        return (
            f"🔥 <b>{symbol_clean} — TP2 alcanzado. Runner hacia TP3.</b>\n"
            f"{_fmt_price(d.get('price'))}"
            f"{footer}"
        )

    if alert.type == "be_activated":
        return (
            f"🔒 <b>{symbol_clean} — SL movido a BE ({_fmt_price(d.get('entry'))})</b>."
            f"{footer}"
        )

    # ── Eventos de CIERRE: necesitan el registro del diario ──
    trade = None
    if journal_trades is not None:
        trade = TradeJournal.find_trade(journal_trades, symbol, timeframe, d.get("entry_time"))
    entry_price = trade["entry_price"] if trade else None
    r_multiple = trade.get("r_multiple") if trade else None

    if alert.type == "tp3_hit":
        return (
            f"💎 <b>{symbol_clean} — TP3 alcanzado. Trade cerrado.</b>\n"
            f"Entrada: {_fmt_price(entry_price)} | Cierre: {_fmt_price(d.get('price'))}\n"
            f"Resultado: ✅ GANADORA ({_fmt_r(r_multiple)})"
            f"{footer}"
        )

    if alert.type == "sl_hit":
        is_be = bool(d.get("be_stop"))
        is_win = trade is not None and trade.get("result") == "win"
        icon = "🛡️" if is_be else "🛑"
        title = "Cierre en Break-Even. Trade cerrado." if is_be else "SL alcanzado. Trade cerrado."
        resultado = "✅ GANADORA" if is_win else "❌ PERDEDORA"
        return (
            f"{icon} <b>{symbol_clean} — {title}</b>\n"
            f"Entrada: {_fmt_price(entry_price)} | Cierre: {_fmt_price(d.get('sl'))}\n"
            f"Resultado: {resultado} ({_fmt_r(r_multiple)})"
            f"{footer}"
        )

    if alert.type == "flip":
        is_win = trade is not None and trade.get("result") == "win"
        resultado = "✅ GANADORA" if is_win else "❌ PERDEDORA"
        return (
            f"🔄 <b>{symbol_clean} — Señal contraria. Trade cerrado "
            f"({d.get('from_dir')}→{d.get('to_dir')}).</b>\n"
            f"Entrada: {_fmt_price(entry_price)} | Cierre: {_fmt_price(d.get('new_entry'))}\n"
            f"Resultado: {resultado} ({_fmt_r(r_multiple)})"
            f"{footer}"
        )

    return f"⚠️ Evento no reconocido: {alert.type} @ {ts}{footer}"


def format_tp1_be_combo(
    tp1_alert: Alert, be_alert: Alert, symbol: str, strategy_name: str
) -> str:
    """
    TP1 y Break-Even se activan siempre en la MISMA vela (el BE se
    dispara justo cuando TP1 se toca por primera vez), así que se
    combinan en un único mensaje — igual que el estilo de referencia:

        ✅ SYMBOL — TP1 alcanzado (precio).
        🔒 SL movido a BE (precio).
    """
    symbol_clean = symbol.replace("/", "")
    return (
        f"✅ <b>{symbol_clean} — TP1 alcanzado "
        f"({_fmt_price(tp1_alert.data.get('price'))})</b>.\n"
        f"🔒 SL movido a BE ({_fmt_price(be_alert.data.get('entry'))})."
        f"{_footer(strategy_name)}"
    )


# ══════════════════════════════════════════════════════════
# Motor
# ══════════════════════════════════════════════════════════

class Engine:
    def __init__(self, infra: InfraConfig, pine_cfg: PineConfig):
        self.infra = infra
        self.pine_cfg = pine_cfg
        self.market_data = MarketData(infra.EXCHANGE_ID)
        self.strategy = SynapseTrailPro(pine_cfg)
        self.telegram = TelegramBot(infra.TELEGRAM_BOT_TOKEN, infra.TELEGRAM_CHAT_ID)
        self.state_manager = StateManager(infra.STATE_FILE)
        self.journal = TradeJournal(infra.JOURNAL_FILE)

    def run(self) -> List[Alert]:
        """
        Recorre TODAS las monedas de `infra.SYMBOLS` (una por una) y
        ejecuta el análisis completo para cada una. Un fallo en una
        moneda (datos insuficientes, error del exchange, etc.) no
        interrumpe el análisis del resto — se registra y se continúa.
        """
        infra = self.infra
        all_alerts: List[Alert] = []

        logger.info(
            "Ejecutando %s | exchange=%s | %d moneda(s) | timeframe=%s | lookback=%d velas",
            infra.STRATEGY_NAME, infra.EXCHANGE_ID, len(infra.SYMBOLS), infra.TIMEFRAME, infra.LOOKBACK_BARS,
        )

        # ── FIX: este chequeo faltaba en esta versión del archivo.
        # Solo avisa en el log; el corte real del envío pasa más abajo,
        # en should_notify, dentro de _run_for_symbol().
        if not infra.TELEGRAM_ENABLED:
            logger.info(
                "TELEGRAM_ENABLED=False — no se enviará ningún mensaje a "
                "Telegram esta ejecución. La estrategia, el diario de "
                "operaciones (trades.json) y el dedupe de estado siguen "
                "funcionando con normalidad."
            )

        if infra.EXCHANGE_ID.lower() == "binance":
            logger.warning(
                "EXCHANGE_ID='binance' — Binance bloquea (HTTP 451) el acceso "
                "público desde IPs de datacenter/CI, incluidas las de GitHub "
                "Actions. Si tu intención era usar otro exchange (ej. 'bitget'), "
                "revisa que la Repository VARIABLE 'EXCHANGE_ID' esté creada en "
                "Settings → Secrets and variables → Actions → pestaña "
                "'Variables' (NO en 'Secrets') con el valor correcto."
            )

        for symbol in infra.SYMBOLS:
            try:
                alerts = self._run_for_symbol(symbol)
                all_alerts.extend(alerts)
            except Exception:
                logger.exception("Fallo analizando %s — se continúa con la siguiente moneda.", symbol)

        return all_alerts

    def _run_for_symbol(self, symbol: str) -> List[Alert]:
        infra = self.infra
        logger.info("── Analizando %s (%s) ──", symbol, infra.TIMEFRAME)

        base_df, htf_df = self.market_data.get_base_and_htf(
            symbol=symbol,
            timeframe=infra.TIMEFRAME,
            htf_timeframe=self.pine_cfg.htfTfInput,
            limit=infra.LOOKBACK_BARS,
        )

        min_bars_needed = max(
            self.pine_cfg.atrLenInput,
            self.pine_cfg.trailLenInput,
            self.pine_cfg.regimeLenInput,
        ) + 10

        if len(base_df) < min_bars_needed:
            logger.error(
                "[%s] Datos insuficientes: %d velas recibidas, se necesitan al menos %d.",
                symbol, len(base_df), min_bars_needed,
            )
            return []

        results, alerts = self.strategy.calculate(base_df, htf_df)

        # ── Filtro anti-flood en la primera ejecución (por símbolo) ──
        # Como el historial completo se recalcula en cada corrida, sin este
        # filtro la PRIMERA ejecución de CADA moneda enviaría a Telegram
        # cada señal de todo el histórico descargado. Solo nos interesan
        # las alertas de velas posteriores a la última vela ya procesada
        # para ESE símbolo en una ejecución previa. Si es la primera vez
        # (no hay estado previo para ese símbolo), solo se consideran las
        # alertas de la ÚLTIMA vela cerrada.
        state = self.state_manager.load()
        key = self.state_manager.symbol_key(symbol, infra.TIMEFRAME)
        prev_ts = state.last_processed_by_key.get(key)

        if prev_ts:
            cutoff = pd.Timestamp(prev_ts)
            alerts = [a for a in alerts if pd.Timestamp(a.timestamp) > cutoff]
        elif results:
            last_ts = results[-1].timestamp
            alerts = [a for a in alerts if pd.Timestamp(a.timestamp) == pd.Timestamp(last_ts)]

        if infra.DEBUG and results:
            last = results[-1]
            logger.info(
                "[DEBUG][%s] %s | close=%.6g | dir=%d | regime=%s (%.1f) | RSI=%.1f | "
                "HTF=%s | activeDir=%d | buyPasses=%s | sellPasses=%s",
                symbol, last.timestamp, last.close, last.dir, last.regime_label,
                last.regime_score, last.rsi, last.htf_bias, last.active_dir,
                last.buy_passes, last.sell_passes,
            )

        sent_count = 0
        journal_trades = self.journal.load()

        # ── Diario: se registra SIEMPRE cada evento, en orden cronológico,
        #    incluso si su notificación está desactivada — así las
        #    estadísticas de acierto no pierden datos.
        for alert in alerts:
            self.journal.apply_alert(journal_trades, symbol, infra.TIMEFRAME, alert)

        # ── Agrupar TP1 + Break-Even en un único mensaje ──
        # Ambos se disparan siempre en la MISMA vela (el BE se activa
        # justo cuando TP1 se toca por primera vez), así que se envían
        # como un solo mensaje combinado en vez de dos separados.
        by_bar: Dict[int, List[Alert]] = {}
        for alert in alerts:
            by_bar.setdefault(alert.bar_index, []).append(alert)

        units: List[tuple] = []  # (kind, [alerts])
        for bar_idx in sorted(by_bar.keys()):
            group = by_bar[bar_idx]
            tp1 = next((a for a in group if a.type == "tp1_hit"), None)
            be = next((a for a in group if a.type == "be_activated"), None)
            if tp1 and be:
                units.append(("tp1_be_combo", [tp1, be]))
                for a in group:
                    if a is not tp1 and a is not be:
                        units.append((a.type, [a]))
            else:
                for a in group:
                    units.append((a.type, [a]))

        for kind, unit_alerts in units:
            alert_ids = [
                self.state_manager.alert_id(symbol, infra.TIMEFRAME, a.timestamp, a.type)
                for a in unit_alerts
            ]
            if all(self.state_manager.already_sent(state, aid) for aid in alert_ids):
                continue

            # ── FIX: faltaba "infra.TELEGRAM_ENABLED and" aquí. Sin esto,
            # el flag global nunca se comprobaba y el bot seguía enviando
            # mensajes aunque TELEGRAM_ENABLED estuviera en False.
            should_notify = infra.TELEGRAM_ENABLED and any(
                a.data.get("notify", True) for a in unit_alerts
            )
            if not should_notify:
                for aid in alert_ids:
                    self.state_manager.mark_sent(state, aid)
                continue

            if kind == "tp1_be_combo":
                message = format_tp1_be_combo(unit_alerts[0], unit_alerts[1], symbol, infra.STRATEGY_NAME)
            else:
                message = format_alert_message(
                    unit_alerts[0], symbol, infra.TIMEFRAME, infra.STRATEGY_NAME,
                    journal_trades=journal_trades,
                )

            if infra.DEBUG:
                logger.info("[DEBUG][%s] Nueva alerta (%s): %s\n%s", symbol, kind, alert_ids, message)

            ok = send_signal(self.telegram, message)
            if ok:
                sent_count += 1
            # Se marca como enviada incluso si Telegram falló momentáneamente
            # SOLO cuando no hay credenciales configuradas se deja tal cual
            # para reintentar; si hay credenciales pero falla la red,
            # preferimos no perder la alerta -> no la marcamos como enviada.
            if ok or not self.telegram.is_configured:
                for aid in alert_ids:
                    self.state_manager.mark_sent(state, aid)

        self.journal.save(journal_trades)

        if results:
            state.last_processed_by_key[key] = str(results[-1].timestamp)

        self.state_manager.save(state)

        logger.info(
            "[%s] Completado. %d alertas nuevas en historial, %d enviadas.",
            symbol, len(alerts), sent_count,
        )

        return alerts