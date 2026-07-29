"""
test_force_entry.py — Prueba de apertura de posición con SL y cierre parcial (TP1) con SL a BE.
"""
import config_rodri as config
import bitget_executor as bx
import time

SYMBOL = "BTC/USDT:USDT"
DIRECTION = "ALCISTA"
ENTRY_PRICE = 64000.0
SL_PRICE = 63730.0
LEVERAGE = 10

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

    print("Diagnóstico de credenciales:")
    print(f"  BITGET_API_KEY:      {_mask(config.BITGET_API_KEY)}")
    print(f"  BITGET_API_SECRET:   {_mask(config.BITGET_API_SECRET)}")
    print(f"  BITGET_API_PASSWORD: {_mask(config.BITGET_API_PASSWORD)}")
    print()

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

    # Abrir posición solo con SL
    state = bx.open_position(
        exchange, SYMBOL, DIRECTION, LEVERAGE,
        entry_price=ENTRY_PRICE, sl_price=SL_PRICE,
        risk_pct=config.RISK_PCT_PER_TRADE,
    )

    print("\n✅ Posición abierta:")
    print(f"  Tamaño: {state['size']}")
    print(f"  ID entrada: {state['entry_order_id']}")
    print(f"  ID SL: {state['sl_order_id']}")
    print(f"  Precio entrada: {state['entry_price']}")
    print(f"  SL price: {state['sl_price']}")

    # Simular que se alcanza TP1: cerrar 1/3 de la posición y mover SL a BE
    time.sleep(2)  # espera para que la orden se haya procesado
    print("\n🔔 Simulando TP1: cerrando 1/3 de la posición y moviendo SL a BE...")
    tp1_amount = state["size"] * (1/3)
    tp1_order = bx.close_partial(exchange, state, tp1_amount, move_sl_to_be_after=True)
    if tp1_order:
        print(f"   Cerrado {tp1_amount} en orden {tp1_order.get('id')}")
        print(f"   Nuevo tamaño: {state['size']}")
        print(f"   Nuevo SL ID: {state['sl_order_id']} (BE)")

    # Ahora la posición restante tiene SL en BE. Podemos seguir simulando TP2, TP3 o cerrar todo.
    print("\n👉 Puedes llamar a bx.close_remaining_position(exchange, state) para cerrar todo.")
    print("   O seguir cerrando parcialmente con bx.close_partial(exchange, state, amount)")

if __name__ == "__main__":
    main()