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
import sys

# ── EDITA ESTO con los valores que quieras forzar ──
# Valores basados en el precio de mercado de BTC/USDT a 29 jul 2026 (~64,000 USDT),
# con SL/TPs calculados igual que el preset "Balanced" (SL 1.5xATR, TPs 1R/2R/3R,
# ATR aproximado ~180 USDT para este rango de volatilidad).
SYMBOL = "BTC/USDT:USDT"
DIRECTION = "ALCISTA"       # "ALCISTA" (long) o "BAJISTA" (short)
ENTRY_PRICE = 64000.0
SL_PRICE = 63730.0
TP1_PRICE = 64270.0
TP2_PRICE = 64540.0
TP3_PRICE = 64810.0
LEVERAGE = 10

# ── OPCIÓN: forzar un tamaño fijo (en BTC) en lugar de calcularlo desde el balance ──
# Si es None, se usará el cálculo basado en riesgo y balance.
# Si pones un número (ej. 0.0001), se usará ESE tamaño, ignorando el balance.
# Prueba con un tamaño muy pequeño si hay problemas de margen.
FORCE_SIZE = 0.0001   # <-- Cambia a None si quieres usar el balance real
# ────────────────────────────────────────────────────


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
        print(f"[ERROR] Faltan/están vacías estas claves de Bitget: {', '.join(missing)}. "
              f"Revisa que los nombres de los secrets en GitHub coincidan EXACTAMENTE con los "
              f"que usa el workflow (env: BITGET_API_KEY/BITGET_API_SECRET/BITGET_API_PASSWORD).")
        return

    print("Diagnóstico de credenciales recibidas (nunca se muestran completas):")
    print(f"  BITGET_API_KEY:      {_mask(config.BITGET_API_KEY)}")
    print(f"  BITGET_API_SECRET:   {_mask(config.BITGET_API_SECRET)}")
    print(f"  BITGET_API_PASSWORD: {_mask(config.BITGET_API_PASSWORD)}")
    print("(Si alguna longitud te sorprende -ej. de más por un espacio o salto de línea pegado-, ahí está el fallo)\n")

    print("Conectando a Bitget demo...")
    exchange = bx.create_demo_exchange(
        config.BITGET_API_KEY, config.BITGET_API_SECRET, config.BITGET_API_PASSWORD
    )

    print("Probando primero una llamada PÚBLICA (sin autenticación) para aislar el problema...")
    try:
        markets = exchange.load_markets()
        print(f"  OK: {len(markets)} mercados cargados. La conexión base y la cabecera PAPTRADING funcionan.")
    except Exception as e:
        print(f"  ERROR incluso en la llamada pública: {e}")
        print("  Esto NO sería un problema de credenciales, sino de conectividad/cabecera. Avisa con este error.")
        return

    print("\nProbando ahora una llamada PRIVADA (fetch_balance, requiere firma con tus claves)...")

    # ── Mostramos la respuesta CRUDA para depurar ──
    for product_type in ("USDT-FUTURES", "SUSDT-FUTURES"):
        try:
            raw = exchange.fetch_balance(params={"type": "swap", "productType": product_type})
            print(f"\n🔍 fetch_balance con productType='{product_type}' (RESPUESTA COMPLETA):")
            print(raw)
        except Exception as e:
            print(f"\n🔍 fetch_balance con productType='{product_type}' -> ERROR: {e}")

    # Intentamos obtener el balance con la función mejorada
    balance_usdt = bx.get_usdt_balance(exchange)
    print(f"\nBalance demo disponible (según get_usdt_balance): {balance_usdt:.2f} USDT")

    # ── Si el balance es cero y no hay tamaño forzado, no podemos continuar ──
    if balance_usdt <= 0 and FORCE_SIZE is None:
        print("\n❌ ERROR: El balance es 0.00 USDT. No se puede calcular un tamaño de posición con riesgo porcentual.")
        print("   Para solucionarlo:")
        print("     1. Entra en la web/app de Bitget con tu cuenta DEMO.")
        print("     2. Busca la sección de fondos/cuenta demo y recarga saldo (suelen tener un botón de 'reset' o 'recargar').")
        print("     3. Vuelve a ejecutar este script.")
        print("   O bien, si solo quieres probar la apertura sin fondos, edita la variable FORCE_SIZE al inicio del script")
        print("   (por ejemplo, FORCE_SIZE = 0.0001) para usar un tamaño fijo.")
        sys.exit(1)

    # ── Mostramos qué tamaño se va a usar ──
    if FORCE_SIZE is not None:
        print(f"\n⚠️  Se usará un tamaño FORZADO de {FORCE_SIZE} BTC (ignorando el balance y el riesgo).")
        kwargs = {'size': FORCE_SIZE}
    else:
        kwargs = {}
        print(f"\n✅ Balance suficiente. Se calculará el tamaño en función del riesgo ({config.RISK_PCT_PER_TRADE}%).")

    print(f"\nForzando entrada: {SYMBOL} | {DIRECTION} | Entrada {ENTRY_PRICE} | "
          f"SL {SL_PRICE} | Leverage {LEVERAGE}x")

    # ── Llamada a open_position con los parámetros adecuados ──
    try:
        result = bx.open_position(
            exchange, SYMBOL, DIRECTION, LEVERAGE,
            entry_price=ENTRY_PRICE, sl_price=SL_PRICE,
            tp_prices=[TP1_PRICE, TP2_PRICE, TP3_PRICE],
            risk_pct=config.RISK_PCT_PER_TRADE if FORCE_SIZE is None else None,  # si usamos size fijo, riesgo no se usa
            tp_split=config.TP_SPLIT,
            **kwargs   # pasa 'size' si existe
        )
    except Exception as e:
        print(f"\n❌ Error al abrir la posición: {e}")
        if "amount must be greater than minimum" in str(e):
            print("   Esto indica que el tamaño calculado es cero o menor que el lote mínimo.")
            print("   Si estás usando FORCE_SIZE, asegúrate de que sea >= 0.0001 BTC.")
        elif "Insufficient margin" in str(e):
            print("   La cuenta no tiene margen suficiente. Revisa que la API key tenga permisos de futuros")
            print("   y que la cuenta demo tenga saldo. Si usas FORCE_SIZE, prueba un tamaño más pequeño.")
        sys.exit(1)

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