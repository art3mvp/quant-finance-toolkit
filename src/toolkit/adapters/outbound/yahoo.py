"""Adaptador outbound de Yahoo Finance basado en la librería ``yfinance``.

Responsabilidades:
    * Traducir la petición del puerto ``PriceProvider`` a una llamada a ``yfinance``.
    * Normalizar el ``DataFrame`` devuelto al esquema estándar de ``PriceSeries``.
    * Encapsular los errores: ninguna excepción de ``yfinance`` sale de este módulo;
      se traducen a ``SeriesNotFoundError`` o ``ProviderError``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFTickerMissingError

from toolkit.domain.errors import ProviderError, SeriesNotFoundError, ToolkitError
from toolkit.domain.models import PRICE_COLUMNS, AssetType, Frequency, PriceSeries

logger = logging.getLogger(__name__)

#: Intervalos de ``yfinance`` por frecuencia. Yahoo no ofrece frecuencia anual.
_INTERVALS: dict[Frequency, str] = {
    Frequency.DAILY: "1d",
    Frequency.WEEKLY: "1wk",
    Frequency.MONTHLY: "1mo",
    Frequency.QUARTERLY: "3mo",
}

#: Renombrado de columnas de Yahoo al esquema estándar.
_COLUMN_MAP: dict[str, str] = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


class YahooPriceProvider:
    """Proveedor de precios de acciones e índices desde Yahoo Finance.

    Args:
        ticker_factory: Función que crea el objeto ``Ticker`` de ``yfinance``.
            Por defecto ``yfinance.Ticker``.
        timeout: Timeout en segundos de cada petición de ``yfinance``.
    """

    name = "yahoo"

    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._ticker_factory = ticker_factory
        self.timeout = timeout

    def fetch_prices(
        self,
        ticker: str,
        start: date | None,
        end: date | None,
        interval: Frequency,
        asset_type: AssetType,
    ) -> PriceSeries:
        """Descarga OHLCV de ``ticker`` con ``auto_adjust=False`` (conserva close y adj_close).

        ``end`` se trata como inclusivo (``yfinance`` lo trata como exclusivo, así que se
        envía ``end + 1 día``). Sin fechas se descarga todo el histórico (``period="max"``).

        Raises:
            SeriesNotFoundError: Si Yahoo no devuelve datos para el ticker o el rango.
            ProviderError: Ante cualquier otro error (red, formato, frecuencia no soportada).
        """
        if interval not in _INTERVALS:
            raise ProviderError(f"yahoo: frecuencia {interval.value} no soportada")
        factory = self._ticker_factory or yf.Ticker
        try:
            yf_ticker = factory(ticker)
            raw = yf_ticker.history(**self._history_kwargs(start, end, interval))
        except ToolkitError:
            raise
        except YFTickerMissingError as exc:
            raise SeriesNotFoundError(f"yahoo: sin datos para {ticker}: {exc}") from exc
        except Exception as exc:  # cualquier error de yfinance/red queda encapsulado
            raise ProviderError(f"yahoo: error descargando {ticker}: {exc}") from exc

        if raw is None or raw.empty:
            raise SeriesNotFoundError(f"yahoo: sin datos para {ticker} en el rango solicitado")

        data = normalize_history(raw)
        if data.empty:
            raise SeriesNotFoundError(f"yahoo: sin datos válidos para {ticker}")
        missing = {"open", "high", "low", "close", "volume"} - set(data.columns)
        if missing:
            raise ProviderError(f"yahoo: respuesta sin columnas {sorted(missing)} para {ticker}")

        name, currency = _metadata(yf_ticker)
        return PriceSeries(
            ticker=ticker,
            name=name,
            asset_type=asset_type,
            source=self.name,
            currency=currency,
            frequency=interval,
            data=data,
        )

    def _history_kwargs(
        self, start: date | None, end: date | None, interval: Frequency
    ) -> dict[str, Any]:
        """Construye los argumentos de ``Ticker.history``."""
        kwargs: dict[str, Any] = {
            "interval": _INTERVALS[interval],
            "auto_adjust": False,
            "actions": False,
            "timeout": self.timeout,
        }
        if start is None and end is None:
            kwargs["period"] = "max"
        else:
            kwargs["start"] = start
            kwargs["end"] = end + timedelta(days=1) if end is not None else None
        return kwargs


def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Convierte un ``DataFrame`` de ``yfinance`` al esquema estándar de ``PriceSeries``.

    * Renombra columnas a minúsculas (``Adj Close`` → ``adj_close``) y descarta el resto
      (dividendos, splits...).
    * Quita la zona horaria conservando la fecha local del mercado y normaliza a medianoche.
    * Ordena, elimina fechas duplicadas (se queda con la última) y filas sin cierre.
    """
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):  # formato de yf.download con varios tickers
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=lambda c: _COLUMN_MAP.get(c, str(c).strip().lower().replace(" ", "_")))
    df = df[[c for c in PRICE_COLUMNS if c in df.columns]]

    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    df.index = index.normalize().rename("date")

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    if "close" in df.columns:
        df = df.dropna(subset=["close"])
    return df.astype(float)


def _metadata(yf_ticker: Any) -> tuple[str | None, str | None]:
    """Obtiene nombre y divisa de forma tolerante a fallos (``None`` si no es posible)."""
    try:
        meta = yf_ticker.get_history_metadata() or {}
    except Exception as exc:  # los metadatos son opcionales: nunca rompen la descarga
        logger.debug("yahoo: no se pudieron obtener metadatos: %s", exc)
        return None, None
    if not isinstance(meta, Mapping):  # yfinance >= 1.x devuelve un Mapping, no un dict
        return None, None
    name = meta.get("longName") or meta.get("shortName")
    currency = meta.get("currency")
    return (str(name) if name else None, str(currency) if currency else None)
