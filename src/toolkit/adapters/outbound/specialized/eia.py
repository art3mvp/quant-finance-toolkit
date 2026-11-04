"""Adaptador outbound de la EIA (U.S. Energy Information Administration), API v2.

Endpoint: ``/v2/seriesid/{id}``, que acepta los identificadores clásicos de la EIA:
    * ``PET.RWTC.D``     → WTI spot (Cushing), diario, $/barril.
    * ``PET.RBRTE.D``    → Brent spot (Europa), diario, $/barril.
    * ``NG.RNGWHHD.D``   → gas natural Henry Hub, diario, $/MMBtu.

Particularidades de la API (verificadas contra el servicio real):
    * Ignora ``start``/``end`` en este endpoint: devuelve toda la serie, ordenada de más
      reciente a más antigua y paginada en bloques de 5000 filas. Por eso se pagina con
      ``offset`` hasta cubrir ``start`` y el rango se filtra en local.
    * ``period`` cambia de formato según la frecuencia (``2024-01-02``, ``2024-01``,
      ``2024-Q1``, ``2024``); se normaliza a la fecha de inicio del periodo.
    * No publica vintages: ``as_of`` no está soportado.

Se clasifica como *macro* porque devuelve series univariantes (``MacroSeries``): son
precios de materias primas sin OHLCV, no activos negociables.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import (
    FREQUENCY_CODES,
    clip,
    parse_period,
    to_series,
)
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency, MacroSeries

DEFAULT_BASE_URL = "https://api.eia.gov/v2"
PAGE_SIZE = 5000  # máximo de filas por petición en la API v2


class EiaMacroProvider:
    """Proveedor de series de energía (petróleo, gas, electricidad) de la EIA.

    Args:
        api_key: API key de la EIA (gratuita). Sin ella ``fetch_series`` lanza
            ``ConfigurationError``.
        base_url: URL base de la API v2.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "eia"

    def __init__(
        self, api_key: str | None, base_url: str = DEFAULT_BASE_URL, **http_options: Any
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(self.name, secrets=[self._api_key], **http_options)

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga ``series_id`` completa (paginando) y la recorta a ``[start, end]``.

        Raises:
            ConfigurationError: Si falta la API key o la EIA la rechaza.
            SeriesNotFoundError: Si la serie no existe o no hay datos en el rango.
            ProviderError: Si se pide ``as_of`` o ante errores HTTP/de formato.
        """
        if not self._api_key:
            raise ConfigurationError(
                "Falta la API key de la EIA. Define EIA_API_KEY en el entorno o en .env "
                "(gratis en https://www.eia.gov/opendata/register.php)"
            )
        if as_of is not None:
            raise ProviderError(f"eia: {series_id}: la EIA no publica vintages (as_of)")

        rows, response = self._fetch_rows(series_id, start)
        data = parse_rows(rows, series_id)
        data = clip(data, start, end)
        if data.empty:
            raise SeriesNotFoundError(f"eia: {series_id}: sin datos en el rango solicitado")
        first = rows[0]
        return MacroSeries(
            series_id=series_id,
            name=first.get("series-description") or None,
            source=self.name,
            units=first.get("units") or None,
            frequency=_frequency(response.get("frequency"), series_id),
            data=data,
        )

    def _fetch_rows(
        self, series_id: str, start: date | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Pide páginas hasta agotar la serie o rebasar ``start`` (filas en orden desc)."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self._http.get_json(
                f"{self.base_url}/seriesid/{series_id.upper()}",  # la ruta distingue mayúsculas
                params={"api_key": self._api_key, "offset": offset, "length": PAGE_SIZE},
                identifier=series_id,
            )
            response = payload.get("response") if isinstance(payload, dict) else None
            page = response.get("data") if isinstance(response, dict) else None
            if not isinstance(page, list):
                raise ProviderError(f"eia: {series_id}: respuesta sin 'response.data'")
            rows.extend(page)
            offset += len(page)
            total = int(response.get("total") or 0)
            if len(page) < PAGE_SIZE or offset >= total or _reached(page, start):
                break
        if not rows:
            raise SeriesNotFoundError(f"eia: {series_id}: serie sin observaciones")
        return rows, response


def parse_rows(rows: list[dict[str, Any]], series_id: str) -> pd.Series:
    """Convierte las filas ``{period, value}`` en una ``pd.Series`` float ordenada.

    Los ``value`` nulos se conservan como ``NaN``; el periodo se normaliza a su inicio.

    Raises:
        ProviderError: Si algún periodo o valor no es interpretable.
    """
    try:
        return to_series([r["period"] for r in rows], [r.get("value") for r in rows], series_id)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProviderError(f"eia: {series_id}: formato de observaciones inválido: {exc}") from exc


def _reached(page: list[dict[str, Any]], start: date | None) -> bool:
    """``True`` si la página (desc) ya contiene periodos anteriores a ``start``."""
    if start is None or not page:
        return False
    return parse_period(str(page[-1].get("period"))) < pd.Timestamp(start)


def _frequency(name: object, series_id: str) -> Frequency:
    """Frecuencia de la respuesta (``daily``, ``monthly``...) o, si falta, la del sufijo
    del id clásico (``.D``, ``.W``, ``.M``, ``.Q``, ``.A``)."""
    try:
        return Frequency(str(name))
    except ValueError:
        suffix = series_id.rsplit(".", 1)[-1].upper()
        return FREQUENCY_CODES.get(suffix, Frequency.DAILY)
