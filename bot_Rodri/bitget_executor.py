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
    Abre la posición con orden LIMIT y SL/TP1 integrados.
    Los TP2 y TP3 se colocan como órdenes límite reduceOnly.
    """
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"
    pos_side = "long" if is_long else "short"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    tp1_price = tp_prices[0]
    tp1_size = float(exchange.amount_to_precision(symbol, size * tp_split[0]))

    # ── ORDEN DE ENTRADA (limit) con SL y TP1 integrados ──
    entry_order = exchange.create_order(
        symbol=symbol,
        type='limit',
        side=entry_side,
        amount=size,
        price=entry_price,
        params={
            'stopLossPrice': sl_price,
            'takeProfitPrice': tp1_price,
            'posSide': pos_side,
            'reduceOnly': False,
        }
    )

    # Pequeña espera para asegurar que la orden ha sido procesada y la posición está abierta
    time.sleep(0.5)

    # ── TP2 y TP3 como órdenes límite reduceOnly ──
    remaining = size - tp1_size
    tp_orders = [{'order_id': entry_order.get('id'), 'price': tp1_price, 'size': tp1_size}]

    for i in range(1, len(tp_prices)):
        tp_price = tp_prices[i]
        if i == len(tp_prices) - 1:
            tp_size = remaining
        else:
            tp_size = float(exchange.amount_to_precision(symbol, size * tp_split[i]))
        if tp_size > 0:
            tp_order = place_tp_order(exchange, symbol, direction, tp_price, tp_size)
            tp_orders.append({'order_id': tp_order.get('id'), 'price': tp_price, 'size': tp_size})
            remaining -= tp_size

    return {
        "entry_order_id": entry_order.get("id"),
        "size": size,
        "sl_order_id": entry_order.get('id'),  # El SL está integrado en la orden de entrada
        "tp_orders": tp_orders,
    }

# ── Funciones auxiliares para gestión posterior ──

def cancel_order_safe(exchange, symbol: str, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo cancelar la orden {order_id} en {symbol}: {e}")

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

def move_sl_to_be(exchange, symbol: str, direction: str, old_sl_order_id, new_sl_price: float,
                   size: float):
    """
    Para mover el SL a BE, necesitamos cancelar la orden de entrada (que contiene el SL)
    y crear una nueva orden de SL separada (o usar la API de modificación de órdenes).
    Como no tenemos un ID de SL independiente, la implementación más simple es
    cerrar la posición y reabrir, o usar la orden de SL independiente.
    Por ahora, dejamos esta función como esqueleto para que la adaptes.
    """
    print("[bitget_executor] Función move_sl_to_be no implementada completamente con TP/SL integrados.")
    # Implementación opcional: cancelar la orden de entrada si aún está abierta,
    # y colocar una nueva orden SL (reduceOnly) con el nuevo precio.
    # Pero esto es complejo con TP/SL integrados. Se recomienda usar la API
    # de modificación de órdenes de Bitget si es necesario.
    return None

def close_remaining_position(exchange, symbol: str, direction: str,
                              sl_order_id=None, tp_order_ids=None):
    """
    Cierra cualquier posición restante y cancela órdenes TP pendientes.
    """
    close_side = "sell" if direction == "ALCISTA" else "buy"

    # Cancelar TP2 y TP3 (TP1 ya está integrado y se cancelará al cerrar la orden)
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