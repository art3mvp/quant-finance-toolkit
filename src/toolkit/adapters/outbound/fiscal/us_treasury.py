"""Adaptador outbound de U.S. Treasury Fiscal Data (``api.fiscaldata.treasury.gov``).

Identificador: ``"<endpoint>:<campo>[:<campo_filtro>=<valor>]"``, p. ej.:
    * ``v2/accounting/od/debt_to_penny:tot_pub_debt_out_amt``
      → deuda pública total de EE. UU., diaria (USD).
    * ``v2/accounting/od/avg_interest_rates:avg_interest_rate_amt:security_desc=Treasury Bills``
      → tipo medio de las Letras del Tesoro en circulación, mensual (%).

Particularidades (verificadas contra el servicio real):
    * Sin API key. Paginación con ``page[number]``/``page[size]`` y ``meta.total-pages``.
    * Algunos endpoints tienen varias filas por fecha (una por tipo de valor, país...):
      hace falta el filtro ``campo=valor``. Se aplica en local y sin distinguir mayúsculas
      (``Treasury Bills`` = ``TREASURY BILLS``).
    * Endpoints y campos van en minúsculas en la API: se normalizan aquí.
    * ``meta.labels`` da el nombre legible y ``meta.dataTypes`` el tipo (``CURRENCY`` → USD,
      ``PERCENTAGE`` → %). Los huecos llegan como la cadena ``"null"``.
    * ``record_date`` es el último día del periodo (p. ej. ``2024-01-31``); se refecha al
      inicio (``2024-01-01``), la convención del dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import infer_frequency, to_period_start, to_series
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import MacroSeries

DEFAULT_BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
PAGE_SIZE = 10000
_UNITS = {"CURRENCY": "USD", "PERCENTAGE": "%"}


@dataclass(frozen=True)
class FiscalQuery:
    """Id de serie ya interpretado: endpoint, campo de valor y filtro opcional."""

    endpoint: str
    field: str
    filter_field: str | None = None
    filter_value: str | None = None

    @classmethod
    def parse(cls, series_id: str) -> FiscalQuery:
        """Interpreta ``endpoint:campo[:filtro=valor]``.

        Raises:
            InvalidRequestError: Si el formato no es válido.
        """
        parts = series_id.strip().split(":", 2)
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise InvalidRequestError(
                f"id inválido {series_id!r}: usa '<endpoint>:<campo>[:<filtro>=<valor>]'"
            )
        endpoint, field = parts[0].strip("/").lower(), parts[1].lower()
        if len(parts) == 2:
            return cls(endpoint, field)
        key, sep, value = parts[2].partition("=")
        if not sep or not key or not value:
            raise InvalidRequestError(f"filtro inválido en {series_id!r}: usa campo=valor")
        return cls(endpoint, field, key.lower(), value)

    @property
    def fields(self) -> str:
        """Columnas a pedir a la API (``fields=``)."""
        extra = [self.filter_field] if self.filter_field else []
        return ",".join(["record_date", self.field, *extra])

    def matches(self, row: dict[str, Any]) -> bool:
        """``True`` si la fila pasa el filtro (sin distinguir mayúsculas)."""
        if self.filter_field is None:
            return True
        return str(row.get(self.filter_field, "")).casefold() == str(self.filter_value).casefold()


class UsTreasuryMacroProvider:
    """Series fiscales del Tesoro de EE. UU. (deuda, tipos medios, ingresos y gastos).

    Args:
        base_url: URL base de ``fiscal_service``.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "us_treasury"

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
        """Descarga ``series_id`` en ``[start, end]`` (filtrado en la API por ``record_date``).

        Raises:
            InvalidRequestError: Si se pide ``as_of`` (la fuente no publica vintages).
            InvalidRequestError: Si el id no tiene el formato esperado.
            SeriesNotFoundError: Si el endpoint no existe o no hay filas.
            ProviderError: Si hay varias filas por fecha (falta un
                filtro) o el formato es inválido.
        """
        if as_of is not None:
            raise InvalidRequestError(
                f"us_treasury: {series_id}: la API no ofrece vintages (as_of)"
            )
        query = FiscalQuery.parse(series_id)
        rows, meta = self._fetch_rows(query, start, end, series_id)
        rows = [r for r in rows if query.matches(r)]
        if not rows:
            raise SeriesNotFoundError(f"us_treasury: {series_id}: sin filas para el filtro/rango")
        dates = [str(r["record_date"]) for r in rows]
        if len(set(dates)) != len(dates):
            raise ProviderError(
                f"us_treasury: {series_id}: varias filas por fecha; añade ':<campo>=<valor>'"
            )
        try:
            data = to_series(dates, [_value(r.get(query.field)) for r in rows], series_id)
        except (ValueError, TypeError) as exc:
            raise ProviderError(f"us_treasury: {series_id}: valores inválidos: {exc}") from exc
        frequency = infer_frequency(data.index)
        return MacroSeries(
            series_id=series_id,
            name=_label(meta, query),
            source=self.name,
            units=_UNITS.get(str((meta.get("dataTypes") or {}).get(query.field))),
            frequency=frequency,
            data=to_period_start(data, frequency),
        )

    def _fetch_rows(
        self, query: FiscalQuery, start: date | None, end: date | None, series_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Pide todas las páginas; devuelve las filas y los metadatos de la primera."""
        filters = [f"record_date:gte:{start.isoformat()}"] if start else []
        filters += [f"record_date:lte:{end.isoformat()}"] if end else []
        params: dict[str, Any] = {"fields": query.fields, "sort": "record_date"}
        if filters:
            params["filter"] = ",".join(filters)
        rows: list[dict[str, Any]] = []
        meta: dict[str, Any] = {}
        page, pages = 1, 1
        while page <= pages:
            payload = self._http.get_json(
                f"{self.base_url}/{query.endpoint}",
                {**params, "page[number]": page, "page[size]": PAGE_SIZE},
                identifier=series_id,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ProviderError(f"us_treasury: {series_id}: respuesta sin 'data'")
            meta = meta or payload.get("meta") or {}
            rows.extend(payload["data"])
            pages = int((payload.get("meta") or {}).get("total-pages") or 1)
            page += 1
        return rows, meta


def _value(raw: Any) -> Any:
    """La API usa la cadena ``"null"`` para los huecos."""
    return None if raw in (None, "", "null") else raw


def _label(meta: dict[str, Any], query: FiscalQuery) -> str | None:
    """Nombre legible del campo, con el filtro si lo hay."""
    label = (meta.get("labels") or {}).get(query.field)
    if label and query.filter_value:
        return f"{label} ({query.filter_value})"
    return label or None
