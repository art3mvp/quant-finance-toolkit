"""Adaptador outbound de CoinGecko: precios diarios de criptoactivos.

Endpoint: ``/coins/{id}/market_chart?vs_currency=...&days=N&interval=daily``.
El ticker es el *id* de CoinGecko (``bitcoin``, ``ethereum``...), no el símbolo (BTC).

Normalización a ``PriceSeries``:
    * CoinGecko no ofrece OHLC diario en el plan gratuito: ``close`` es el precio de cada
      punto y ``open``/``high``/``low`` quedan a ``NaN`` (no se inventan velas).
    * ``volume`` es el volumen negociado en las 24 h previas a cada punto.
    * El último punto es el precio "en vivo" del día actual; si coincide en fecha con el
      punto diario, se conserva el más reciente.
    * Frecuencias superiores a la diaria se obtienen agregando: último cierre y suma del
      volumen, con la fecha de inicio de cada periodo (como Yahoo).

Planes: sin clave o con plan ``demo`` el histórico está limitado a 365 días; el plan
``pro`` usa otro host y cabecera. La clave nunca aparece en los mensajes de error.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import clip
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries

logger = logging.getLogger(__name__)

_HOSTS = {"demo": "https://api.coingecko.com/api/v3", "pro": "https://pro-api.coingecko.com/api/v3"}
_DEFAULT_DAYS = 365  # máximo del plan gratuito/demo

#: Periodo de pandas usado para agregar cada frecuencia (semana de lunes a domingo).
_PERIODS: dict[Frequency, str] = {
    Frequency.WEEKLY: "W-SUN",
    Frequency.MONTHLY: "M",
    Frequency.QUARTERLY: "Q",
    Frequency.ANNUAL: "Y",
}


class CoinGeckoPriceProvider:
    """Proveedor de precios de criptoactivos desde la API de CoinGecko.

    Args:
        api_key: Clave de CoinGecko (opcional en plan ``demo``, obligatoria en ``pro``).
        plan: ``"demo"`` (por defecto) o ``"pro"``.
        vs_currency: Divisa de cotización (``usd``, ``eur``...).
        today: Reloj inyectable para calcular cuántos días pedir.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "coingecko"

    def __init__(
        self,
        api_key: str | None = None,
        plan: str = "demo",
        vs_currency: str = "usd",
        today: Callable[[], date] = date.today,
        **http_options: Any,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.plan = (plan or "demo").strip().lower()
        self.vs_currency = vs_currency.lower()
        self._today = today
        self._http = HttpClient(self.name, secrets=[self._api_key], **http_options)

    def fetch_prices(
        self,
        ticker: str,
        start: date | None,
        end: date | None,
        interval: Frequency,
        asset_type: AssetType,
    ) -> PriceSeries:
        """Descarga precios diarios de ``ticker`` y los agrega a ``interval`` si hace falta.

        Raises:
            ConfigurationError: Si el plan no es válido, falta la clave en ``pro`` o
                CoinGecko rechaza el acceso (p. ej. histórico > 365 días sin plan pro).
            SeriesNotFoundError: Si el id no existe o no hay datos en el rango.
            ProviderError: Ante cualquier otro error HTTP, de red o de formato.
        """
        if asset_type is not AssetType.CRYPTO:
            logger.warning("coingecko: %s se trata como crypto (pedido %s)", ticker, asset_type)
        coin = ticker.strip().lower()
        payload = self._http.get_json(
            f"{self._base_url()}/coins/{coin}/market_chart",
            params={
                "vs_currency": self.vs_currency,
                "days": self._days(start),
                "interval": "daily",
            },
            headers=self._headers(),
            identifier=coin,
        )
        data = parse_market_chart(payload, coin)
        data = clip(data, start, end)
        if data.empty:
            raise SeriesNotFoundError(f"coingecko: {coin}: sin datos en el rango solicitado")
        return PriceSeries(
            ticker=coin,
            name=None,
            asset_type=AssetType.CRYPTO,
            source=self.name,
            currency=self.vs_currency.upper(),
            frequency=interval,
            data=resample(data, interval),
        )

    def _base_url(self) -> str:
        if self.plan not in _HOSTS:
            raise ConfigurationError("coingecko: COINGECKO_API_PLAN debe ser 'demo' o 'pro'")
        return _HOSTS[self.plan]

    def _headers(self) -> dict[str, str]:
        if self.plan == "pro" and not self._api_key:
            raise ConfigurationError("coingecko: el plan pro requiere COINGECKO_API_KEY")
        return {f"x-cg-{self.plan}-api-key": self._api_key} if self._api_key else {}

    def _days(self, start: date | None) -> int:
        """Días a pedir: desde ``start`` hasta hoy (incluido), o 365 si no hay ``start``.

        Raises:
            ConfigurationError: Si el plan demo no cubre ``start`` (CoinGecko responde 401,
                que se confundiría con una clave rechazada).
        """
        if start is None:
            return _DEFAULT_DAYS
        days = max((self._today() - start).days + 1, 1)
        if self.plan == "demo" and days > _DEFAULT_DAYS:
            raise ConfigurationError(
                f"coingecko: el plan demo solo cubre {_DEFAULT_DAYS} días; usa un start "
                "más reciente o COINGECKO_API_PLAN=pro"
            )
        return days


def parse_market_chart(payload: Any, coin: str) -> pd.DataFrame:
    """Convierte ``prices`` y ``total_volumes`` en un ``DataFrame`` OHLCV diario.

    Raises:
        SeriesNotFoundError: Si no hay precios.
        ProviderError: Si el formato no es el esperado.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("prices"), list):
        raise ProviderError(f"coingecko: {coin}: respuesta sin 'prices'")
    if not payload["prices"]:
        raise SeriesNotFoundError(f"coingecko: {coin}: sin precios")
    try:
        close = _points(payload["prices"])
        volume = _points(payload.get("total_volumes") or []).reindex(close.index)
    except (TypeError, ValueError) as exc:
        raise ProviderError(f"coingecko: {coin}: formato de precios inválido: {exc}") from exc
    frame = pd.DataFrame({"close": close, "volume": volume})
    for column in ("open", "high", "low"):
        frame[column] = np.nan  # CoinGecko no da OHL diario: no se inventa
    return frame[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])


def _points(points: list[Any]) -> pd.Series:
    """``[[ms, valor], ...]`` → ``pd.Series`` por fecha UTC (se queda con el último del día)."""
    frame = pd.DataFrame(points, columns=["ts", "value"])
    index = pd.to_datetime(frame["ts"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    series = pd.Series(frame["value"].astype(float).to_numpy(), index=pd.DatetimeIndex(index))
    series = series.sort_index()
    return series[~series.index.duplicated(keep="last")].rename_axis("date")


def resample(data: pd.DataFrame, interval: Frequency) -> pd.DataFrame:
    """Agrega datos diarios a ``interval``: último cierre, suma de volumen, fecha de inicio."""
    if interval is Frequency.DAILY:
        return data
    periods = data.index.to_period(_PERIODS[interval])
    grouped = data.groupby(periods).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    grouped.index = pd.DatetimeIndex(grouped.index.start_time, name="date")
    return grouped.astype(float)
