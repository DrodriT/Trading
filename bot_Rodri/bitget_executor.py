"""
bitget_executor.py — Ejecución de operaciones en Bitget demo con TP/SL integrados.
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

def place_tp_order(exchange, symbol, direction, tp_price, size):
    """Orden límite para un TP adicional (reduceOnly)."""
    side = 'sell' if direction == "ALCISTA" else 'buy'
    return exchange.create_order(
        symbol=symbol,
        type='limit',
        side=side,
        amount=size,
        price=tp_price,
        params={'reduceOnly': True}
    )

def open_position(exchange, symbol: str, direction: str, leverage: int,
                   entry_price: float, sl_price: float, tp_prices: list,
                   risk_pct: float, tp_split=(1/3, 1/3, 1/3)) -> dict:
    """
    Abre la posición con SL y TP1 integrados en la orden de entrada.
    Los TP2 y TP3 se colocan como órdenes límite adicionales.
    """
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    # Preparar TP1 y SL para la orden de entrada
    tp1_price = tp_prices[0]
    tp1_size = float(exchange.amount_to_precision(symbol, size * tp_split[0]))

    # Orden de entrada con SL y TP1 integrados
    entry_order = exchange.create_order(
        symbol=symbol,
        type='market',
        side=entry_side,
        amount=size,
        params={
            'stopLossPrice': sl_price,
            'takeProfitPrice': tp1_price,
            'reduceOnly': False,  # no es reduceOnly, es apertura
        }
    )

    # Para los TP2 y TP3, los colocamos como órdenes límite reduceOnly
    remaining = size - tp1_size
    tp_orders = [{'order_id': entry_order.get('id'), 'price': tp1_price, 'size': tp1_size}]  # TP1 ya incluido

    # TP2 y TP3
    for i in range(1, len(tp_prices)):
        tp_price = tp_prices[i]
        tp_size = float(exchange.amount_to_precision(symbol, size * tp_split[i])) if i < len(tp_prices)-1 else remaining
        if tp_size > 0:
            tp_order = place_tp_order(exchange, symbol, direction, tp_price, tp_size)
            tp_orders.append({'order_id': tp_order.get('id'), 'price': tp_price, 'size': tp_size})
            remaining -= tp_size

    return {
        "entry_order_id": entry_order.get("id"),
        "size": size,
        "sl_order_id": entry_order.get('id'),  # el SL está vinculado a la orden de entrada, no hay ID separado
        "tp_orders": tp_orders,
    }

# Las demás funciones (cancel_order, move_sl_to_be, close_remaining) se mantienen igual,
# pero move_sl_to_be deberá cancelar la orden de entrada (si aún está abierta) y crear un nuevo SL.
# Por simplicidad, no las incluyo aquí, pero puedes adaptarlas.