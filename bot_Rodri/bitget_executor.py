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

def get_open_position_size(exchange, symbol: str) -> float:
    try:
        positions = exchange.fetch_positions([symbol])
        for p in positions:
            contracts = p.get("contracts") or 0
            if contracts:
                return float(contracts)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo consultar la posición abierta en {symbol}: {e}")
    return 0.0

def wait_for_position(exchange, symbol: str, timeout=8):
    start = time.time()
    while time.time() - start < timeout:
        pos_size = get_open_position_size(exchange, symbol)
        if pos_size > 0:
            return pos_size
        time.sleep(0.3)
    raise TimeoutError(f"No se detectó posición abierta para {symbol} después de {timeout}s")

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
    Abre la posición con orden LIMIT y coloca SL (sin TPs).
    """
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    entry_order = exchange.create_order(
        symbol=symbol,
        type='limit',
        side=entry_side,
        amount=size,
        price=entry_price,
    )

    try:
        wait_for_position(exchange, symbol, timeout=8)
    except TimeoutError as e:
        print(f"[bitget_executor] La orden de entrada puede no haberse ejecutado. {e}")
        raise

    sl_order = place_sl_order(exchange, symbol, direction, sl_price, size)

    return {
        "entry_order_id": entry_order.get("id"),
        "entry_price": entry_price,
        "size": size,
        "sl_order_id": sl_order.get("id"),
        "sl_price": sl_price,
    }

def close_partial(exchange, symbol: str, direction: str, amount: float):
    """
    Cierra una cantidad parcial de la posición (reduceOnly) al precio de mercado.
    Devuelve el tamaño realmente cerrado.
    """
    close_side = "sell" if direction == "ALCISTA" else "buy"
    current_size = get_open_position_size(exchange, symbol)
    if amount > current_size:
        print(f"[bitget_executor] Advertencia: se intenta cerrar {amount} pero solo hay {current_size}. Se cerrará todo.")
        amount = current_size
    if amount <= 0:
        return 0.0
    try:
        order = exchange.create_order(symbol, "market", close_side, amount,
                                      params={"reduceOnly": True})
        # El tamaño realmente ejecutado puede diferir ligeramente; lo obtenemos de la orden
        filled = order.get('filled', amount) if order else amount
        return float(filled)
    except Exception as e:
        print(f"[bitget_executor] ERROR al cerrar parcial: {e}")
        return 0.0

def cancel_order_safe(exchange, symbol: str, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo cancelar la orden {order_id} en {symbol}: {e}")

def update_sl_price(exchange, symbol: str, direction: str, old_sl_order_id: str,
                     new_sl_price: float, current_size: float) -> str:
    """
    Cancela la orden SL existente y coloca una nueva con el precio actualizado.
    Retorna el ID de la nueva orden SL.
    """
    # Cancelar la orden SL antigua
    cancel_order_safe(exchange, symbol, old_sl_order_id)

    # Colocar nuevo SL con el precio actualizado
    if current_size <= 0:
        print(f"[bitget_executor] No hay posición restante, no se coloca nuevo SL.")
        return None

    # Si el nuevo precio es 0 o None, significa que queremos eliminar el SL (no recomendado)
    if new_sl_price is None or new_sl_price <= 0:
        print(f"[bitget_executor] Precio SL inválido, no se coloca nuevo SL.")
        return None

    sl_order = place_sl_order(exchange, symbol, direction, new_sl_price, current_size)
    return sl_order.get("id")

def close_tp1_and_move_sl_to_be(exchange, symbol: str, direction: str,
                                  tp1_amount: float, entry_price: float,
                                  old_sl_order_id: str, old_sl_price: float) -> dict:
    """
    Ejecuta TP1 (cierra parcial) y mueve el SL al precio de entrada (break-even)
    para la posición restante.
    Retorna un dict con el tamaño cerrado, nuevo tamaño y nuevo SL ID.
    """
    # 1. Cerrar TP1
    closed = close_partial(exchange, symbol, direction, tp1_amount)
    if closed <= 0:
        print("[bitget_executor] No se pudo cerrar TP1, no se mueve SL.")
        return {"closed": 0, "remaining": 0, "new_sl_id": None}

    # 2. Obtener la posición restante
    remaining = get_open_position_size(exchange, symbol)
    if remaining <= 0:
        print("[bitget_executor] No queda posición restante, no se coloca nuevo SL.")
        return {"closed": closed, "remaining": 0, "new_sl_id": None}

    # 3. Mover SL a break-even (precio de entrada)
    new_sl_price = entry_price  # BE
    if new_sl_price == old_sl_price:
        print("[bitget_executor] El SL ya está en BE, no se modifica.")
        new_sl_id = old_sl_order_id
    else:
        new_sl_id = update_sl_price(exchange, symbol, direction, old_sl_order_id,
                                     new_sl_price, remaining)
    return {
        "closed": closed,
        "remaining": remaining,
        "new_sl_id": new_sl_id,
    }

def close_remaining_position(exchange, symbol: str, direction: str, sl_order_id=None):
    """
    Cierra toda la posición restante y cancela el SL.
    """
    cancel_order_safe(exchange, symbol, sl_order_id)
    remaining = get_open_position_size(exchange, symbol)
    if remaining > 0:
        close_side = "sell" if direction == "ALCISTA" else "buy"
        try:
            return exchange.create_order(symbol, "market", close_side, remaining,
                                          params={"reduceOnly": True})
        except Exception as e:
            print(f"[bitget_executor] ERROR cerrando el resto de la posición en {symbol}: {e}")
    return None