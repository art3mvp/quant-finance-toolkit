"""Adaptador outbound de Alpha Vantage: precios OHLCV diarios, semanales o mensuales.

Funciones usadas: ``TIME_SERIES_DAILY``, ``TIME_SERIES_WEEKLY`` y ``TIME_SERIES_MONTHLY``
(sin ajustar: las versiones ``_ADJUSTED`` diarias son de pago, así que no hay
``adj_close``).

Particularidades (verificadas contra el servicio real):
    * Los errores llegan con HTTP 200 dentro del cuerpo: ``Error Message`` (símbolo
      inválido) o ``Information``/``Note`` (límite de peticiones, plan o clave).
    * ``outputsize=compact`` devuelve ~100 sesiones; ``full`` todo el histórico. Se pide
      ``full`` solo si ``start`` queda fuera de la ventana compacta.
    * Las barras semanales y mensuales se fechan en la última sesión del periodo.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import clip
from toolkit.adapters.outbound._prices import normalize_ohlcv
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries

DEFAULT_BASE_URL = "https://www.alphavantage.co/query"
_COMPACT_WINDOW = timedelta(days=140)  # ~100 sesiones bursátiles con margen

#: Función de la API y clave de la serie temporal en la respuesta, por frecuencia.
_FUNCTIONS: dict[Frequency, tuple[str, str]] = {
    Frequency.DAILY: ("TIME_SERIES_DAILY", "Time Series (Daily)"),
    Frequency.WEEKLY: ("TIME_SERIES_WEEKLY", "Weekly Time Series"),
    Frequency.MONTHLY: ("TIME_SERIES_MONTHLY", "Monthly Time Series"),
}
_COLUMNS = {"1. open": "open", "2. high": "high", "3. low": "low", "4. close": "close"}


class AlphaVantagePriceProvider:
    """Proveedor de precios de acciones desde Alpha Vantage.

    Args:
        api_key: Clave de Alpha Vantage (gratuita). Sin ella se lanza ``ConfigurationError``.
        base_url: URL del endpoint ``query``.
        today: Reloj inyectable para decidir entre ``compact`` y ``full``.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "alpha_vantage"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = DEFAULT_BASE_URL,
        today: Any = date.today,
        **http_options: Any,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.base_url = base_url
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
        """Descarga OHLCV de ``ticker`` y lo recorta a ``[start, end]``.

        Raises:
            ConfigurationError: Si falta la API key.
            SeriesNotFoundError: Si el símbolo no existe o no hay datos en el rango.
            ProviderError: Frecuencia no soportada, límites de la API o formato inválido.
        """
        if not self._api_key:
            raise ConfigurationError(
                "Falta ALPHA_VANTAGE_API_KEY (gratis en https://www.alphavantage.co/support/)"
            )
        if interval not in _FUNCTIONS:
            raise ProviderError(f"alpha_vantage: frecuencia {interval.value} no soportada")
        function, key = _FUNCTIONS[interval]
        # Orden de la documentación: la clave "demo" solo acepta las URLs de ejemplo.
        params = {"function": function, "symbol": ticker}
        if interval is Frequency.DAILY:
            params["outputsize"] = self._output_size(start)
        params["apikey"] = self._api_key
        payload = self._http.get_json(self.base_url, params=params, identifier=ticker)
        data = clip(parse_time_series(payload, key, ticker), start, end)
        if data.empty:
            raise SeriesNotFoundError(f"alpha_vantage: {ticker}: sin datos en el rango solicitado")
        return PriceSeries(
            ticker=ticker,
            name=None,
            asset_type=asset_type,
            source=self.name,
            currency=None,  # la API no informa la divisa en estas funciones
            frequency=interval,
            data=data,
        )

    def _output_size(self, start: date | None) -> str:
        if start is not None and self._today() - start <= _COMPACT_WINDOW:
            return "compact"
        return "full"


def parse_time_series(payload: Any, key: str, ticker: str) -> pd.DataFrame:
    """Extrae la serie ``key`` del cuerpo y la normaliza a OHLCV.

    Raises:
        SeriesNotFoundError: Si Alpha Vantage indica que el símbolo no existe.
        ProviderError: Ante avisos de límite/plan o formato inesperado.
    """
    if not isinstance(payload, dict):
        raise ProviderError(f"alpha_vantage: {ticker}: respuesta inesperada")
    if payload.get("Error Message"):
        raise SeriesNotFoundError(f"alpha_vantage: {ticker}: símbolo no válido")
    for notice in ("Note", "Information"):
        if payload.get(notice):  # límite de peticiones, endpoint premium o clave demo
            raise ProviderError(f"alpha_vantage: {ticker}: {str(payload[notice])[:200]}")
    series = payload.get(key)
    if not isinstance(series, dict) or not series:
        raise ProviderError(f"alpha_vantage: {ticker}: respuesta sin '{key}'")
    frame = pd.DataFrame.from_dict(series, orient="index")
    frame = frame.rename(columns={**_COLUMNS, "5. volume": "volume"})
    return normalize_ohlcv(frame, "alpha_vantage", ticker)
