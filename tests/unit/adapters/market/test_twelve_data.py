"""Tests del adaptador Twelve Data con HTTP mockeado (sin red)."""

from __future__ import annotations

import math
from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.market.twelve_data import (
    DEFAULT_BASE_URL,
    TwelveDataPriceProvider,
    parse_time_series,
)
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.ports.outbound import PriceProvider

KEY = "td-key"
URL = f"{DEFAULT_BASE_URL}/time_series"


def bar(day: str, close: str, volume: str | None = "100") -> dict[str, str]:
    row = {"datetime": day, "open": "1", "high": "2", "low": "0.5", "close": close}
    if volume is not None:
        row["volume"] = volume
    return row


PAYLOAD = {
    "meta": {"symbol": "AAPL", "interval": "1day", "currency": "USD"},
    "values": [bar("2024-01-02", "10"), bar("2024-01-03", "11"), bar("2024-01-04", "12")],
    "status": "ok",
}


@pytest.fixture
def provider() -> TwelveDataPriceProvider:
    return TwelveDataPriceProvider(api_key=KEY, sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(TwelveDataPriceProvider(api_key=None), PriceProvider)


@responses.activate
def test_happy_path_sends_exclusive_end_date(provider: TwelveDataPriceProvider) -> None:
    responses.get(
        URL,
        json=PAYLOAD,
        match=[
            matchers.query_param_matcher(
                {
                    "symbol": "AAPL",
                    "interval": "1day",
                    "outputsize": "5000",
                    "order": "asc",
                    "apikey": KEY,
                    "start_date": "2024-01-02",
                    "end_date": "2024-01-04",  # end=03/01 + 1 día
                }
            )
        ],
    )
    series = provider.fetch_prices(
        "AAPL", date(2024, 1, 2), date(2024, 1, 3), Frequency.DAILY, AssetType.EQUITY
    )
    assert isinstance(series, PriceSeries)
    assert (series.source, series.currency) == ("twelve_data", "USD")
    assert series.data["close"].tolist() == [10.0, 11.0]  # el 04/01 se recorta en local


@responses.activate
def test_index_without_volume(provider: TwelveDataPriceProvider) -> None:
    responses.get(URL, json={"meta": {}, "values": [bar("2024-01-02", "5", volume=None)]})
    series = provider.fetch_prices("SPX", None, None, Frequency.MONTHLY, AssetType.INDEX)
    assert "interval=1month" in responses.calls[0].request.url
    assert math.isnan(series.data["volume"].iloc[0])
    assert series.currency is None


@pytest.mark.parametrize(
    ("code", "error"),
    [(401, ConfigurationError), (404, SeriesNotFoundError), (429, ProviderError)],
)
def test_body_errors_are_translated(code: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        parse_time_series({"status": "error", "code": code, "message": "x"}, "AAPL")


@responses.activate
def test_http_401_is_configuration_error(provider: TwelveDataPriceProvider) -> None:
    responses.get(URL, status=401, json={"status": "error", "code": 401, "message": "bad key"})
    with pytest.raises(ConfigurationError):
        provider.fetch_prices("AAPL", None, None, Frequency.DAILY, AssetType.EQUITY)


def test_missing_key_and_unsupported_frequency(provider: TwelveDataPriceProvider) -> None:
    with pytest.raises(ConfigurationError, match="TWELVE_DATA_API_KEY"):
        TwelveDataPriceProvider(api_key=None).fetch_prices(
            "AAPL", None, None, Frequency.DAILY, AssetType.EQUITY
        )
    with pytest.raises(ProviderError, match="annual"):
        provider.fetch_prices("AAPL", None, None, Frequency.ANNUAL, AssetType.EQUITY)


def test_malformed_payloads() -> None:
    with pytest.raises(ProviderError):
        parse_time_series({"meta": {}}, "AAPL")
    with pytest.raises(SeriesNotFoundError):
        parse_time_series({"values": []}, "AAPL")
    with pytest.raises(ProviderError):
        parse_time_series({"values": [{"close": "1"}]}, "AAPL")
