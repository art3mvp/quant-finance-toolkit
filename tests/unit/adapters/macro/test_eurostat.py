"""Tests del adaptador de Eurostat con un CSV real (sin red)."""

from __future__ import annotations

import pytest
import responses

from toolkit.adapters.outbound.macro.eurostat import EurostatMacroProvider
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

BASE = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
URL = f"{BASE}/PRC_HICP_MANR/M.RCH_A.CP00.ES"  # el servicio pasa los ids a mayúsculas
CSV = (
    "DATAFLOW,LAST UPDATE,freq,unit,coicop,geo,TIME_PERIOD,OBS_VALUE,OBS_FLAG,CONF_STATUS\r\n"
    "ESTAT:PRC_HICP_MANR(1.0),06/02/26 23:00:00,M,RCH_A,CP00,ES,2024-01,3.5,,\r\n"
    "ESTAT:PRC_HICP_MANR(1.0),06/02/26 23:00:00,M,RCH_A,CP00,ES,2024-02,2.9,,\r\n"
)


def test_satisfies_port() -> None:
    assert isinstance(EurostatMacroProvider(), MacroProvider)


@responses.activate
def test_fetches_hicp_with_lowercase_dimension_columns() -> None:
    responses.get(URL, body=CSV)
    series = EurostatMacroProvider().fetch_series("PRC_HICP_MANR/M.RCH_A.CP00.ES", None, None, None)
    assert "format=SDMX-CSV" in responses.calls[0].request.url
    assert (series.source, series.name, series.units) == ("eurostat", None, "RCH_A")
    assert series.frequency is Frequency.MONTHLY
    assert series.data.tolist() == [3.5, 2.9]


def fault(code: str, text: str) -> str:
    """Cuerpo de error real de Eurostat (fallo SOAP), con el escapado XML incluido."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?><S:Fault xmlns:S="http://schemas.xmlsoap.org/'
        f'soap/envelope/"><faultcode>{code}</faultcode><faultstring>{text}</faultstring></S:Fault>'
    )


VALUE_NOT_ALLOWED = (
    "INVALID_QUERY_DIMENSION_VALUE: Query is invalid as per its structure&apos;s definition. "
    "The following values for dimension are not allowed: GEO=XX."
)


@pytest.mark.parametrize(
    ("status", "body", "error", "message"),
    [
        (400, fault("150", VALUE_NOT_ALLOWED), SeriesNotFoundError, "no encontrado: GEO=XX$"),
        (
            404,
            fault("100", "ERR_NOT_FOUND_2: DATA_SET:X is not available for dissemination."),
            SeriesNotFoundError,
            "DATA_SET:X is not available",
        ),
        (
            400,
            fault("140", "INVALID_QUERY_NB_FILTERS: Incorrect number of filters"),
            InvalidRequestError,
            "clave mal formada",
        ),
        (400, fault("999", "OTRO_FALLO: algo"), ProviderError, r"fallo 999\): OTRO_FALLO"),
        (400, "Bad Request", ProviderError, "HTTP 400: Bad Request"),  # sin fallo SOAP
    ],
    ids=["value-not-allowed", "unknown-dataset", "malformed-key", "other-fault", "no-fault"],
)
@responses.activate
def test_fault_codes_are_translated(
    status: int, body: str, error: type[Exception], message: str
) -> None:
    provider = EurostatMacroProvider(sleep=lambda _: None)
    responses.get(URL, status=status, body=body, content_type="application/xml")
    with pytest.raises(error, match=message) as excinfo:
        provider.fetch_series("PRC_HICP_MANR/M.RCH_A.CP00.ES", None, None, None)
    assert type(excinfo.value) is error
    assert "<?xml" not in str(excinfo.value)  # el motivo, nunca el XML de la respuesta
