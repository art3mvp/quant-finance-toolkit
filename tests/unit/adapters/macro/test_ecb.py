"""Tests del adaptador del BCE con un CSV real recortado (sin red)."""

from __future__ import annotations

from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.macro.ecb import EcbMacroProvider
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A"
# Columnas reales del servicio (recortadas a las relevantes, mismo orden).
CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE,OBS_STATUS,"
    "TITLE,UNIT,UNIT_MULT\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-02,1.0956,A,"
    "US dollar/Euro ECB reference exchange rate,USD,0\n"
    "EXR.D.USD.EUR.SP00.A,D,USD,EUR,SP00,A,2024-01-03,1.0919,A,"
    "US dollar/Euro ECB reference exchange rate,USD,0\n"
)


def test_satisfies_port() -> None:
    assert isinstance(EcbMacroProvider(), MacroProvider)


@responses.activate
def test_fetches_exchange_rate_as_csvdata() -> None:
    responses.get(
        URL,
        body=CSV,
        match=[matchers.query_param_matcher({"format": "csvdata", "startPeriod": "2024-01-02"})],
    )
    series = EcbMacroProvider().fetch_series("EXR/D.USD.EUR.SP00.A", date(2024, 1, 2), None, None)
    assert series.source == "ecb"
    assert series.name == "US dollar/Euro ECB reference exchange rate"
    assert series.units == "USD"
    assert series.frequency is Frequency.DAILY
    assert series.data.tolist() == pytest.approx([1.0956, 1.0919])
