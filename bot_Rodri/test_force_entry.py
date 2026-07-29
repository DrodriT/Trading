"""
test_force_entry.py — Forzar una entrada de prueba en Bitget demo.

Sirve para comprobar que la conexión con Bitget funciona de verdad (abre
posición, coloca SL + 3 TP como órdenes reales) SIN depender de que el
motor de señales de Rodri dispare una señal real.

Edita los valores de abajo (símbolo, dirección, entrada, SL, TPs,
leverage) — por defecto están puestos los de tu captura de OPUSDT LONG —
y ejecútalo:

    python3 test_force_entry.py

Después de correrlo, VE A LA APP DE BITGET (cuenta demo) y comprueba:
  1. Que se abrió la posición con el tamaño/leverage esperado.
  2. Que aparecen 4 órdenes pendientes: el SL y los 3 TP.
  3. Los precios de esas órdenes coinciden con los de abajo.
"""
import config_rodri as config
import bitget_executor as bx

# ── EDITA ESTO con los valores que quieras forzar ──
SYMBOL = "OP/USDT:USDT"
DIRECTION = "ALCISTA"       # "ALCISTA" (long) o "BAJISTA" (short)
ENTRY_PRICE = 0.0893
SL_PRICE = 0.0852
TP1_PRICE = 0.0934
TP2_PRICE = 0.09627
TP3_PRICE = 0.09955
LEVERAGE = 2
# ────────────────────────────────────────────────────


def main():
    missing = [
        name for name, val in [
            ("BITGET_API_KEY", config.BITGET_API_KEY),
            ("BITGET_API_SECRET", config.BITGET_API_SECRET),
            ("BITGET_API_PASSWORD", config.BITGET_API_PASSWORD),
        ] if not val or "PON_AQUI" in val
    ]
    if missing:
        print(f"[ERROR] Faltan/están vacías estas claves de Bitget: {', '.join(missing)}. "
              f"Revisa que los nombres de los secrets en GitHub coincidan EXACTAMENTE con los "
              f"que usa el workflow (env: BITGET_API_KEY/BITGET_API_SECRET/BITGET_API_PASSWORD).")
        return

    print(f"Conectando a Bitget demo...")
    exchange = bx.create_demo_exchange(
        config.BITGET_API_KEY, config.BITGET_API_SECRET, config.BITGET_API_PASSWORD
    )

    balance = bx.get_usdt_balance(exchange)
    print(f"Balance demo disponible: {balance:.2f} USDT")

    print(f"\nForzando entrada: {SYMBOL} | {DIRECTION} | Entrada {ENTRY_PRICE} | "
          f"SL {SL_PRICE} | Leverage {LEVERAGE}x | Riesgo {config.RISK_PCT_PER_TRADE}% del balance")

    result = bx.open_position(
        exchange, SYMBOL, DIRECTION, LEVERAGE,
        entry_price=ENTRY_PRICE, sl_price=SL_PRICE,
        tp_prices=[TP1_PRICE, TP2_PRICE, TP3_PRICE],
        risk_pct=config.RISK_PCT_PER_TRADE, tp_split=config.TP_SPLIT,
    )

    print("\n✅ Resultado de la apertura:")
    print(f"  Tamaño de la posición: {result['size']}")
    print(f"  ID orden de entrada:   {result['entry_order_id']}")
    print(f"  ID orden SL:           {result['sl_order_id']}")
    for i, tp in enumerate(result["tp_orders"], start=1):
        print(f"  ID orden TP{i}:          {tp['order_id']} (precio {tp['price']}, tamaño {tp['size']})")

    print("\n👉 Ahora ve a la app de Bitget (cuenta DEMO) y comprueba que todo "
          "esto aparece exactamente así.")


if __name__ == "__main__":
    main()
