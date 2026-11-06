"""Adaptador outbound de Eurostat (API SDMX 2.1 de difusión).

Ids de ejemplo (``<dataset>/<clave>``; dimensiones en el orden del dataset):
    * ``prc_hicp_manr/M.RCH_A.CP00.ES``    → inflación HICP de España, tasa anual.
    * ``une_rt_m/M.SA.TOTAL.PC_ACT.T.ES``  → tasa de paro de España, desestacionalizada.
    * ``namq_10_gdp/Q.CLV_PCH_PRE.SCA.B1GQ.ES`` → PIB real de España, variación trimestral.

Sin API key. El CSV no trae título; la unidad es el código de la dimensión ``unit``.

Errores (verificados contra el servicio real). Eurostat no usa el estado HTTP para el
motivo sino un ``faultcode`` SOAP en el cuerpo XML:

* ``100`` (HTTP 404): el dataset no existe → ``SeriesNotFoundError``.
* ``150`` (HTTP 400) ``INVALID_QUERY_DIMENSION_VALUE``: un valor de la clave no existe
  (``GEO=XX``) o no hay datos en el rango (``TIME_PERIOD``) → ``SeriesNotFoundError``.
* ``140`` (HTTP 400) ``INVALID_QUERY_NB_FILTERS``: la clave no tiene el número de
  dimensiones del dataset → ``InvalidRequestError``.
* Cualquier otro fallo → ``ProviderError`` con el ``faultstring`` (nunca el XML).
"""

from __future__ import annotations

import html
import re

from toolkit.adapters.outbound._sdmx import SdmxMacroProvider
from toolkit.domain.errors import (
    InvalidRequestError,
    ProviderError,
    SeriesNotFoundError,
    ToolkitError,
)

_FAULT = re.compile(
    r"<faultcode>\s*(?P<code>[^<]+?)\s*</faultcode>\s*<faultstring>(?P<text>.*?)</faultstring>",
    flags=re.S,
)
#: Fallos que significan "la serie no existe o no tiene datos en el rango".
NOT_FOUND_FAULTS = frozenset({"100", "150"})
#: Fallos que significan "la clave está mal formada".
MALFORMED_FAULTS = frozenset({"140"})


def map_error(status: int, body: str) -> ToolkitError | None:
    """Traduce el ``faultcode`` de Eurostat; ``None`` si el cuerpo no es un fallo SOAP."""
    match = _FAULT.search(body)
    if match is None:
        return None
    code = match["code"]
    text = " ".join(html.unescape(match["text"]).split())
    detail = (
        text.split("are not allowed:", 1)[1].strip(" .") if "are not allowed:" in text else text
    )
    if code in NOT_FOUND_FAULTS:
        return SeriesNotFoundError(f"no encontrado: {detail}")
    if code in MALFORMED_FAULTS:
        return InvalidRequestError(f"clave mal formada: {text}")
    return ProviderError(f"HTTP {status} (fallo {code}): {text}")


class EurostatMacroProvider(SdmxMacroProvider):
    """Series de Eurostat: precios, empleo, cuentas nacionales de la UE."""

    name = "eurostat"
    DEFAULT_BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
    FORMAT_PARAMS = {"format": "SDMX-CSV"}  # noqa: RUF012 - constante de clase
    map_error = staticmethod(map_error)
