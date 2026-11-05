"""Tests del adaptador del BIS con un CSV real recortado (sin red)."""

from __future__ import annotations

from datetime import date

import responses
from responses import matchers

from toolkit.adapters.outbound.macro.bis import BisMacroProvider
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

URL = "https://stats.bis.org/api/v1/data/WS_EER/M.N.B.ES"
CSV = (
    "FREQ,EER_TYPE,EER_BASKET,REF_AREA,UNIT_MEASURE,TIME_FORMAT,COLLECTION,TITLE_TS,"
    "TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,OBS_PRE_BREAK\n"
    "M,N,B,ES,882,,A,Spain - Nominal - Broad (64 economies),2024-01,104.38,A,F,\n"
    "M,N,B,ES,882,,A,Spain - Nominal - Broad (64 economies),2024-02,104.32,A,F,\n"
)


def test_satisfies_port() -> None:
    assert isinstance(BisMacroProvider(), MacroProvider)


@responses.activate
def test_fetches_effective_exchange_rate() -> None:
    responses.get(
        URL,
        body=CSV,
        match=[matchers.query_param_matcher({"format": "csv", "endPeriod": "2024-02-29"})],
    )
    series = BisMacroProvider().fetch_series("WS_EER/M.N.B.ES", None, date(2024, 2, 29), None)
    assert series.source == "bis"
    assert series.name == "Spain - Nominal - Broad (64 economies)"  # de TITLE_TS
    assert series.units == "882"
    assert series.frequency is Frequency.MONTHLY
    assert series.data.tolist() == [104.38, 104.32]
