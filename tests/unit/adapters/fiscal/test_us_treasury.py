"""Tests del adaptador de U.S. Treasury Fiscal Data con respuestas reales recortadas."""

from __future__ import annotations

import math
from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.fiscal.us_treasury import (
    DEFAULT_BASE_URL,
    FiscalQuery,
    UsTreasuryMacroProvider,
)
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

DEBT_URL = f"{DEFAULT_BASE_URL}/v2/accounting/od/debt_to_penny"
RATES_URL = f"{DEFAULT_BASE_URL}/v2/accounting/od/avg_interest_rates"
DEBT_META = {
    "labels": {
        "record_date": "Record Date",
        "tot_pub_debt_out_amt": "Total Public Debt Outstanding",
    },
    "dataTypes": {"record_date": "DATE", "tot_pub_debt_out_amt": "CURRENCY"},
    "total-pages": 1,
}


def debt(rows: list[tuple[str, str]], pages: int = 1) -> dict:
    data = [{"record_date": d, "tot_pub_debt_out_amt": v} for d, v in rows]
    return {"data": data, "meta": {**DEBT_META, "total-pages": pages}}


@pytest.fixture
def provider() -> UsTreasuryMacroProvider:
    return UsTreasuryMacroProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(UsTreasuryMacroProvider(), MacroProvider)


@responses.activate
def test_debt_to_penny_with_uppercased_id(provider: UsTreasuryMacroProvider) -> None:
    responses.get(
        DEBT_URL,
        json=debt([("2024-01-02", "33990127522066.83"), ("2024-01-03", "null")]),
        match=[
            matchers.query_param_matcher(
                {
                    "fields": "record_date,tot_pub_debt_out_amt",
                    "sort": "record_date",
                    "filter": "record_date:gte:2024-01-02,record_date:lte:2024-01-05",
                    "page[number]": "1",
                    "page[size]": "10000",
                }
            )
        ],
    )
    series = provider.fetch_series(
        "V2/ACCOUNTING/OD/DEBT_TO_PENNY:TOT_PUB_DEBT_OUT_AMT",  # así llega desde el servicio
        date(2024, 1, 2),
        date(2024, 1, 5),
        None,
    )
    assert (series.source, series.units) == ("us_treasury", "USD")
    assert series.name == "Total Public Debt Outstanding"
    assert series.data.iloc[0] == pytest.approx(33990127522066.83)
    assert math.isnan(series.data.iloc[1])  # "null" → NaN


@responses.activate
def test_paginates(provider: UsTreasuryMacroProvider) -> None:
    responses.get(DEBT_URL, json=debt([("2024-01-02", "1")], pages=2))
    responses.get(DEBT_URL, json=debt([("2024-01-03", "2")], pages=2))
    series = provider.fetch_series(
        "v2/accounting/od/debt_to_penny:tot_pub_debt_out_amt", None, None, None
    )
    assert "page%5Bnumber%5D=2" in responses.calls[1].request.url
    assert series.data.tolist() == [1.0, 2.0]
    assert series.frequency is Frequency.DAILY


@responses.activate
def test_filter_is_case_insensitive_and_required_for_multirow(
    provider: UsTreasuryMacroProvider,
) -> None:
    rows = [
        {
            "record_date": "2024-01-31",
            "security_desc": "Treasury Bills",
            "avg_interest_rate_amt": "5.411",
        },
        {
            "record_date": "2024-01-31",
            "security_desc": "Treasury Notes",
            "avg_interest_rate_amt": "2.340",
        },
        {
            "record_date": "2024-02-29",
            "security_desc": "Treasury Bills",
            "avg_interest_rate_amt": "5.389",
        },
    ]
    meta = {
        "labels": {"avg_interest_rate_amt": "Average Interest Rate Amount"},
        "dataTypes": {"avg_interest_rate_amt": "PERCENTAGE"},
        "total-pages": 1,
    }
    responses.get(RATES_URL, json={"data": rows, "meta": meta})
    responses.get(RATES_URL, json={"data": rows, "meta": meta})
    series = provider.fetch_series(
        "V2/ACCOUNTING/OD/AVG_INTEREST_RATES:AVG_INTEREST_RATE_AMT:SECURITY_DESC=TREASURY BILLS",
        None,
        None,
        None,
    )
    assert "security_desc" in responses.calls[0].request.url
    assert series.data.tolist() == [5.411, 5.389]
    assert series.units == "%"
    assert series.name == "Average Interest Rate Amount (TREASURY BILLS)"
    with pytest.raises(ProviderError, match="varias filas"):
        provider.fetch_series(
            "v2/accounting/od/avg_interest_rates:avg_interest_rate_amt", None, None, None
        )


@responses.activate
def test_errors(provider: UsTreasuryMacroProvider) -> None:
    responses.get(DEBT_URL, status=404, body="<html>404</html>")
    responses.get(DEBT_URL, json=debt([]))
    responses.get(DEBT_URL, status=400, json={"error": "Invalid Query Param"})
    sid = "v2/accounting/od/debt_to_penny:tot_pub_debt_out_amt"
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series(sid, None, None, None)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series(sid, None, None, None)
    with pytest.raises(ProviderError, match="HTTP 400: Invalid Query Param") as excinfo:
        provider.fetch_series(sid, None, None, None)
    assert type(excinfo.value) is ProviderError
    with pytest.raises(InvalidRequestError, match="vintages"):
        provider.fetch_series(sid, None, None, date(2020, 1, 1))


@pytest.mark.parametrize(
    ("body", "error", "message"),
    [
        # cuerpo real: campo de la serie o del filtro inexistente
        (
            {
                "error": "Invalid Query Param",
                "message": "Invalid query parameter: Field 'no_existe_amt' does not exist. "
                "For more information, please see the documentation.",
            },
            SeriesNotFoundError,
            r"no encontrado: Invalid query parameter: Field 'no_existe_amt' does not exist\.$",
        ),
        (
            {"error": "Invalid Query Param", "message": "Invalid filter operator 'xx'."},
            ProviderError,
            r"HTTP 400: Invalid filter operator 'xx'\.$",
        ),
    ],
    ids=["field-does-not-exist", "other-400"],
)
@responses.activate
def test_400_uses_the_message_from_the_body(
    provider: UsTreasuryMacroProvider, body: dict, error: type[Exception], message: str
) -> None:
    responses.get(DEBT_URL, status=400, json=body)
    with pytest.raises(error, match=message) as excinfo:
        provider.fetch_series("v2/accounting/od/debt_to_penny:no_existe_amt", None, None, None)
    assert type(excinfo.value) is error


@pytest.mark.parametrize("bad", ["debt_to_penny", ":field", "e:f:nofilter", "e:f:=v", "e:f:k="])
def test_query_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(InvalidRequestError):
        FiscalQuery.parse(bad)
