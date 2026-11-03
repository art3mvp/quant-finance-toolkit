"""Tests del adaptador del Banco Mundial con respuestas reales recortadas (sin red)."""

from __future__ import annotations

import math
from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.macro.world_bank import DEFAULT_BASE_URL, WorldBankMacroProvider
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

URL = f"{DEFAULT_BASE_URL}/country/ESP/indicator/NY.GDP.MKTP.CD"


def row(year: str, value: float | None) -> dict[str, object]:
    return {
        "indicator": {"id": "NY.GDP.MKTP.CD", "value": "GDP (current US$)"},
        "countryiso3code": "ESP",
        "date": year,
        "value": value,
        "unit": "",
    }


def meta(pages: int = 1) -> dict[str, object]:
    return {"page": 1, "pages": pages, "per_page": 20000, "lastupdated": "2026-10-08"}


@pytest.fixture
def provider() -> WorldBankMacroProvider:
    return WorldBankMacroProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(WorldBankMacroProvider(), MacroProvider)


@responses.activate
def test_happy_path_filters_by_year_and_clips(provider: WorldBankMacroProvider) -> None:
    responses.get(
        URL,
        json=[meta(), [row("2021", 3.0), row("2020", None), row("2019", 1.0)]],
        match=[
            matchers.query_param_matcher(
                {"format": "json", "per_page": "20000", "page": "1", "date": "2019:2021"}
            )
        ],
    )
    series = provider.fetch_series("ESP/NY.GDP.MKTP.CD", date(2019, 6, 1), date(2021, 12, 31), None)
    assert (series.source, series.name, series.units) == ("world_bank", "GDP (current US$)", None)
    assert series.frequency is Frequency.ANNUAL
    # 2019-01-01 < start: se recorta en local
    assert series.data.index.strftime("%Y").tolist() == ["2020", "2021"]
    assert math.isnan(series.data.iloc[0])


@responses.activate
def test_paginates(provider: WorldBankMacroProvider) -> None:
    responses.get(URL, json=[meta(pages=2), [row("2021", 2.0)]])
    responses.get(URL, json=[meta(pages=2), [row("2020", 1.0)]])
    series = provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, None)
    assert "page=2" in responses.calls[1].request.url
    assert series.data.tolist() == [1.0, 2.0]


@responses.activate
def test_monthly_periods(provider: WorldBankMacroProvider) -> None:
    responses.get(URL, json=[meta(), [row("2020M02", 2.0), row("2020M01", 1.0)]])
    series = provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, None)
    assert series.frequency is Frequency.MONTHLY
    assert series.start == date(2020, 1, 1)


@responses.activate
def test_body_errors(provider: WorldBankMacroProvider) -> None:
    error = [{"message": [{"id": "120", "key": "Invalid value", "value": "not valid"}]}]
    responses.get(URL, json=error)
    responses.get(URL, json=[meta(), None])
    responses.get(URL, json={"unexpected": True})
    with pytest.raises(SeriesNotFoundError, match="not valid"):
        provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, None)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, None)
    with pytest.raises(ProviderError):
        provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, None)


def test_bad_ids_and_as_of(provider: WorldBankMacroProvider) -> None:
    with pytest.raises(InvalidRequestError):
        provider.fetch_series("NY.GDP.MKTP.CD", None, None, None)
    with pytest.raises(ProviderError, match="vintages"):
        provider.fetch_series("ESP/NY.GDP.MKTP.CD", None, None, date(2020, 1, 1))
