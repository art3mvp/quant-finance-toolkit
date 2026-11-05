"""Adaptador outbound del BIS (Bank for International Settlements), API SDMX v1.

Ids de ejemplo (``<flujo>/<clave>``):
    * ``WS_EER/M.N.B.ES``      → tipo de cambio efectivo nominal de España (cesta amplia).
    * ``WS_CBPOL/M.US``        → tipo de interés oficial de la Fed, mensual.
    * ``WS_SPP/Q.ES.N.628``    → precios de vivienda residencial en España.

Sin API key. ``UNIT_MEASURE`` es un código (p. ej. ``882``), no un texto legible.
"""

from __future__ import annotations

from toolkit.adapters.outbound._sdmx import SdmxMacroProvider


class BisMacroProvider(SdmxMacroProvider):
    """Series del BIS: tipos de cambio efectivos, tipos oficiales, crédito, vivienda."""

    name = "bis"
    DEFAULT_BASE_URL = "https://stats.bis.org/api/v1/data"
    FORMAT_PARAMS = {"format": "csv"}  # noqa: RUF012 - constante de clase
