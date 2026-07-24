# ============================================================
# BOT PRINCIPAL — Rodri bot
# Loop: fetch data → compute signals → manage positions → execute
# ============================================================
import sys
import time
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Optional

import ccxt
import pandas as pd
import numpy as np

import config as cfg
from strategy import SynapseStrategy, StateManager, PositionState

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("synapse_bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("synapse_bot")


# ============================================================
# TELEGRAM
# ============================================================
class TelegramNotifier:
    """Envía mensajes por Telegram."""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id and "PON_AQUI" not in token)

    def send(self, text: str):
        if not self.enabled:
            logger.info(f"[Telegram OFF] {text}")
            return
        try:
            import requests
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                logger.error(f"Telegram error: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram exception: {e}")


# ============================================================
# EXCHANGE CONNECTOR
# ============================================================
class ExchangeConnector:
    """Maneja la conexión con Bitget."""

    def __init__(self):
        self.exchange = ccxt.bitget({
            "apiKey": cfg.API_KEY,
            "secret": cfg.API_SECRET,
            "password": cfg.API_PASSWORD,
            "options": {"defaultType": cfg.MARKET_TYPE},
            "enableRateLimit": True,
        })
        logger.info(f"Conectado a {cfg.EXCHANGE_ID} ({cfg.MARKET_TYPE})")

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """Obtiene OHLCV como DataFrame."""
        try:
            candles = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"Error fetching {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def fetch_ticker(self, symbol: str) -> float:
        """Obtiene el último precio."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker["last"]
        except Exception:
            return 0.0

    def get_balance(self, quote="USDT") -> float:
        """Obtiene balance disponible en USDT."""
        try:
            balance = self.exchange.fetch_balance()
            return balance.get(quote, {}).get("free", 0.0)
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0.0

    def set_leverage(self, symbol: str, leverage: int):
        """Configura el apalancamiento para un símbolo."""
        try:
            self.exchange.set_leverage(leverage, symbol)
        except Exception as e:
            logger.warning(f"No se pudo setear leverage {leverage}x para {symbol}: {e}")

    def execute_market_order(self, symbol: str, side: str, amount_usd: float) -> Optional[dict]:
        """
        Ejecuta orden de mercado.
        side: 'buy' o 'sell'
        amount_usd: tamaño en USDT
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker["last"]
            amount = amount_usd / price

            # Redondear según specs del exchange
            market = self.exchange.market(symbol)
            amount = self.exchange.amount_to_precision(symbol, amount)

            order = self.exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=amount,
            )
            logger.info(f"ORDEN {side.upper()} {symbol}: {amount} @ ~{price:.4f} → ID: {order.get('id', '?')}")
            return order
        except Exception as e:
            logger.error(f"Error ejecutando orden {side} {symbol}: {e}")
            return None

    def execute_limit_order(self, symbol: str, side: str, amount_usd: float,
                            price: float) -> Optional[dict]:
        """Ejecuta orden límite (para TP/SL simulados)."""
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker["last"]
            amount = amount_usd / current_price

            market = self.exchange.market(symbol)
            amount = self.exchange.amount_to_precision(symbol, amount)
            price = self.exchange.price_to_precision(symbol, price)

            order = self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side=side,
                amount=amount,
                price=price,
            )
            return order
        except Exception as e:
            logger.error(f"Error orden límite {side} {symbol} @ {price}: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: str):
        """Cancela una orden por ID."""
        try:
            self.exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.warning(f"Error cancelando orden {order_id}: {e}")


# ============================================================
# ORDENADOR DE POSICIONES (ENTRADAS ESCALONADAS)
# ============================================================

class PositionExecutor:
    """
    Ejecuta las 3 entradas escalonadas y gestiona los cierres parciales.
    """

    def __init__(self, connector: ExchangeConnector, notifier: TelegramNotifier):
        self.connector = connector
        self.notifier = notifier

    def open_scaled_entries(self, symbol: str, direction: int, capital_usd: float):
        """
        Abre 3 órdenes de mercado escalonadas.
        Cada una = capital_usd / 3.
        """
        side = "buy" if direction == 1 else "sell"
        split_size = capital_usd / cfg.ENTRY_SPLITS

        orders = []
        for i in range(cfg.ENTRY_SPLITS):
            order = self.connector.execute_market_order(symbol, side, split_size)
            if order:
                orders.append(order.get("id", ""))
            time.sleep(0.5)  # Pequeña pausa entre órdenes

        return orders

    def close_position(self, symbol: str, direction: int, size_pct: float = 1.0):
        """
        Cierra un porcentaje de la posición.
        size_pct: 0.33 para cerrar 1/3, 1.0 para cerrar todo.
        """
        side = "sell" if direction == 1 else "buy"  # Cerrar = lado contrario
        # El cierre es simplificado: market order por el % del capital
        # En producción, calcularías el tamaño exacto del contrato
        try:
            # Obtenemos la posición actual
            positions = self.connector.exchange.fetch_positions([symbol])
            for pos in positions:
                if float(pos.get("contracts", 0)) > 0:
                    # Cerrar con orden de mercado en dirección contraria
                    close_order = self.connector.exchange.create_order(
                        symbol=symbol,
                        type="market",
                        side=side,
                        amount=abs(float(pos["contracts"])) * size_pct,
                        reduceOnly=True
                    )
                    return close_order
        except Exception as e:
            logger.error(f"Error cerrando posición {symbol}: {e}")
        return None


# ============================================================
# BOT LOOP
# ============================================================

class SynapseBot:
    """
    Bot principal: coordina el loop de trading.
    """

    def __init__(self):
        self.connector = ExchangeConnector()
        self.notifier = TelegramNotifier(cfg.TELEGRAM_TOKEN, cfg.TELEGRAM_CHAT_ID)
        self.state = StateManager()
        self.strategy = SynapseStrategy(self.state, self.connector.exchange)
        self.executor = PositionExecutor(self.connector, self.notifier)

        # Track de velas procesadas
        self.last_candle_ts: Dict[str, int] = {}

    def send_startup_message(self):
        """Mensaje de arranque por Telegram."""
        balance = self.connector.get_balance()
        msg = (
            f"🤖 <b>{cfg.STRATEGY_LABEL}</b> INICIADO\n"
            f"Exchange: {cfg.EXCHANGE_ID} | TF: {cfg.TIMEFRAME} | HTF: {cfg.CONFIRM_TIMEFRAME}\n"
            f"Preset: {cfg.RISK_PRESET} | SL={cfg.SL_MULT}×ATR | "
            f"TP={cfg.TP1_MULT}R/{cfg.TP2_MULT}R/{cfg.TP3_MULT}R\n"
            f"Símbolos: {len(cfg.SYMBOLS)} | Balance: ${balance:.2f}"
        )
        self.notifier.send(msg)

    def has_new_candle(self, symbol: str, df: pd.DataFrame) -> bool:
        """Detecta si hay una vela nueva (no procesada)."""
        if df.empty:
            return False
        last_ts = df.index[-1].timestamp()
        if symbol not in self.last_candle_ts or self.last_candle_ts[symbol] < last_ts:
            self.last_candle_ts[symbol] = last_ts
            return True
        return False

    def process_symbol(self, symbol: str):
        """Procesa un símbolo: fetch → analyze → execute."""
        try:
            # --- Fetch data ---
            df = self.connector.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
            if df.empty or len(df) < 50:
                return

            # HTF data
            htf_df = None
            if cfg.USE_HTF_FILTER:
                htf_df = self.connector.fetch_ohlcv(symbol, cfg.CONFIRM_TIMEFRAME, limit=200)

            # Solo procesar en vela nueva
            if not self.has_new_candle(symbol, df):
                return

            # --- Calcular señal ---
            signal = self.strategy.get_signal(symbol, df, htf_df)
            logger.debug(f"{symbol}: dir={signal['direction']} grade={signal['grade']} "
                         f"regime={signal['regime_label']} quality={signal['quality_score']:.0f}")

            existing_pos = self.state.get_position(symbol)

            # --- Si hay señal nueva ---
            if signal["direction"] != 0:
                if signal["flip"] and existing_pos:
                    # Cerrar posición existente (flip)
                    logger.info(f"FLIP {symbol}: cerrando posición {existing_pos.direction} → nueva {signal['direction']}")
                    self.executor.close_position(symbol, existing_pos.direction)
                    self.state.close_position(symbol)

                if not self.state.has_position(symbol):
                    # Abrir nueva posición
                    atr = compute_atr(df, cfg.ATR_LEN)  # Necesitamos ATR para SL
                    atr_val = atr.iloc[-1] if not atr.empty else 0.01
                    entry_price = df["close"].values[-1]

                    # Calcular tamaño según riesgo
                    balance = self.connector.get_balance()
                    capital_per_trade = balance * (cfg.RISK_PER_TRADE_PCT / 100.0)

                    # Set leverage
                    self.connector.set_leverage(symbol, cfg.LEVERAGE)

                    # Abrir posición (tracking interno)
                    pos = self.strategy.open_position(
                        symbol=symbol,
                        direction=signal["direction"],
                        entry_price=entry_price,
                        quality_score=signal["quality_score"],
                        grade=signal["grade"],
                        bar_time=len(df) - 1,
                        atr_value=atr_val
                    )

                    # Ejecutar 3 entradas escalonadas
                    orders = self.executor.open_scaled_entries(
                        symbol, signal["direction"], capital_per_trade
                    )
                    pos.orders_ids = orders

                    # Notificar
                    direction_str = "🟢 LONG" if signal["direction"] == 1 else "🔴 SHORT"
                    msg = (
                        f"{direction_str} <b>{symbol}</b>\n"
                        f"Precio: {entry_price:.4f} | Grade: {signal['grade']} "
                        f"({signal['quality_score']:.0f}/100)\n"
                        f"SL: {pos.sl:.4f} | TP1: {pos.tp1:.4f} | "
                        f"TP2: {pos.tp2:.4f} | TP3: {pos.tp3:.4f}\n"
                        f"Régimen: {signal['regime_label']} "
                        f"({'⚠️Choppy' if signal['is_choppy'] else '✅Trending' if signal['is_trending'] else 'Mixed'})"
                    )
                    self.notifier.send(msg)

            # --- Monitorear posición existente ---
            if existing_pos:
                exit_event = self.strategy.check_exits(symbol, df)

                if exit_event:
                    event = exit_event["event"]
                    price = exit_event["price"]

                    if event == "sl":
                        # Cerrar posición completa
                        self.executor.close_position(symbol, existing_pos.direction)
                        self.state.close_position(symbol)
                        msg = (
                            f"{'🛡️ BE' if existing_pos.be_active else '🛑 SL'} "
                            f"<b>{symbol}</b> @ {price:.4f}"
                        )
                        self.notifier.send(msg)

                    elif event == "tp1":
                        # Cerrar 1/3
                        self.executor.close_position(symbol, existing_pos.direction, 1/3)
                        msg = f"🎯 TP1 <b>{symbol}</b> @ {price:.4f}"
                        self.notifier.send(msg)

                    elif event == "tp2":
                        self.executor.close_position(symbol, existing_pos.direction, 1/3)
                        msg = f"🎯🎯 TP2 <b>{symbol}</b> @ {price:.4f}"
                        self.notifier.send(msg)

                    elif event == "tp3":
                        self.executor.close_position(symbol, existing_pos.direction, 1/3)
                        self.state.close_position(symbol)
                        msg = f"🏆 TP3 <b>{symbol}</b> @ {price:.4f} ✅ POSICIÓN CERRADA"
                        self.notifier.send(msg)

            # --- Actualizar estado ---
            self.state.save()

        except Exception as e:
            logger.error(f"Error procesando {symbol}: {e}")
            traceback.print_exc()

    def run_once(self):
        """Ejecuta una iteración sobre todos los símbolos."""
        for symbol in cfg.SYMBOLS:
            self.process_symbol(symbol)
            time.sleep(1)  # Rate limiting entre símbolos

    def run_loop(self):
        """Loop principal."""
        logger.info("=" * 50)
        logger.info(f"Iniciando {cfg.STRATEGY_LABEL}")
        logger.info("=" * 50)

        self.send_startup_message()

        while True:
            try:
                self.run_once()
                logger.info(f"Ciclo completado. Esperando {cfg.CHECK_INTERVAL_SECONDS}s...")
                time.sleep(cfg.CHECK_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("Bot detenido por usuario")
                self.notifier.send(f"🛑 {cfg.STRATEGY_LABEL} DETENIDO")
                break
            except Exception as e:
                logger.error(f"Error en loop principal: {e}")
                traceback.print_exc()
                time.sleep(30)


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    bot = SynapseBot()
    bot.run_loop()