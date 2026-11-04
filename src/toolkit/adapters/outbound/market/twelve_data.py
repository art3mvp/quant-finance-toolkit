"""Adaptador outbound de Twelve Data: OHLCV de acciones, índices y ETFs.

Endpoint: ``/time_series`` con ``interval`` ``1day``/``1week``/``1month``.

Particularidades (verificadas contra el servicio real):
    * ``end_date`` es **exclusivo**: se envía ``end + 1 día`` para que ``end`` se incluya.
    * Máximo de 5000 barras por petición; si el rango es mayor se avisa en el log.
    * Los errores llegan como ``{"status": "error", "code": ..., "message": ...}``, a veces
      con HTTP 200, así que también se inspecciona el cuerpo.
    * Índices y divisas pueden no traer ``volume``: queda a ``NaN``.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import clip
from toolkit.adapters.outbound._prices import normalize_ohlcv
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.twelvedata.com"
MAX_OUTPUT = 5000

_INTERVALS: dict[Frequency, str] = {
    Frequency.DAILY: "1day",
    Frequency.WEEKLY: "1week",
    Frequency.MONTHLY: "1month",
}


class TwelveDataPriceProvider:
    """Proveedor de precios desde Twelve Data.

    Args:
        api_key: Clave de Twelve Data (plan gratuito disponible).
        base_url: URL base de la API.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "twelve_data"

    def __init__(
        self, api_key: str | None, base_url: str = DEFAULT_BASE_URL, **http_options: Any
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(self.name, secrets=[self._api_key], **http_options)

    def fetch_prices(
        self,
        ticker: str,
        start: date | None,
        end: date | None,
        interval: Frequency,
        asset_type: AssetType,
    ) -> PriceSeries:
        """Descarga OHLCV de ``ticker`` en ``[start, end]`` (ambos incluidos).

        Raises:
            ConfigurationError: Si falta o se rechaza la API key.
            SeriesNotFoundError: Si el símbolo no existe o no hay datos.
            ProviderError: Frecuencia no soportada, límites de la API o formato inválido.
        """
        if not self._api_key:
            raise ConfigurationError("Falta TWELVE_DATA_API_KEY (gratis en twelvedata.com)")
        if interval not in _INTERVALS:
            raise ProviderError(f"twelve_data: frecuencia {interval.value} no soportada")
        params: dict[str, Any] = {
            "symbol": ticker,
            "interval": _INTERVALS[interval],
            "outputsize": MAX_OUTPUT,
            "order": "asc",
            "apikey": self._api_key,
        }
        if start is not None:
            params["start_date"] = start.isoformat()
        if end is not None:
            params["end_date"] = (end + timedelta(days=1)).isoformat()  # exclusivo en la API
        payload = self._http.get_json(f"{self.base_url}/time_series", params, identifier=ticker)
        meta, data = parse_time_series(payload, ticker)
        if start is not None and len(data) >= MAX_OUTPUT and data.index[0].date() > start:
            logger.warning("twelve_data: %s truncado a %d barras", ticker, MAX_OUTPUT)
        data = clip(data, start, end)
        if data.empty:
            raise SeriesNotFoundError(f"twelve_data: {ticker}: sin datos en el rango solicitado")
        return PriceSeries(
            ticker=ticker,
            name=None,
            asset_type=asset_type,
            source=self.name,
            currency=meta.get("currency") or None,
            frequency=interval,
            data=data,
        )


def parse_time_series(payload: Any, ticker: str) -> tuple[dict[str, Any], pd.DataFrame]:
    """Devuelve ``(meta, ohlcv)`` a partir del cuerpo de ``/time_series``.

    Raises:
        ConfigurationError: Errores 401/403 en el cuerpo (clave o plan).
        SeriesNotFoundError: Errores 400/404 en el cuerpo o lista vacía.
        ProviderError: Cualquier otro error o formato inesperado.
    """
    if not isinstance(payload, dict):
        raise ProviderError(f"twelve_data: {ticker}: respuesta inesperada")
    if payload.get("status") == "error":
        _raise_body_error(payload, ticker)
    values = payload.get("values")
    if not isinstance(values, list):
        raise ProviderError(f"twelve_data: {ticker}: respuesta sin 'values'")
    if not values:
        raise SeriesNotFoundError(f"twelve_data: {ticker}: sin datos")
    frame = pd.DataFrame(values)
    if "datetime" not in frame:
        raise ProviderError(f"twelve_data: {ticker}: barras sin 'datetime'")
    data = normalize_ohlcv(frame.set_index("datetime"), "twelve_data", ticker)
    return payload.get("meta") or {}, data


def _raise_body_error(payload: dict[str, Any], ticker: str) -> None:
    code = payload.get("code")
    message = str(payload.get("message", ""))[:200]
    if code in (401, 403):
        raise ConfigurationError(f"twelve_data: clave o plan sin acceso: {message}")
    if code in (400, 404):
        raise SeriesNotFoundError(f"twelve_data: {ticker}: {message}")
    raise ProviderError(f"twelve_data: {ticker}: error {code}: {message}")
