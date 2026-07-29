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
    """Devuelve (size, entry_price) de la posición abierta para el símbolo."""
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
    Abre la posición con orden LIMIT y coloca SL con reintentos y temporizador.
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
    print(f"[bitget_executor] Orden de entrada enviada. ID: {entry_order.get('id')}")

    # 2. Colocar SL con temporizador y reintentos (máx 10s)
    start_time = time.time()
    timeout = 10  # segundos
    sl_order = None
    attempt = 0

    while time.time() - start_time < timeout:
        attempt += 1
        try:
            sl_order = place_sl_order(exchange, symbol, direction, sl_price, size)
            print(f"[bitget_executor] SL colocado en intento {attempt}")
            break
        except Exception as e:
            error_msg = str(e)
            if "No position available to close" in error_msg:
                print(f"[bitget_executor] Intento {attempt}: posición aún no disponible, esperando 0.5s...")
                time.sleep(0.5)
            else:
                print(f"[bitget_executor] Intento {attempt} falló con error inesperado: {e}")
                # Si es otro error, reintentamos igualmente
                time.sleep(0.5)

    if sl_order is None:
        # Si no se pudo colocar el SL, cancelamos la orden de entrada para no dejar posición sin protección
        try:
            exchange.cancel_order(entry_order.get('id'), symbol)
            print("[bitget_executor] Orden de entrada cancelada por fallo en SL.")
        except:
            pass
        raise RuntimeError("No se pudo colocar el SL después de varios intentos (timeout).")

    # Verificar que la posición realmente se abrió
    current_size, actual_entry = get_open_position_info(exchange, symbol)
    if current_size <= 0:
        print("[bitget_executor] Advertencia: no se detectó posición abierta aunque el SL se colocó.")
        # Podríamos cancelar SL y lanzar error, pero quizás la posición se abrirá después
        # Por ahora, continuamos y confiamos en que la orden se ejecutará.

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
    """Mueve el SL a break-even (precio de entrada) para la cantidad restante."""
    current_size, _ = get_open_position_info(exchange, state["symbol"])
    if current_size <= 0:
        print("[bitget_executor] No hay posición abierta, no se puede mover SL.")
        return None

    cancel_order_safe(exchange, state["symbol"], state["sl_order_id"])

    try:
        new_sl = place_sl_order(exchange, state["symbol"], state["direction"],
                                 state["entry_price"], current_size)
        state["sl_order_id"] = new_sl.get("id")
        state["sl_price"] = state["entry_price"]
        return new_sl.get("id")
    except Exception as e:
        print(f"[bitget_executor] Error al mover SL a BE: {e}")
        return None

def close_partial(exchange, state, amount, move_sl_to_be_after=False):
    """Cierra una cantidad parcial y opcionalmente mueve SL a BE."""
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
        new_size = current_size - amount
        state["size"] = new_size

        if move_sl_to_be_after and new_size > 0:
            move_sl_to_be(exchange, state)
        return order
    except Exception as e:
        print(f"[bitget_executor] ERROR al cerrar parcial: {e}")
        return None

def close_remaining_position(exchange, state):
    """Cierra toda la posición restante y cancela el SL."""
    cancel_order_safe(exchange, state["symbol"], state["sl_order_id"])
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