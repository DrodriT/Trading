"""
Data/market_data.py

Obtención de datos OHLCV para el timeframe base y para el HTF
(higher timeframe) usado por el filtro de sesgo del Pine.

Usa ccxt porque es la librería estándar para exchanges cripto y no
requiere claves API para datos públicos de velas. Si tu mercado es
otro (forex/acciones), sustituye `fetch_ohlcv` por tu proveedor de
datos, manteniendo el mismo contrato de salida (DataFrame con
timestamp/open/high/low/close/volume, SIN la vela en formación).

── Auto HTF (4x el timeframe actual) ──
Replica `autoHtf()` del Pine (sección 5):
  On 5m/15m/30m/1h/4h/1D -> siguiente múltiplo de 4x redondeado al
  timeframe estándar más cercano.
"""

from __future__ import annotations
from typing import Optional, Tuple
import logging

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import ccxt
except ImportError:
    ccxt = None


# Minutos por timeframe (para el cálculo de autoHtf, igual que Pine)
_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440, "1w": 10080,
}


def auto_htf(base_timeframe: str) -> str:
    """Replica autoHtf(): 4x el timeframe actual, redondeado al estándar."""
    base_min = _TF_MINUTES.get(base_timeframe.lower())
    if base_min is None:
        raise ValueError(f"Timeframe base no reconocido para autoHtf: {base_timeframe}")
    target = base_min * 4
    if target <= 5:
        return "5m"
    if target <= 15:
        return "15m"
    if target <= 30:
        return "30m"
    if target <= 60:
        return "1h"
    if target <= 240:
        return "4h"
    if target <= 1440:
        return "1d"
    return "1w"


class MarketData:
    def __init__(self, exchange_id: str = "binance"):
        if ccxt is None:
            raise ImportError(
                "ccxt no está instalado. Ejecuta: pip install ccxt"
            )
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 1500
    ) -> pd.DataFrame:
        """
        Devuelve un DataFrame ordenado ascendentemente con columnas
        [timestamp, open, high, low, close, volume], EXCLUYENDO la
        última vela si todavía está en formación (para garantizar
        que solo trabajamos con barstate.isconfirmed == true).
        """
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

        # Excluir la vela en curso: comparamos el cierre esperado de la
        # última vela contra la hora actual del exchange.
        tf_ms = self.exchange.parse_timeframe(timeframe) * 1000
        now_ms = self.exchange.milliseconds()
        last_open_ms = int(df["timestamp"].iloc[-1].timestamp() * 1000)
        if last_open_ms + tf_ms > now_ms:
            df = df.iloc[:-1]

        return df.reset_index(drop=True)

    def get_base_and_htf(
        self,
        symbol: str,
        timeframe: str,
        htf_timeframe: str = "",
        limit: int = 1500,
    ) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        """
        Descarga el TF base y el HTF (auto 4x si htf_timeframe == "").
        El HTF se pide con más histórico relativo en barras para poder
        alinear correctamente vía merge_asof (mismo rango temporal).
        """
        base_df = self.fetch_ohlcv(symbol, timeframe, limit=limit)

        resolved_htf = htf_timeframe if htf_timeframe else auto_htf(timeframe)
        try:
            htf_df = self.fetch_ohlcv(symbol, resolved_htf, limit=limit)
        except Exception as e:
            logger.warning("No se pudo obtener HTF (%s): %s", resolved_htf, e)
            htf_df = None

        return base_df, htf_df
