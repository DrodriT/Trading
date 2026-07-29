"""
bitget_executor.py — Ejecución de operaciones en la cuenta DEMO de Bitget
para la estrategia Rodri v1.0.
"""
import ccxt
import time

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
    value = usdt.get("free", None)
    if value is None:
        value = usdt.get("total", 0.0)
    return float(value or 0.0)

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

def wait_for_position(exchange, symbol: str, timeout: int = 10, interval: float = 0.5) -> bool:
    """Espera a que la posición se abra (contracts > 0). Retorna True si se abre, False si timeout."""
    start = time.time()
    while time.time() - start < timeout:
        size = get_open_position_size(exchange, symbol)
        if size > 0:
            print(f"[wait_for_position] Posición detectada: {size} {symbol}")
            return True
        time.sleep(interval)
    print(f"[wait_for_position] Timeout esperando posición en {symbol}")
    return False

def cancel_order_safe(exchange, symbol: str, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo cancelar la orden {order_id} en {symbol}: {e}")

def place_sl_order(exchange, symbol, direction, sl_price, size):
    """Coloca una orden stop-loss (reduceOnly) usando stop-market."""
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

def place_tp_order(exchange, symbol, direction, tp_price, size):
    """Coloca una orden take-profit (reduceOnly) límite."""
    side = 'sell' if direction == "ALCISTA" else 'buy'
    order = exchange.create_order(
        symbol=symbol,
        type='limit',
        side=side,
        amount=size,
        price=tp_price,
        params={'reduceOnly': True}
    )
    return order

def open_position(exchange, symbol: str, direction: str, leverage: int,
                   entry_price: float, sl_price: float, tp_prices: list,
                   risk_pct: float, tp_split=(1 / 3, 1 / 3, 1 / 3)) -> dict:
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    # 1. Orden de entrada (market)
    entry_order = exchange.create_order(symbol, "market", entry_side, size)
    print(f"[open_position] Orden de entrada enviada: {entry_order.get('id')}")

    # 2. Esperar a que la posición se abra realmente
    if not wait_for_position(exchange, symbol, timeout=15):
        raise RuntimeError(f"No se pudo confirmar la apertura de la posición en {symbol}")

    # 3. SL (stop)
    sl_order = place_sl_order(exchange, symbol, direction, sl_price, size)

    # 4. TPs (limit)
    tp_orders = []
    remaining = size
    last_i = len(tp_prices) - 1
    for i, (tp_price, split) in enumerate(zip(tp_prices, tp_split)):
        tp_size = round(remaining, 8) if i == last_i else float(exchange.amount_to_precision(symbol, size * split))
        remaining = round(remaining - tp_size, 8)
        tp_order = place_tp_order(exchange, symbol, direction, tp_price, tp_size)
        tp_orders.append({"order_id": tp_order.get("id"), "price": tp_price, "size": tp_size})

    return {
        "entry_order_id": entry_order.get("id"),
        "size": size,
        "sl_order_id": sl_order.get("id"),
        "tp_orders": tp_orders,
    }

def move_sl_to_be(exchange, symbol: str, direction: str, old_sl_order_id, new_sl_price: float,
                   size: float):
    cancel_order_safe(exchange, symbol, old_sl_order_id)
    try:
        new_sl_order = place_sl_order(exchange, symbol, direction, new_sl_price, size)
        return new_sl_order.get("id")
    except Exception as e:
        print(f"[bitget_executor] ERROR moviendo SL a BE en {symbol}: {e}")
        return None

def close_remaining_position(exchange, symbol: str, direction: str,
                              sl_order_id=None, tp_order_ids=None):
    close_side = "sell" if direction == "ALCISTA" else "buy"

    cancel_order_safe(exchange, symbol, sl_order_id)
    for tp_id in (tp_order_ids or []):
        cancel_order_safe(exchange, symbol, tp_id)

    remaining = get_open_position_size(exchange, symbol)
    if remaining > 0:
        try:
            return exchange.create_order(symbol, "market", close_side, remaining,
                                          params={"reduceOnly": True})
        except Exception as e:
            print(f"[bitget_executor] ERROR cerrando el resto de la posición en {symbol}: {e}")
    return None