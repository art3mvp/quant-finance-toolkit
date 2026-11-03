"""Adaptador outbound del Banco de España (API BIEST, ``srdatosapp/listaSeries``).

Ids de ejemplo (códigos de serie del BdE):
    * ``D_1NBAF472``  → Euríbor a un año (mensual, %).

Particularidades (verificadas contra el servicio real):
    * El orden de los parámetros importa: ``idioma`` primero. Con ``idioma=en`` este
      endpoint responde 412, así que se fija ``es`` (solo afecta a las descripciones).
    * Una serie inexistente también responde **412**: se traduce a ``SeriesNotFoundError``.
    * ``rango=MAX`` devuelve todo el histórico en columnas paralelas ``fechas``/``valores``
      (más reciente primero, fechas con hora UTC); el rango se recorta en local.
    * Sin vintages: ``as_of`` no está soportado.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import frequency_from_code, to_series
from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import MacroSeries

DEFAULT_BASE_URL = "https://app.bde.es/bierest/resources/srdatosapp"


class BancoEspanaMacroProvider:
    """Series del Banco de España: tipos de interés, crédito, balanza de pagos...

    Args:
        base_url: URL base de ``srdatosapp``.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "banco_espana"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, **http_options: Any) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(self.name, not_found_status=(404, 412), **http_options)

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga el histórico completo de ``series_id`` y lo recorta a ``[start, end]``.

        Raises:
            SeriesNotFoundError: Si la serie no existe o no hay datos en el rango.
            ProviderError: Si se pide ``as_of`` o el formato es inválido.
        """
        if as_of is not None:
            raise ProviderError(f"banco_espana: {series_id}: la API no ofrece vintages (as_of)")
        payload = self._http.get_json(
            f"{self.base_url}/listaSeries",
            {"idioma": "es", "series": series_id, "rango": "MAX"},  # idioma primero
            identifier=series_id,
        )
        item = _single_series(payload, series_id)
        try:
            data = to_series(list(item["fechas"]), list(item["valores"]), series_id)
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(
                f"banco_espana: {series_id}: observaciones inválidas: {exc}"
            ) from exc
        data = data.loc[pd.Timestamp(start) if start else None : pd.Timestamp(end) if end else None]
        if data.empty:
            raise SeriesNotFoundError(
                f"banco_espana: {series_id}: sin datos en el rango solicitado"
            )
        return MacroSeries(
            series_id=series_id,
            name=item.get("descripcionCorta") or item.get("descripcion") or None,
            source=self.name,
            units=item.get("simbolo") or None,
            frequency=frequency_from_code(item.get("codFrecuencia"), data.index, series_id),
            data=data,
        )


def _single_series(payload: Any, series_id: str) -> dict[str, Any]:
    """Devuelve el único objeto serie de la respuesta (una lista de un elemento)."""
    if not isinstance(payload, list):
        raise ProviderError(f"banco_espana: {series_id}: respuesta inesperada")
    if not payload:
        raise SeriesNotFoundError(f"banco_espana: {series_id}: serie no encontrada")
    item = payload[0]
    if not isinstance(item, dict) or len(item.get("fechas") or []) != len(
        item.get("valores") or []
    ):
        raise ProviderError(f"banco_espana: {series_id}: fechas y valores no cuadran")
    if not item.get("fechas"):
        raise SeriesNotFoundError(f"banco_espana: {series_id}: serie sin observaciones")
    return item
