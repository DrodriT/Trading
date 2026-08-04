"""
Conexión al exchange (Bitget vía ccxt) y descarga de velas OHLCV.

Extraído de main.py (antes bot_rodri.py) sin cambios de lógica.
"""
import ccxt
import pandas as pd


def create_exchange(cfg):
    """Crea el cliente ccxt del exchange configurado (Bitget, perpetuos)."""
    exchange_class = getattr(ccxt, cfg.EXCHANGE_ID)
    return exchange_class({
        "enableRateLimit": True,
        "options": {"defaultType": cfg.MARKET_TYPE},
    })


def fetch_ohlcv(exchange, symbol, timeframe, limit):
    """Descarga velas OHLCV y las devuelve como DataFrame con columna
    'datetime' (UTC) añadida."""
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df
