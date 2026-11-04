"""Tests de la base SDMX-CSV compartida (HTTP mockeado, sin red)."""

from __future__ import annotations

import math
from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound._sdmx import SdmxMacroProvider, read_csv, split_series_id
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

BASE = "https://sdmx.example.org/data"
CSV = (
    "KEY,FREQ,TIME_PERIOD,OBS_VALUE,TITLE,UNIT\n"
    "EXR.M.X,M,2024-02,1.2,Tipo de cambio,USD\n"
    "EXR.M.X,M,2024-01,,Tipo de cambio,USD\n"
)


class DemoProvider(SdmxMacroProvider):
    name = "demo"
    DEFAULT_BASE_URL = BASE


@pytest.fixture
def provider() -> DemoProvider:
    return DemoProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(DemoProvider(), MacroProvider)


@responses.activate
def test_happy_path(provider: DemoProvider) -> None:
    responses.get(
        f"{BASE}/EXR/M.X",
        body=CSV,
        match=[
            matchers.query_param_matcher(
                {"format": "csv", "startPeriod": "2024-01-01", "endPeriod": "2024-02-29"}
            )
        ],
    )
    series = provider.fetch_series("EXR/M.X", date(2024, 1, 1), date(2024, 2, 29), None)
    assert (series.source, series.name, series.units) == ("demo", "Tipo de cambio", "USD")
    assert series.frequency is Frequency.MONTHLY
    assert series.data.index.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-02-01"]
    assert math.isnan(series.data.iloc[0])
    assert series.mean == pytest.approx(1.2)


@responses.activate
def test_multiple_series_are_rejected(provider: DemoProvider) -> None:
    body = "TIME_PERIOD,OBS_VALUE\n2024-01,1\n2024-01,2\n"
    responses.get(f"{BASE}/EXR/M.X+Y", body=body)
    with pytest.raises(ProviderError, match="varias series"):
        provider.fetch_series("EXR/M.X+Y", None, None, None)


@responses.activate
def test_404_is_not_found(provider: DemoProvider) -> None:
    responses.get(f"{BASE}/EXR/M.X", status=404, body="No results found.")
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("EXR/M.X", None, None, None)


def test_as_of_is_not_supported(provider: DemoProvider) -> None:
    with pytest.raises(InvalidRequestError, match="vintages"):
        provider.fetch_series("EXR/M.X", None, None, date(2020, 1, 1))


@pytest.mark.parametrize("bad", ["EXR", "/M.X", "EXR/", "A/B/C"])
def test_split_series_id_rejects_malformed(bad: str) -> None:
    with pytest.raises(InvalidRequestError):
        split_series_id(bad)


def test_read_csv_validation() -> None:
    with pytest.raises(SeriesNotFoundError):
        read_csv("  ", "demo", "X")
    with pytest.raises(SeriesNotFoundError):
        read_csv("TIME_PERIOD,OBS_VALUE\n", "demo", "X")
    with pytest.raises(ProviderError, match="OBS_VALUE"):
        read_csv("TIME_PERIOD,VALUE\n2024,1\n", "demo", "X")
