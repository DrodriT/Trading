"""
test_force_entry.py — Prueba de apertura, TP1 y mover SL a BE.
"""
import config_rodri as config
import bitget_executor as bx
import time
import sys

SYMBOL = "BTC/USDT:USDT"
DIRECTION = "ALCISTA"
ENTRY_PRICE = 64000.0
SL_PRICE = 63730.0
LEVERAGE = 10

# Definimos los tamaños de TP (ej. 1/3 cada uno)
TP1_FRACTION = 1/3
TP2_FRACTION = 1/3
TP3_FRACTION = 1/3

def _mask(val: str) -> str:
    if not val:
        return "(VACÍO)"
    return f"longitud={len(val)} | empieza_por='{val[:3]}' | termina_en='{val[-3:]}'"

def main():
    missing = [
        name for name, val in [
            ("BITGET_API_KEY", config.BITGET_API_KEY),
            ("BITGET_API_SECRET", config.BITGET_API_SECRET),
            ("BITGET_API_PASSWORD", config.BITGET_API_PASSWORD),
        ] if not val or "PON_AQUI" in val
    ]
    if missing:
        print(f"[ERROR] Faltan/están vacías estas claves de Bitget: {', '.join(missing)}")
        return

    print("Conectando a Bitget demo...")
    exchange = bx.create_demo_exchange(
        config.BITGET_API_KEY, config.BITGET_API_SECRET, config.BITGET_API_PASSWORD
    )

    print("Probando llamada pública...")
    try:
        markets = exchange.load_markets()
        print(f"  OK: {len(markets)} mercados cargados.")
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    print("\nProbando fetch_balance...")
    balance = bx.get_usdt_balance(exchange)
    print(f"Balance demo: {balance:.2f} USDT")

    print(f"\nAbriendo posición: {SYMBOL} | {DIRECTION} | Entrada {ENTRY_PRICE} | "
          f"SL {SL_PRICE} | Leverage {LEVERAGE}x | Riesgo {config.RISK_PCT_PER_TRADE}%")

    result = bx.open_position(
        exchange, SYMBOL, DIRECTION, LEVERAGE,
        entry_price=ENTRY_PRICE, sl_price=SL_PRICE,
        risk_pct=config.RISK_PCT_PER_TRADE,
    )

    print("\n✅ Posición abierta:")
    print(f"  Tamaño: {result['size']}")
    print(f"  ID entrada: {result['entry_order_id']}")
    print(f"  ID SL: {result['sl_order_id']}")
    print(f"  Precio SL: {result['sl_price']}")
    print(f"  Precio entrada: {result['entry_price']}")

    # Simulación: esperar 10 segundos y luego ejecutar TP1
    print("\nSimulación: esperando 10 segundos y ejecutando TP1 (cierre de 1/3)...")
    time.sleep(10)

    tp1_amount = result['size'] * TP1_FRACTION
    # Redondear a la precisión del exchange
    tp1_amount = float(exchange.amount_to_precision(SYMBOL, tp1_amount))

    update = bx.close_tp1_and_move_sl_to_be(
        exchange, SYMBOL, DIRECTION,
        tp1_amount=tp1_amount,
        entry_price=result['entry_price'],
        old_sl_order_id=result['sl_order_id'],
        old_sl_price=result['sl_price']
    )

    print("\n✅ TP1 ejecutado y SL movido a BE:")
    print(f"  Cerrado TP1: {update['closed']}")
    print(f"  Posición restante: {update['remaining']}")
    print(f"  Nuevo ID SL: {update['new_sl_id']} (debería ser BE = {result['entry_price']})")

    # Opcional: cerrar todo al final
    # bx.close_remaining_position(exchange, SYMBOL, DIRECTION, update['new_sl_id'])

if __name__ == "__main__":
    main()