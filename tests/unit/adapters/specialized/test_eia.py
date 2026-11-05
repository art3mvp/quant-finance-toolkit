"""Tests del adaptador EIA con HTTP mockeado (sin red)."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.specialized import eia
from toolkit.adapters.outbound.specialized.eia import EiaMacroProvider, parse_period, parse_rows
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency, MacroSeries
from toolkit.ports.outbound import MacroProvider

KEY = "eia-test-key"
URL = f"{eia.DEFAULT_BASE_URL}/seriesid/PET.RWTC.D"


def row(period: str, value: float | None) -> dict[str, object]:
    return {
        "period": period,
        "value": value,
        "units": "$/BBL",
        "series-description": "Cushing, OK WTI Spot Price FOB (Dollars per Barrel)",
    }


def page(rows: list[dict[str, object]], total: int, frequency: str = "daily") -> dict:
    return {"response": {"total": total, "frequency": frequency, "data": rows}}


@pytest.fixture
def provider() -> EiaMacroProvider:
    return EiaMacroProvider(api_key=KEY, sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(EiaMacroProvider(api_key=None), MacroProvider)


@responses.activate
def test_happy_path_filters_range_locally(provider: EiaMacroProvider) -> None:
    rows = [row("2024-01-04", 73.0), row("2024-01-03", None), row("2024-01-02", 70.0)]
    responses.get(
        URL,
        json=page(rows, total=3),
        match=[matchers.query_param_matcher({"api_key": KEY, "offset": "0", "length": "5000"})],
    )
    series = provider.fetch_series("PET.RWTC.D", date(2024, 1, 3), date(2024, 1, 4), None)
    assert isinstance(series, MacroSeries)
    assert (series.source, series.units, series.frequency) == ("eia", "$/BBL", Frequency.DAILY)
    assert series.name.startswith("Cushing")
    assert series.data.index.strftime("%Y-%m-%d").tolist() == ["2024-01-03", "2024-01-04"]
    assert math.isnan(series.data.iloc[0])
    assert series.mean == pytest.approx(73.0)


@responses.activate
def test_lowercase_ids_hit_the_uppercase_route(provider: EiaMacroProvider) -> None:
    responses.get(URL, json=page([row("2024-01-02", 70.0)], total=1))
    assert provider.fetch_series("pet.rwtc.d", None, None, None).n_obs == 1


@responses.activate
def test_paginates_until_start_is_covered(
    provider: EiaMacroProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(eia, "PAGE_SIZE", 2)
    responses.get(URL, json=page([row("2024-01-05", 5.0), row("2024-01-04", 4.0)], total=6))
    responses.get(URL, json=page([row("2024-01-03", 3.0), row("2024-01-02", 2.0)], total=6))
    series = provider.fetch_series("PET.RWTC.D", date(2024, 1, 3), None, None)
    assert len(responses.calls) == 2  # la 3.ª página ya no hace falta
    assert "offset=2" in responses.calls[1].request.url
    assert series.data.tolist() == [3.0, 4.0, 5.0]


@responses.activate
def test_monthly_series_uses_response_frequency(provider: EiaMacroProvider) -> None:
    url = URL.replace(".D", ".M")
    responses.get(url, json=page([row("2024-02", 2.0), row("2024-01", 1.0)], 2, "monthly"))
    series = provider.fetch_series("PET.RWTC.M", None, None, None)
    assert series.frequency is Frequency.MONTHLY
    assert series.start == date(2024, 1, 1)


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="EIA_API_KEY"):
        EiaMacroProvider(api_key=" ").fetch_series("PET.RWTC.D", None, None, None)


def test_as_of_is_not_supported(provider: EiaMacroProvider) -> None:
    with pytest.raises(ProviderError, match="vintages"):
        provider.fetch_series("PET.RWTC.D", None, None, date(2020, 1, 1))


@responses.activate
def test_unknown_series_raises_not_found(provider: EiaMacroProvider) -> None:
    responses.get(URL, status=404, json={"error": "Series ID is not valid.", "code": 404})
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("PET.RWTC.D", None, None, None)


@responses.activate
def test_rejected_key_does_not_leak(provider: EiaMacroProvider) -> None:
    responses.get(URL, status=403, json={"error": f"API_KEY_INVALID {KEY}"})
    with pytest.raises(ConfigurationError) as excinfo:
        provider.fetch_series("PET.RWTC.D", None, None, None)
    assert KEY not in str(excinfo.value)


@responses.activate
def test_empty_or_malformed_responses(provider: EiaMacroProvider) -> None:
    responses.get(URL, json=page([], total=0))
    responses.get(URL, json={"unexpected": True})
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("PET.RWTC.D", None, None, None)
    with pytest.raises(ProviderError):
        provider.fetch_series("PET.RWTC.D", None, None, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-02", "2024-01-02"),
        ("2024-03", "2024-03-01"),
        ("2024-Q2", "2024-04-01"),
        ("2024", "2024-01-01"),
    ],
)
def test_parse_period(text: str, expected: str) -> None:
    assert parse_period(text) == pd.Timestamp(expected)


def test_parse_rows_rejects_garbage() -> None:
    with pytest.raises(ProviderError):
        parse_rows([{"period": "yesterday", "value": 1}], "X")
    with pytest.raises(ProviderError):
        parse_rows([{"period": "2024-01-01", "value": "abc"}], "X")
