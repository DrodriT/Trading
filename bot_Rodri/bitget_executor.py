"""
bitget_executor.py - Módulo para operar en Bitget (demo y real)
Funciones:
- create_demo_exchange: conexión a Bitget en modo sandbox.
- get_usdt_balance: obtiene el saldo disponible en USDT o USD.
- open_position: abre una posición con SL y TPs, acepta tamaño fijo.
- (auxiliares) place_sl_order, place_tp_orders.
"""
import ccxt
import time
import logging

logger = logging.getLogger(__name__)

def create_demo_exchange(api_key, api_secret, api_password):
    """Crea y configura una instancia de exchange de Bitget en modo demo."""
    exchange = ccxt.bitget({
        'apiKey': api_key,
        'secret': api_secret,
        'password': api_password,
        'options': {
            'defaultType': 'swap',   # Futuros perpetuos
        },
        'enableRateLimit': True,
    })
    exchange.set_sandbox_mode(True)   # Modo demo
    return exchange


def get_usdt_balance(exchange):
    """
    Obtiene el saldo disponible en USDT (o USD) de la cuenta de futuros.
    Maneja diferentes estructuras de respuesta de Bitget.
    Retorna float con el balance, o 0.0 si no se encuentra.
    """
    try:
        # Intentamos obtener balance con tipo 'swap' sin productType específico
        raw = exchange.fetch_balance(params={'type': 'swap'})
        print("DEBUG get_usdt_balance - raw completo:", raw)  # Línea de depuración

        # 1. Buscar en 'total' o 'free' por moneda USDT/USD
        for key in ['total', 'free']:
            if key in raw and raw[key]:
                for currency in ['USDT', 'USD']:
                    if currency in raw[key]:
                        val = raw[key][currency]
                        if val is not None:
                            return float(val)

        # 2. Buscar en 'info' (estructura anidada típica de Bitget)
        if 'info' in raw and raw['info']:
            info = raw['info']
            # Si info es una lista, cada elemento tiene 'coin' y 'available'
            if isinstance(info, list) and len(info) > 0:
                for item in info:
                    if item.get('coin') in ['USDT', 'USD']:
                        return float(item.get('available', 0.0))
            # Si info es un dict con 'data' -> 'list' (otro formato común)
            elif isinstance(info, dict) and 'data' in info:
                data = info.get('data', {})
                if isinstance(data, dict) and 'list' in data:
                    for item in data['list']:
                        if item.get('coin') in ['USDT', 'USD']:
                            return float(item.get('available', 0.0))
                elif isinstance(data, list):  # a veces data es directamente lista
                    for item in data:
                        if item.get('coin') in ['USDT', 'USD']:
                            return float(item.get('available', 0.0))

        # Si no se encuentra, devolvemos 0
        print("No se pudo extraer el balance de USDT/USD. Revisa la estructura de raw.")
        return 0.0

    except Exception as e:
        print(f"Error en get_usdt_balance: {e}")
        return 0.0


def place_sl_order(exchange, symbol, direction, entry_price, sl_price, size, leverage):
    """
    Coloca una orden de stop loss (take-profit) para la posición.
    Nota: Bitget usa órdenes 'stop' para SL y TP.
    Esta función es un ejemplo; puede necesitar ajustes según la versión de CCXT.
    """
    try:
        # Determinar el lado de la orden de stop
        # Si es LONG, el SL se coloca por debajo del precio de entrada (venta)
        # Si es SHORT, el SL se coloca por encima (compra)
        side = 'sell' if direction.upper() == 'ALCISTA' else 'buy'
        # El precio de activación (stopPrice) es el SL price
        stop_price = sl_price
        order = exchange.create_order(
            symbol=symbol,
            type='stop',
            side=side,
            amount=size,
            price=None,          # No se especifica precio límite (orden stop market)
            params={
                'stopPrice': stop_price,
                'reduceOnly': True,   # Solo cierra posición
                'leverage': leverage,
            }
        )
        return order
    except Exception as e:
        logger.error(f"Error al colocar SL: {e}")
        raise


