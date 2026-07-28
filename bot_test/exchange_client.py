"""
Envoltorio sobre ccxt para Bitget — cuenta DEMO, swap USDT-M, aislado.

⚠️ IMPORTANTE — LEE ESTO ANTES DE USARLO CON DINERO (incluso demo):
Este módulo asume una serie de detalles de la API de Bitget a través de
ccxt (nombres de parámetros para stop-loss/reduce-only, modo de posición
one-way vs hedge, etc.) que NO he podido probar en vivo porque no tengo
acceso a tu cuenta ni a un entorno con red hacia Bitget. Antes de dejarlo
operando solo, hay que:
  1. Correrlo primero con --dry-run (no manda órdenes, solo imprime/loguea
     lo que HARÍA) para revisar que el sizing y los niveles tienen sentido.
  2. Probar UN símbolo, UNA vez, en real-pero-demo, y verificar en el panel
     de Bitget que la orden, el apalancamiento y el modo aislado son los
     esperados, antes de dejarlo corriendo para los 13 símbolos.
  3. Revisar si tu cuenta Bitget está en modo "one-way" o "hedge" — si es
     hedge, hay que añadir posSide en los params (ver comentarios abajo).
"""
import time
import ccxt

import live_config as config


def make_exchange():
    exchange = ccxt.bitget({
        "apiKey": config.BITGET_API_KEY,
        "secret": config.BITGET_API_SECRET,
        "password": config.BITGET_API_PASSWORD,
        "enableRateLimit": True,
        "options": {"defaultType": config.MARKET_TYPE},
    })
    if config.DEMO_MODE:
        # Manda el header PAPTRADING=1 en cada request — cuenta demo.
        exchange.set_sandbox_mode(True)
    return exchange


def get_equity_usdt(exchange) -> float:
    """Equity disponible en USDT de la cuenta de swap/futuros."""
    balance = exchange.fetch_balance(params={"type": config.MARKET_TYPE})
    usdt = balance.get("USDT", {})
    # 'total' incluye posiciones abiertas valoradas; si tu cuenta reporta
    # distinto, ajusta a balance['total']['USDT'] o al campo que uses.
    return float(usdt.get("total") or usdt.get("free") or 0.0)


def prepare_market(exchange, symbol: str, leverage: int):
    """Fija modo aislado + apalancamiento para el símbolo, ANTES de abrir."""
    try:
        exchange.set_margin_mode(config.MARGIN_MODE, symbol)
    except Exception as e:
        print(f"[WARN] set_margin_mode({symbol}): {e}")
    try:
        exchange.set_leverage(leverage, symbol)
    except Exception as e:
        print(f"[WARN] set_leverage({symbol}, {leverage}): {e}")


def open_position(exchange, symbol: str, direction: str, contracts: float):
    """
    Abre la posición a mercado. direction: 'ALCISTA' (long) / 'BAJISTA' (short).
    Devuelve la orden de ccxt tal cual (incluye el precio medio de fill si
    el exchange lo reporta).
    """
    side = "buy" if direction == "ALCISTA" else "sell"
    amount = exchange.amount_to_precision(symbol, contracts)
    return exchange.create_order(symbol, "market", side, float(amount))


def place_stop_loss(exchange, symbol: str, direction: str, contracts: float, sl_price: float):
    """
    Orden de stop-loss reduce-only (trigger a mercado). El parámetro
    'stopLossPrice' es la convención unificada de ccxt para crear una
    orden de disparo — en Bitget se traduce a una plan order. Si tu
    versión de ccxt/Bitget necesita otro nombre, ajusta aquí.
    """
    close_side = "sell" if direction == "ALCISTA" else "buy"
    amount = exchange.amount_to_precision(symbol, contracts)
    price = exchange.price_to_precision(symbol, sl_price)
    return exchange.create_order(
        symbol, "market", close_side, float(amount), None,
        {"reduceOnly": True, "stopLossPrice": float(price)}
    )


def place_take_profit(exchange, symbol: str, direction: str, contracts: float, tp_price: float):
    """Orden límite reduce-only para cerrar parcialmente en un TP."""
    close_side = "sell" if direction == "ALCISTA" else "buy"
    amount = exchange.amount_to_precision(symbol, contracts)
    price = exchange.price_to_precision(symbol, tp_price)
    return exchange.create_order(
        symbol, "limit", close_side, float(amount), float(price),
        {"reduceOnly": True}
    )


def cancel_order_safe(exchange, symbol: str, order_id: str):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[WARN] cancel_order({symbol}, {order_id}): {e}")


def fetch_order_status(exchange, symbol: str, order_id: str):
    """Devuelve el dict de la orden (incluye 'status': open/closed/canceled)."""
    try:
        return exchange.fetch_order(order_id, symbol)
    except Exception as e:
        print(f"[WARN] fetch_order({symbol}, {order_id}): {e}")
        return None


def fetch_open_positions(exchange, symbols=None):
    """Lista de posiciones abiertas reales (según el exchange, no state.json)."""
    try:
        return exchange.fetch_positions(symbols)
    except Exception as e:
        print(f"[WARN] fetch_positions: {e}")
        return []
