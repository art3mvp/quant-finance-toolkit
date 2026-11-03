"""Tests del adaptador de Eurostat con un CSV real (sin red)."""

from __future__ import annotations

import pytest
import responses

from toolkit.adapters.outbound.macro.eurostat import EurostatMacroProvider
from toolkit.domain.errors import ProviderError, SeriesNotFoundError
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


@responses.activate
def test_invalid_dimension_is_provider_error() -> None:
    provider = EurostatMacroProvider(sleep=lambda _: None)
    responses.get(URL, status=400, body="INVALID_QUERY_DIMENSION_VALUE: GEO=XX")
    with pytest.raises(ProviderError) as excinfo:
        provider.fetch_series("PRC_HICP_MANR/M.RCH_A.CP00.ES", None, None, None)
    assert not isinstance(excinfo.value, SeriesNotFoundError)
