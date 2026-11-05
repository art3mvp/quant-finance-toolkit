"""Adaptador outbound de Eurostat (API SDMX 2.1 de difusión).

Ids de ejemplo (``<dataset>/<clave>``; dimensiones en el orden del dataset):
    * ``prc_hicp_manr/M.RCH_A.CP00.ES``    → inflación HICP de España, tasa anual.
    * ``une_rt_m/M.SA.TOTAL.PC_ACT.T.ES``  → tasa de paro de España, desestacionalizada.
    * ``namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.ES`` → PIB real de España, variación trimestral.

Sin API key. El CSV no trae título; la unidad es el código de la dimensión ``unit``.
Una dimensión inválida se rechaza con HTTP 400 (``ProviderError``).
"""

from __future__ import annotations

from toolkit.adapters.outbound._sdmx import SdmxMacroProvider


class EurostatMacroProvider(SdmxMacroProvider):
    """Series de Eurostat: precios, empleo, cuentas nacionales de la UE."""

    name = "eurostat"
    DEFAULT_BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
    FORMAT_PARAMS = {"format": "SDMX-CSV"}  # noqa: RUF012 - constante de clase
