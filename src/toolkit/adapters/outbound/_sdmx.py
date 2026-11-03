"""Base común para fuentes estadísticas SDMX REST en formato CSV (BCE, BIS, Eurostat).

No es un adaptador por sí mismo: cada fuente concreta hereda de ``SdmxMacroProvider`` y
solo declara su nombre, URL y parámetro de formato.

Identificador de serie: ``"<flujo>/<clave>"``, p. ej. ``EXR/D.USD.EUR.SP00.A``.
La clave debe fijar **todas** las dimensiones (una sola serie); si la consulta devuelve
varias (comodines o ``+``), se rechaza para no mezclar series en una ``MacroSeries``.

Verificado contra los tres servicios: aceptan ``startPeriod``/``endPeriod`` en ISO
(``YYYY-MM-DD``) para cualquier frecuencia y devuelven 404 si no hay datos.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, ClassVar

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import frequency_from_code, to_series
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import MacroSeries


class SdmxMacroProvider:
    """Proveedor ``MacroProvider`` genérico sobre una API SDMX REST con salida CSV.

    Args:
        base_url: URL base hasta ``.../data`` (por defecto la de la subclase).
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name: ClassVar[str] = "sdmx"
    DEFAULT_BASE_URL: ClassVar[str] = ""
    #: Parámetros fijos que piden CSV a la API.
    FORMAT_PARAMS: ClassVar[Mapping[str, str]] = {"format": "csv"}
    #: Columnas candidatas para cada metadato, por orden de preferencia.
    NAME_COLUMNS: ClassVar[Sequence[str]] = ("TITLE", "TITLE_TS")
    UNIT_COLUMNS: ClassVar[Sequence[str]] = ("UNIT", "UNIT_MEASURE", "unit")
    FREQ_COLUMNS: ClassVar[Sequence[str]] = ("FREQ", "freq")

    def __init__(self, base_url: str | None = None, **http_options: Any) -> None:
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._http = HttpClient(self.name, **http_options)

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga ``<flujo>/<clave>`` en ``[start, end]``.

        Raises:
            InvalidRequestError: Si el id no tiene la forma ``flujo/clave``.
            SeriesNotFoundError: Si no hay datos (404 o CSV vacío).
            ProviderError: Si se pide ``as_of``, la clave devuelve varias series o el
                formato es inválido.
        """
        if as_of is not None:
            raise ProviderError(f"{self.name}: {series_id}: la API no ofrece vintages (as_of)")
        flow, key = split_series_id(series_id)
        params: dict[str, str] = dict(self.FORMAT_PARAMS)
        if start is not None:
            params["startPeriod"] = start.isoformat()
        if end is not None:
            params["endPeriod"] = end.isoformat()
        text = self._http.get_text(f"{self.base_url}/{flow}/{key}", params, identifier=series_id)
        return self._to_macro_series(text, series_id)

    def _to_macro_series(self, text: str, series_id: str) -> MacroSeries:
        frame = read_csv(text, self.name, series_id)
        if frame["TIME_PERIOD"].duplicated().any():
            raise ProviderError(
                f"{self.name}: {series_id}: la clave devuelve varias series; "
                "fija todas las dimensiones (sin comodines ni '+')"
            )
        try:
            data = to_series(frame["TIME_PERIOD"].tolist(), _values(frame), series_id)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                f"{self.name}: {series_id}: observaciones inválidas: {exc}"
            ) from exc
        return MacroSeries(
            series_id=series_id,
            name=_first(frame, self.NAME_COLUMNS),
            source=self.name,
            units=_first(frame, self.UNIT_COLUMNS),
            frequency=frequency_from_code(_first(frame, self.FREQ_COLUMNS), data.index, series_id),
            data=data,
        )


def split_series_id(series_id: str) -> tuple[str, str]:
    """``"EXR/D.USD.EUR.SP00.A"`` → ``("EXR", "D.USD.EUR.SP00.A")``.

    Raises:
        InvalidRequestError: Si falta el flujo o la clave.
    """
    flow, _, key = series_id.strip().partition("/")
    if not flow or not key or "/" in key:
        raise InvalidRequestError(
            f"id SDMX inválido {series_id!r}: usa '<flujo>/<clave>', p. ej. EXR/D.USD.EUR.SP00.A"
        )
    return flow, key


def read_csv(text: str, source: str, series_id: str) -> pd.DataFrame:
    """Lee el CSV SDMX como texto y comprueba las columnas obligatorias.

    Raises:
        SeriesNotFoundError: Si no hay filas.
        ProviderError: Si faltan ``TIME_PERIOD``/``OBS_VALUE`` o el CSV es ilegible.
    """
    if not text.strip():
        raise SeriesNotFoundError(f"{source}: {series_id}: respuesta vacía")
    try:
        frame = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except (ValueError, pd.errors.ParserError) as exc:
        raise ProviderError(f"{source}: {series_id}: CSV ilegible: {exc}") from exc
    missing = {"TIME_PERIOD", "OBS_VALUE"} - set(frame.columns)
    if missing:
        raise ProviderError(f"{source}: {series_id}: CSV sin columnas {sorted(missing)}")
    if frame.empty:
        raise SeriesNotFoundError(f"{source}: {series_id}: sin observaciones")
    return frame


def _values(frame: pd.DataFrame) -> list[object]:
    """Valores de ``OBS_VALUE`` con las celdas vacías como ``None`` (→ ``NaN``)."""
    return [value if value.strip() else None for value in frame["OBS_VALUE"]]


def _first(frame: pd.DataFrame, columns: Sequence[str]) -> str | None:
    """Primer valor no vacío de la primera columna presente de ``columns``."""
    for column in columns:
        if column in frame:
            values = [v for v in frame[column] if v.strip()]
            if values:
                return values[0]
    return None
