"""Tests del adaptador Alpha Vantage con HTTP mockeado (sin red)."""

from __future__ import annotations

from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.market.alpha_vantage import (
    DEFAULT_BASE_URL,
    AlphaVantagePriceProvider,
    parse_time_series,
)
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.ports.outbound import PriceProvider

KEY = "av-key"


def bar(close: str) -> dict[str, str]:
    return {"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": close, "5. volume": "10"}


DAILY = {
    "Meta Data": {"2. Symbol": "IBM", "5. Time Zone": "US/Eastern"},
    "Time Series (Daily)": {
        "2024-01-04": bar("12"),
        "2024-01-03": bar("11"),
        "2024-01-02": bar("10"),
    },
}


@pytest.fixture
def provider() -> AlphaVantagePriceProvider:
    return AlphaVantagePriceProvider(
        api_key=KEY, today=lambda: date(2024, 1, 5), sleep=lambda _: None
    )


def test_satisfies_port() -> None:
    assert isinstance(AlphaVantagePriceProvider(api_key=None), PriceProvider)


@responses.activate
def test_daily_happy_path_uses_compact_for_recent_start(
    provider: AlphaVantagePriceProvider,
) -> None:
    responses.get(
        DEFAULT_BASE_URL,
        json=DAILY,
        match=[
            matchers.query_param_matcher(
                {
                    "function": "TIME_SERIES_DAILY",
                    "symbol": "IBM",
                    "apikey": KEY,
                    "outputsize": "compact",
                }
            )
        ],
    )
    series = provider.fetch_prices("IBM", date(2024, 1, 3), None, Frequency.DAILY, AssetType.EQUITY)
    assert isinstance(series, PriceSeries)
    assert series.source == "alpha_vantage"
    assert series.data["close"].tolist() == [11.0, 12.0]
    assert series.mean_return == pytest.approx(12 / 11 - 1)


@responses.activate
def test_old_start_requests_full_history(provider: AlphaVantagePriceProvider) -> None:
    responses.get(DEFAULT_BASE_URL, json=DAILY)
    provider.fetch_prices("IBM", date(2000, 1, 1), None, Frequency.DAILY, AssetType.EQUITY)
    assert "outputsize=full" in responses.calls[0].request.url


@responses.activate
def test_weekly_uses_weekly_function(provider: AlphaVantagePriceProvider) -> None:
    responses.get(DEFAULT_BASE_URL, json={"Weekly Time Series": {"2024-01-05": bar("10")}})
    series = provider.fetch_prices("IBM", None, None, Frequency.WEEKLY, AssetType.EQUITY)
    assert "function=TIME_SERIES_WEEKLY" in responses.calls[0].request.url
    assert "outputsize" not in responses.calls[0].request.url
    assert series.frequency is Frequency.WEEKLY


def test_missing_key_and_unsupported_frequency(provider: AlphaVantagePriceProvider) -> None:
    with pytest.raises(ConfigurationError, match="ALPHA_VANTAGE_API_KEY"):
        AlphaVantagePriceProvider(api_key="").fetch_prices(
            "IBM", None, None, Frequency.DAILY, AssetType.EQUITY
        )
    with pytest.raises(ProviderError, match="quarterly"):
        provider.fetch_prices("IBM", None, None, Frequency.QUARTERLY, AssetType.EQUITY)


def test_body_errors_are_translated() -> None:
    with pytest.raises(SeriesNotFoundError):
        parse_time_series({"Error Message": "Invalid API call."}, "k", "NOPE")
    with pytest.raises(ProviderError, match="rate limit"):
        parse_time_series({"Information": "rate limit reached"}, "k", "IBM")
    with pytest.raises(ProviderError, match="respuesta sin"):
        parse_time_series({"Meta Data": {}}, "Time Series (Daily)", "IBM")


@responses.activate
def test_empty_range_raises_not_found(provider: AlphaVantagePriceProvider) -> None:
    responses.get(DEFAULT_BASE_URL, json=DAILY)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_prices(
            "IBM", date(2023, 1, 1), date(2023, 1, 31), Frequency.DAILY, AssetType.EQUITY
        )
