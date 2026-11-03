"""Adaptador outbound del Banco Central Europeo (ECB Data Portal, API SDMX).

Ids de ejemplo (``<flujo>/<clave>``):
    * ``EXR/D.USD.EUR.SP00.A``         → tipo de cambio de referencia USD/EUR, diario.
    * ``ICP/M.U2.N.000000.4.ANR``      → inflación HICP de la eurozona, tasa anual.
    * ``FM/B.U2.EUR.4F.KR.DFR.LEV``    → tipo de la facilidad de depósito del BCE.

Sin API key. Título y unidad salen de las columnas ``TITLE`` y ``UNIT`` del CSV.
"""

from __future__ import annotations

from toolkit.adapters.outbound._sdmx import SdmxMacroProvider


class EcbMacroProvider(SdmxMacroProvider):
    """Series del BCE: tipos de cambio, tipos oficiales, inflación, agregados monetarios."""

    name = "ecb"
    DEFAULT_BASE_URL = "https://data-api.ecb.europa.eu/service/data"
    FORMAT_PARAMS = {"format": "csvdata"}  # noqa: RUF012 - constante de clase