def place_tp_orders(exchange, symbol, direction, entry_price, tp_prices, size, leverage):
    """
    Coloca órdenes de take profit (límite) para las ganancias parciales.
    tp_prices es una lista de precios.
    """
    orders = []
    try:
        # Lado de la orden: si LONG, vender; si SHORT, comprar
        side = 'sell' if direction.upper() == 'ALCISTA' else 'buy'
        # Para cada TP, colocar una orden límite
        for tp_price in tp_prices:
            # El tamaño se puede dividir, pero aquí usamos el mismo size para cada TP
            # (ajustable según tp_split)
            order = exchange.create_order(
                symbol=symbol,
                type='limit',
                side=side,
                amount=size,
                price=tp_price,
                params={
                    'reduceOnly': True,
                    'leverage': leverage,
                }
            )
            orders.append(order)
        return orders
    except Exception as e:
        logger.error(f"Error al colocar TP: {e}")
        raise


def open_position(exchange, symbol, direction, leverage, entry_price, sl_price,
                  tp_prices, risk_pct, tp_split, size=None):
    """
    Abre una posición en el mercado de futuros con SL y TPs.

    Parámetros:
        exchange: instancia de ccxt.bitget
        symbol: str, ej. 'BTC/USDT:USDT'
        direction: 'ALCISTA' o 'BAJISTA'
        leverage: int, apalancamiento
        entry_price: float, precio de entrada (límite)
        sl_price: float, precio de stop loss
        tp_prices: list de float, precios de take profit
        risk_pct: float, porcentaje del balance a arriesgar (se ignora si size no es None)
        tp_split: str, 'equal' o 'progressive' (no usado en este ejemplo básico)
        size: float opcional, tamaño fijo en moneda base (ej. BTC). Si se proporciona, ignora risk_pct.

    Retorna:
        dict con 'size', 'entry_order_id', 'sl_order_id', 'tp_orders'
    """
    # Asegurar que el mercado existe
    if symbol not in exchange.markets:
        raise ValueError(f"Símbolo {symbol} no soportado por Bitget")

    # Ajustar apalancamiento
    exchange.set_leverage(leverage, symbol)

    # Calcular el tamaño de la posición
    if size is None:
        # Obtener balance disponible
        balance = get_usdt_balance(exchange)
        if balance <= 0:
            raise ValueError(f"Balance insuficiente: {balance} USDT. No se puede abrir la posición.")

        risk_amount = balance * (risk_pct / 100.0)
        price_diff = abs(entry_price - sl_price)
        # Fórmula: tamaño = (riesgo / diferencia_precio) * apalancamiento
        raw_size = (risk_amount / price_diff) * leverage
        # Ajustar al mínimo permitido por el mercado
        min_amount = exchange.markets[symbol]['limits']['amount']['min']
        if raw_size < min_amount:
            logger.warning(f"Tamaño calculado {raw_size} menor que mínimo {min_amount}, se ajusta a {min_amount}")
            raw_size = min_amount
    else:
        # Usar el tamaño fijo proporcionado
        raw_size = size
        # Validar mínimo
        min_amount = exchange.markets[symbol]['limits']['amount']['min']
        if raw_size < min_amount:
            logger.warning(f"Tamaño forzado {raw_size} menor que mínimo {min_amount}, se ajusta a {min_amount}")
            raw_size = min_amount

    # Aplicar precisión del exchange (número de decimales)
    size_precise = float(exchange.amount_to_precision(symbol, raw_size))

    # ---- Orden de entrada (market o limit) ----
    # Usamos una orden limit para fijar el precio de entrada
    side = 'buy' if direction.upper() == 'ALCISTA' else 'sell'
    try:
        entry_order = exchange.create_order(
            symbol=symbol,
            type='limit',
            side=side,
            amount=size_precise,
            price=entry_price,
            params={'leverage': leverage}
        )
        entry_order_id = entry_order['id']
    except Exception as e:
        logger.error(f"Error al colocar orden de entrada: {e}")
        raise

    # ---- SL y TP ----
    # Para SL, usamos una orden stop (reduceOnly)
    sl_order = place_sl_order(exchange, symbol, direction, entry_price, sl_price, size_precise, leverage)
    # Para TPs, órdenes límite (reduceOnly)
    tp_orders = place_tp_orders(exchange, symbol, direction, entry_price, tp_prices, size_precise, leverage)

    # Retornar información
    return {
        'size': size_precise,
        'entry_order_id': entry_order_id,
        'sl_order_id': sl_order['id'],
        'tp_orders': [{'order_id': o['id'], 'price': o['price'], 'size': o['amount']} for o in tp_orders]
    }


# Ejemplo de uso (para pruebas rápidas)
if __name__ == "__main__":
    # Aquí puedes poner un test rápido si lo deseas
    pass