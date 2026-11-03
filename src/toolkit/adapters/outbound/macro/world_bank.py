"""Adaptador outbound del Banco Mundial (World Bank Indicators API v2).

Identificador: ``"<país ISO3>/<indicador>"``, p. ej.:
    * ``ESP/NY.GDP.MKTP.CD``   → PIB de España en USD corrientes (anual).
    * ``USA/FP.CPI.TOTL.ZG``   → inflación de EE. UU. (anual, %).
    * ``EMU/SL.UEM.TOTL.ZS``   → paro de la eurozona (% población activa).

Particularidades (verificadas contra el servicio real):
    * La respuesta es ``[metadatos, filas]``; los errores llegan con HTTP 200 como
      ``[{"message": [...]}]`` y "sin datos" como ``[metadatos, null]``.
    * El filtro ``date`` es por años (``2019:2021``); el rango exacto se recorta en local.
    * Los periodos son ``2020``, ``2020Q1`` o ``2020M01`` según la frecuencia.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import FREQUENCY_CODES, to_series
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import MacroSeries

DEFAULT_BASE_URL = "https://api.worldbank.org/v2"
PAGE_SIZE = 20000


class WorldBankMacroProvider:
    """Indicadores de desarrollo del Banco Mundial por país (sin API key).

    Args:
        base_url: URL base de la API v2.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "world_bank"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, **http_options: Any) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(self.name, **http_options)

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga ``<país>/<indicador>`` y lo recorta a ``[start, end]``.

        Raises:
            InvalidRequestError: Si el id no tiene la forma ``país/indicador``.
            SeriesNotFoundError: Si el indicador o país no existe o no hay datos.
            ProviderError: Si se pide ``as_of`` o el formato es inválido.
        """
        if as_of is not None:
            raise ProviderError(f"world_bank: {series_id}: la API no ofrece vintages (as_of)")
        country, indicator = _split(series_id)
        params: dict[str, Any] = {"format": "json", "per_page": PAGE_SIZE}
        if start is not None or end is not None:
            params["date"] = f"{(start or date(1960, 1, 1)).year}:{(end or date.today()).year}"
        rows = self._fetch_rows(
            f"{self.base_url}/country/{country}/indicator/{indicator}", params, series_id
        )
        periods = [str(r["date"]) for r in rows]
        try:
            data = to_series(periods, [r.get("value") for r in rows], series_id)
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(f"world_bank: {series_id}: observaciones inválidas: {exc}") from exc
        data = data.loc[pd.Timestamp(start) if start else None : pd.Timestamp(end) if end else None]
        if data.dropna().empty:
            raise SeriesNotFoundError(f"world_bank: {series_id}: sin datos en el rango solicitado")
        first = rows[0]
        return MacroSeries(
            series_id=series_id,
            name=(first.get("indicator") or {}).get("value") or None,
            source=self.name,
            units=first.get("unit") or None,
            frequency=FREQUENCY_CODES[_frequency_code(periods[0])],
            data=data,
        )

    def _fetch_rows(self, url: str, params: dict[str, Any], series_id: str) -> list[dict[str, Any]]:
        """Recorre todas las páginas y devuelve las filas."""
        rows: list[dict[str, Any]] = []
        page, pages = 1, 1
        while page <= pages:
            payload = self._http.get_json(url, {**params, "page": page}, identifier=series_id)
            meta, page_rows = _unpack(payload, series_id)
            rows.extend(page_rows)
            pages = int(meta.get("pages") or 1)
            page += 1
        if not rows:
            raise SeriesNotFoundError(f"world_bank: {series_id}: sin observaciones")
        return rows


def _split(series_id: str) -> tuple[str, str]:
    country, _, indicator = series_id.strip().partition("/")
    if not country or not indicator or "/" in indicator:
        raise InvalidRequestError(
            f"id inválido {series_id!r}: usa '<país ISO3>/<indicador>', p. ej. ESP/NY.GDP.MKTP.CD"
        )
    return country, indicator


def _unpack(payload: Any, series_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Separa ``[meta, filas]`` y traduce los errores que llegan con HTTP 200."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ProviderError(f"world_bank: {series_id}: respuesta inesperada")
    if "message" in payload[0]:
        messages = payload[0]["message"] or [{}]
        detail = messages[0].get("value") or messages[0].get("key") or "error"
        raise SeriesNotFoundError(f"world_bank: {series_id}: {detail}")
    rows = payload[1] if len(payload) > 1 else None
    if rows is None:
        raise SeriesNotFoundError(f"world_bank: {series_id}: sin observaciones")
    if not isinstance(rows, list):
        raise ProviderError(f"world_bank: {series_id}: filas con formato inválido")
    return payload[0], rows


def _frequency_code(period: str) -> str:
    """``2020M01`` → ``M``; ``2020Q1`` → ``Q``; ``2020`` → ``A``."""
    for code in ("M", "Q"):
        if code in period.upper():
            return code
    return "A"
