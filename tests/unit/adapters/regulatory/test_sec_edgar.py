"""Tests del adaptador SEC EDGAR con respuestas reales recortadas (sin red)."""

from __future__ import annotations

from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.regulatory.sec_edgar import (
    DEFAULT_DATA_URL,
    DEFAULT_TICKERS_URL,
    ConceptQuery,
    SecEdgarMacroProvider,
    select_facts,
)
from toolkit.domain.errors import (
    ConfigurationError,
    InvalidRequestError,
    ProviderError,
    SeriesNotFoundError,
)
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

UA = "Test Runner test@example.org"
FACTS_URL = f"{DEFAULT_DATA_URL}/companyfacts/CIK0000320193.json"
TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


def flow(start: str, end: str, val: float, filed: str, form: str = "10-Q") -> dict:
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form, "accn": filed}


FACTS = {
    "cik": 320193,
    "facts": {
        "us-gaap": {
            "Assets": {
                "label": "Assets",
                "units": {
                    "USD": [
                        {"end": "2025-12-27", "val": 100.0, "filed": "2026-01-30", "accn": "a"},
                        # comparativo reexpresado en una presentación posterior
                        {"end": "2025-12-27", "val": 101.0, "filed": "2026-05-01", "accn": "b"},
                        {"end": "2026-03-28", "val": 110.0, "filed": "2026-05-01", "accn": "b"},
                    ]
                },
            },
            "Revenues": {
                "label": "Revenues",
                "units": {
                    "USD": [
                        flow("2025-12-28", "2026-03-28", 10.0, "2026-05-01"),
                        flow("2025-09-28", "2026-06-27", 30.0, "2026-07-31"),  # 9M acumulado
                        flow("2026-03-29", "2026-06-27", 11.0, "2026-07-31"),
                        flow("2025-09-28", "2026-09-26", 45.0, "2026-11-03", "10-K"),
                    ]
                },
            },
        }
    },
}


@pytest.fixture
def provider() -> SecEdgarMacroProvider:
    return SecEdgarMacroProvider(user_agent=UA, sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(SecEdgarMacroProvider(user_agent=None), MacroProvider)


@responses.activate
def test_ticker_and_uppercased_concept_resolve_case_insensitively(
    provider: SecEdgarMacroProvider,
) -> None:
    responses.get(DEFAULT_TICKERS_URL, json=TICKERS)
    responses.get(FACTS_URL, json=FACTS, match=[matchers.header_matcher({"User-Agent": UA})])
    series = provider.fetch_series("AAPL/US-GAAP/ASSETS", None, None, None)
    assert (series.source, series.name, series.units) == ("sec_edgar", "Assets", "USD")
    assert series.data.tolist() == [101.0, 110.0]  # gana la reexpresión


@responses.activate
def test_facts_are_cached_per_company(provider: SecEdgarMacroProvider) -> None:
    responses.get(FACTS_URL, json=FACTS)
    provider.fetch_series("320193/Assets", None, None, None)
    provider.fetch_series("CIK0000320193/us-gaap/Revenues", None, None, None)
    assert len(responses.calls) == 1


@responses.activate
def test_flow_concepts_by_quarter_and_year(provider: SecEdgarMacroProvider) -> None:
    responses.get(FACTS_URL, json=FACTS)
    quarterly = provider.fetch_series("320193/Revenues", None, None, None)
    annual = provider.fetch_series("320193/Revenues:FY", None, None, None)
    assert quarterly.data.tolist() == [10.0, 11.0]  # el 9M acumulado se descarta
    assert quarterly.frequency is Frequency.QUARTERLY
    assert annual.data.tolist() == [45.0]
    assert annual.frequency is Frequency.ANNUAL


@responses.activate
def test_as_of_uses_only_filed_data(provider: SecEdgarMacroProvider) -> None:
    responses.get(FACTS_URL, json=FACTS)
    series = provider.fetch_series("320193/Assets", None, None, as_of=date(2026, 2, 1))
    assert series.data.tolist() == [100.0]  # el dato original, sin la reexpresión posterior
    assert series.vintage == date(2026, 2, 1)


@responses.activate
def test_not_found_cases(provider: SecEdgarMacroProvider) -> None:
    responses.get(DEFAULT_TICKERS_URL, json=TICKERS)
    responses.get(FACTS_URL, json=FACTS)
    with pytest.raises(SeriesNotFoundError, match="ticker"):
        provider.fetch_series("NOPE/Assets", None, None, None)
    with pytest.raises(SeriesNotFoundError, match="no reportado"):
        provider.fetch_series("AAPL/us-gaap/Goodwill", None, None, None)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("AAPL/Assets", date(2030, 1, 1), None, None)


@responses.activate
def test_missing_or_rejected_user_agent() -> None:
    with pytest.raises(ConfigurationError, match="SEC_USER_AGENT"):
        SecEdgarMacroProvider(user_agent=" ").fetch_series("320193/Assets", None, None, None)
    responses.get(FACTS_URL, status=403)
    with pytest.raises(ConfigurationError):
        SecEdgarMacroProvider(user_agent=UA).fetch_series("320193/Assets", None, None, None)


@pytest.mark.parametrize("bad", ["AAPL", "AAPL/us-gaap/Assets/x", "AAPL/Assets:MONTHLY"])
def test_query_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(InvalidRequestError):
        ConceptQuery.parse(bad)


def test_select_facts_rejects_garbage() -> None:
    with pytest.raises(ProviderError):
        select_facts([{"end": "2024-01-01", "val": "abc"}], "Q", None, "X")
    with pytest.raises(SeriesNotFoundError):
        select_facts([], "Q", None, "X")
