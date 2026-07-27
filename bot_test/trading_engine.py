# trading_engine.py
import ccxt
import time
from config import (
    BITGET_API_KEY, BITGET_SECRET_KEY, BITGET_PASSPHRASE,
    BITGET_DEMO, ORDER_AMOUNT_USDT, ORDER_TYPE
)

class BitgetTrader:
    def __init__(self):
        self.exchange = ccxt.bitget({
            'apiKey': BITGET_API_KEY,
            'secret': BITGET_SECRET_KEY,
            'password': BITGET_PASSPHRASE,
            'options': {
                'defaultType': 'swap',          # perpetuos
            },
            'demo': BITGET_DEMO,
            'enableRateLimit': True,
        })
        self.amount_usdt = ORDER_AMOUNT_USDT
        self.order_type = ORDER_TYPE

    def _retry(self, func, retries=3, delay=1):
        for i in range(retries):
            try:
                return func()
            except Exception as e:
                if i == retries - 1:
                    raise
                time.sleep(delay * (i + 1))
        return None

    def get_balance(self, currency='USDT'):
        try:
            balance = self.exchange.fetch_balance()
            return balance['free'].get(currency, 0.0)
        except Exception as e:
            print(f"[ERROR] Balance: {e}")
            return 0.0

    def get_ticker(self, symbol):
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            print(f"[ERROR] Ticker: {e}")
            return None

    def open_position(self, symbol, side, amount_usdt=None):
        """
        Abre una posición long (buy) o short (sell) en swap.
        amount_usdt: capital a usar en USDT (se convierte a cantidad base).
        """
        if amount_usdt is None:
            amount_usdt = self.amount_usdt

        price = self.get_ticker(symbol)
        if not price:
            return None

        # Cantidad en el activo base (BTC, ETH, etc.)
        quantity = amount_usdt / price
        market = self.exchange.market(symbol)
        precision = market.get('precision', {}).get('amount', 8)
        quantity = round(quantity, precision)

        # Opcional: establecer apalancamiento (demo suele tener 1x por defecto)
        try:
            self.exchange.set_leverage(1, symbol)   # o el valor que quieras
        except:
            pass

        try:
            order = self.exchange.create_market_order(symbol, side, quantity)
            print(f"[ORDEN] Abrir {side.upper()} {quantity} {symbol} a mercado")
            return order
        except Exception as e:
            print(f"[ERROR] Abrir orden {side}: {e}")
            return None

    def close_position(self, symbol, side):
        """
        Cierra una posición long o short completamente.
        side: 'long' o 'short' (dirección de la posición abierta)
        """
        try:
            # Obtener la posición actual
            positions = self.exchange.fetch_positions([symbol])
            if not positions:
                print(f"[WARN] No hay posición abierta para {symbol}")
                return None
            pos = positions[0]
            if pos['side'] != side:
                print(f"[WARN] La posición abierta es {pos['side']}, no {side}")
                return None
            quantity = pos['contracts']   # número de contratos
            close_side = 'sell' if side == 'long' else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, quantity)
            print(f"[ORDEN] Cerrar {side.upper()} {quantity} {symbol} a mercado")
            return order
        except Exception as e:
            print(f"[ERROR] Cerrar posición: {e}")
            return None