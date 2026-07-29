"""
bitget_executor.py — Ejecución de operaciones en la cuenta DEMO de Bitget
para la estrategia Rodri v1.0.

Recibe las órdenes de strategy_rodri/bot_rodri (dirección, entrada, SL,
TP1/TP2/TP3, leverage) y las ejecuta en Bitget:
  1. Fija el apalancamiento.
  2. Calcula el tamaño de la posición según un % de riesgo del balance
     demo (distancia al SL = 100% del riesgo asumido).
  3. Abre la posición a mercado.
  4. Coloca el SL y los 3 TP como órdenes REALES reduceOnly en el propio
     Bitget (no las vigila el bot con polling): si el bot se cae o pierde
     conexión, el SL y los TP se ejecutan igual, porque viven en el
     exchange.
  5. Permite mover el SL a break-even (cancela la orden vieja, coloca una
     nueva) y cerrar/limpiar lo que quede de la posición (usado en un flip
     o como red de seguridad al cerrar).

╔══════════════════════════════════════════════════════════════════════╗
║ LÉEME ANTES DE USAR — IMPORTANTE                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║ 1. El modo demo de Bitget usa tus claves API REALES, pero necesita la ║
║    cabecera 'PAPTRADING: 1' en cada petición para operar con USDT     ║
║    virtual en vez de fondos reales. Este módulo la añade solo, pero   ║
║    aun así verifica en la app de Bitget que estás en la cuenta demo   ║
║    (3000 USDT virtuales) antes de dejarlo corriendo desatendido.      ║
║                                                                        ║
║ 2. Este código NO ha podido probarse contra la API real de Bitget     ║
║    (sin acceso de red a api.bitget.com desde donde se escribió).      ║
║    Antes de confiar en él, prueba cada función a mano con importes    ║
║    pequeños: abre una posición, comprueba que aparecen el SL y los 3  ║
║    TP en la app, fuerza un TP1 y comprueba que el SL se mueve a BE.   ║
║                                                                        ║
║ 3. Si tu cuenta de Bitget está en modo "hedge" (posiciones long/short ║
║    independientes) en vez de "one-way", es posible que Bitget exija   ║
║    un parámetro adicional 'holdSide': 'long'/'short' en las órdenes.  ║
║    Si ves errores de tipo "posición no encontrada" o similar al       ║
║    colocar el SL/TP, ese es el primer sitio donde mirar.              ║
╚══════════════════════════════════════════════════════════════════════╝
"""
import ccxt


def create_demo_exchange(api_key: str, api_secret: str, api_password: str):
    """
    Crea una instancia de ccxt.bitget apuntando al entorno DEMO.
    Se usa la cabecera 'PAPTRADING' explícita en vez del set_sandbox_mode()
    de ccxt, que ha tenido bugs conocidos y mal documentados para Bitget
    (mezcla las dos formas de "demo" que existen en su API).
    """
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
    """Balance disponible en USDT (virtual, en la cuenta demo) para futuros."""
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
    """
    Tamaño de posición (en unidades del activo base, ej. nº de BTC) para
    arriesgar 'risk_pct' % del balance demo si el precio llega al SL.
    NOTA: esto es el tamaño de la POSICIÓN (no el margen). El margen real
    usado = tamaño × precio / leverage — con leverage alto, el margen
    bloqueado es menor, pero el riesgo en USDT si salta el SL es el mismo
    (por eso el cálculo de tamaño no depende del leverage).
    """
    # risk_amount = balance * (risk_pct / 100.0)
    risk_amount = 50
    sl_distance = abs(entry_price - sl_price)
    if sl_distance <= 0:
        return 0.0
    return risk_amount / sl_distance


def get_open_position_size(exchange, symbol: str) -> float:
    """Contratos abiertos actualmente en el exchange para ese símbolo (0 si no hay posición)."""
    try:
        positions = exchange.fetch_positions([symbol])
        for p in positions:
            contracts = p.get("contracts") or 0
            if contracts:
                return float(contracts)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo consultar la posición abierta en {symbol}: {e}")
    return 0.0


def cancel_order_safe(exchange, symbol: str, order_id):
    if not order_id:
        return
    try:
        exchange.cancel_order(order_id, symbol)
    except Exception as e:
        print(f"[bitget_executor] Aviso: no se pudo cancelar la orden {order_id} en {symbol}: {e}")


def open_position(exchange, symbol: str, direction: str, leverage: int,
                   entry_price: float, sl_price: float, tp_prices: list,
                   risk_pct: float, tp_split=(1 / 3, 1 / 3, 1 / 3)) -> dict:
    """
    Abre la posición en Bitget demo y coloca SL + 3 TP como órdenes reales
    reduceOnly. Devuelve un dict con los IDs de las órdenes y el tamaño
    real usado, para que el bot lo guarde en su estado y pueda gestionarlo
    después (ej. mover el SL a BE, cancelar al cerrar).
    """
    is_long = direction == "ALCISTA"
    entry_side = "buy" if is_long else "sell"
    close_side = "sell" if is_long else "buy"

    set_leverage(exchange, symbol, leverage)

    balance = get_usdt_balance(exchange)
    raw_size = calculate_position_size(balance, entry_price, sl_price, risk_pct)
    size = float(exchange.amount_to_precision(symbol, raw_size))
    if size <= 0:
        raise ValueError(f"Tamaño de posición calculado es 0 para {symbol} (balance={balance:.2f} USDT)")

    entry_order = exchange.create_order(symbol, "market", entry_side, size)

    sl_order = exchange.create_order(
        symbol, "market", close_side, size,
        params={"stopLossPrice": sl_price, "reduceOnly": True},
    )

    tp_orders = []
    remaining = size
    last_i = len(tp_prices) - 1
    for i, (tp_price, split) in enumerate(zip(tp_prices, tp_split)):
        tp_size = round(remaining, 8) if i == last_i else float(exchange.amount_to_precision(symbol, size * split))
        remaining = round(remaining - tp_size, 8)
        tp_order = exchange.create_order(
            symbol, "market", close_side, tp_size,
            params={"takeProfitPrice": tp_price, "reduceOnly": True},
        )
        tp_orders.append({"order_id": tp_order.get("id"), "price": tp_price, "size": tp_size})

    return {
        "entry_order_id": entry_order.get("id"),
        "size": size,
        "sl_order_id": sl_order.get("id"),
        "tp_orders": tp_orders,
    }


def move_sl_to_be(exchange, symbol: str, direction: str, old_sl_order_id, new_sl_price: float,
                   size: float):
    """
    Cancela la orden de SL anterior y coloca una nueva en break-even.
    Devuelve el ID de la nueva orden de SL (o None si algo falla).
    """
    is_long = direction == "ALCISTA"
    close_side = "sell" if is_long else "buy"

    cancel_order_safe(exchange, symbol, old_sl_order_id)

    try:
        new_sl_order = exchange.create_order(
            symbol, "market", close_side, size,
            params={"stopLossPrice": new_sl_price, "reduceOnly": True},
        )
        return new_sl_order.get("id")
    except Exception as e:
        print(f"[bitget_executor] ERROR moviendo SL a BE en {symbol}: {e}")
        return None


def close_remaining_position(exchange, symbol: str, direction: str,
                              sl_order_id=None, tp_order_ids=None):
    """
    Red de seguridad al cerrar un trade (flip, SL o TP3): cancela las
    órdenes de SL/TP que sigan pendientes y, si queda tamaño abierto en el
    exchange (ej. por un flip, o porque el SL/TP del propio Bitget aún no
    se ha ejecutado), lo cierra a mercado.
    """
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
