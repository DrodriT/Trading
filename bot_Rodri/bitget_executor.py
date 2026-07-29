"""
bitget_executor.py — Ejecución de operaciones en Bitget demo.
Abre posición con SL, permite cierres parciales y mover SL a BE.
"""
import ccxt
import time
import logging

logger = logging.getLogger(__name__)

def create_demo_exchange(api_key: str, api_secret: str, api_password: str):
    exchange = ccxt.bitget({
        "apiKey": api_key,
        "secret": api_secret,
        "password": api_password,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    exchange.headers = dict(exchange.headers or {})
    exchange.headers["PAPTRADING"] = "1"
    return exchange

def get_usdt_balance(exchange) -> float:
    balance = exchange.fetch_balance(params={"type": "swap"})
    usdt = balance.get("USDT", {})
    return float(usdt.get("free", 0.0) or 0.0)

def set_leverage(exchange, symbol: str, leverage: int):
    try:
        exchange.set_leverage(leverage, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo fijar leverage {leverage}x en {symbol}: {e}")

def calculate_position_size(balance: float, entry_price: float, sl_price: float,
                             risk_pct: float) -> float:
    risk_amount = balance * (risk_pct / 100.0)
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0
    return risk_amount / sl_distance

def get_open_position_info(exchange, symbol: str):
    """
    Devuelve (size, entry_price) de la posición abierta para el símbolo.
    Si no hay posición, devuelve (0, None).
    """
    try:
        positions = exchange.fetch_positions([symbol])
        for p in positions:
            contracts = p.get("contracts") or 0
            if contracts:
                return float(contracts), float(p.get("entryPrice", 0))
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo consultar la posición en {symbol}: {e}")
    return 0.0, None

def place_sl_order(exchange, symbol, direction, sl_price, size):
    """Orden stop-market reduceOnly para el SL."""
    side = 'sell' if direction == "ALCISTA" else 'buy'
    order = exchange.create_order(
        symbol=symbol,
        type='stop',
        side=side,
        amount=size,
        price=None,
        params={
            'stopPrice': sl_price,
            'reduceOnly': True,
            'orderType': 'market',
        }
    )
    return order

def open_position(exchange, symbol: str, direction: str, leverage: int,
                   entry_price: float, sl_price: float, risk_pct: float) -> dict:
    """
    Abre la posición con orden LIMIT y coloca SL (con reintentos).
    """
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    # 1. ORDEN DE ENTRADA (límite)
    entry_order = exchange.create_order(
        symbol=symbol,
        type='limit',
        side=entry_side,
        amount=size,
        price=entry_price,
    )

    # 2. Colocar SL con reintentos (hasta 5 veces, esperando 1s entre intentos)
    sl_order = None
    for attempt in range(5):
        try:
            sl_order = place_sl_order(exchange, symbol, direction, sl_price, size)
            break
        except Exception as e:
            print(f"[bitget_executor] Intento {attempt+1} de SL falló: {e}")
            time.sleep(1)
    if sl_order is None:
        raise RuntimeError("No se pudo colocar el SL después de varios intentos.")

    return {
        "entry_order_id": entry_order.get("id"),
        "size": size,
        "sl_order_id": sl_order.get("id"),
        "sl_price": sl_price,
        "entry_price": entry_price,
        "direction": direction,
        "symbol": symbol,
    }

def cancel_order_safe(exchange, symbol: str, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo cancelar la orden {order_id} en {symbol}: {e}")

def move_sl_to_be(exchange, state):
    """
    Mueve el SL a break-even (precio de entrada) para la cantidad restante.
    state debe contener: symbol, direction, entry_price, sl_order_id, size.
    Devuelve el nuevo ID del SL o None si falla.
    """
    # Obtener la cantidad actual (puede haber cambiado si se cerró parcialmente)
    current_size, _ = get_open_position_info(exchange, state["symbol"])
    if current_size <= 0:
        print("[bitget_executor] No hay posición abierta, no se puede mover SL.")
        return None

    # Cancelar SL antiguo
    cancel_order_safe(exchange, state["symbol"], state["sl_order_id"])

    # Colocar nuevo SL en BE (entry_price)
    try:
        new_sl = place_sl_order(exchange, state["symbol"], state["direction"],
                                 state["entry_price"], current_size)
        # Actualizar estado
        state["sl_order_id"] = new_sl.get("id")
        state["sl_price"] = state["entry_price"]
        return new_sl.get("id")
    except Exception as e:
        print(f"[bitget_executor] Error al mover SL a BE: {e}")
        return None

def close_partial(exchange, state, amount, move_sl_to_be_after=False):
    """
    Cierra una cantidad parcial de la posición (reduceOnly) al precio de mercado.
    Si move_sl_to_be_after es True, mueve el SL a BE después del cierre.
    state se actualiza en el lugar (sl_order_id, size).
    Devuelve la orden de cierre o None.
    """
    # Verificar cantidad actual
    current_size, _ = get_open_position_info(exchange, state["symbol"])
    if current_size <= 0:
        print("[bitget_executor] No hay posición abierta para cerrar.")
        return None

    if amount > current_size:
        print(f"[bitget_executor] Advertencia: se intenta cerrar {amount} pero solo hay {current_size}. Se cerrará todo.")
        amount = current_size

    close_side = "sell" if state["direction"] == "ALCISTA" else "buy"
    try:
        order = exchange.create_order(state["symbol"], "market", close_side, amount,
                                      params={"reduceOnly": True})
        # Actualizar tamaño en estado (aproximado)
        new_size = current_size - amount
        state["size"] = new_size

        # Si se pidió mover SL a BE y queda posición, moverlo
        if move_sl_to_be_after and new_size > 0:
            move_sl_to_be(exchange, state)
        return order
    except Exception as e:
        print(f"[bitget_executor] ERROR al cerrar parcial: {e}")
        return None

def close_remaining_position(exchange, state):
    """Cierra toda la posición restante y cancela el SL."""
    # Cancelar SL
    cancel_order_safe(exchange, state["symbol"], state["sl_order_id"])
    # Obtener tamaño actual
    current_size, _ = get_open_position_info(exchange, state["symbol"])
    if current_size > 0:
        close_side = "sell" if state["direction"] == "ALCISTA" else "buy"
        try:
            order = exchange.create_order(state["symbol"], "market", close_side, current_size,
                                          params={"reduceOnly": True})
            state["size"] = 0
            return order
        except Exception as e:
            print(f"[bitget_executor] ERROR cerrando el resto de la posición: {e}")
    return None