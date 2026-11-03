"""Tests del adaptador CoinGecko con HTTP mockeado (sin red)."""

from __future__ import annotations

import math
from datetime import date

import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.specialized.coingecko import (
    CoinGeckoPriceProvider,
    parse_market_chart,
    resample,
)
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.ports.outbound import PriceProvider

URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
PRO_URL = "https://pro-api.coingecko.com/api/v3/coins/bitcoin/market_chart"
DAY = 86_400_000
T0 = 1_704_067_200_000  # 2024-01-01 00:00 UTC

PAYLOAD = {
    "prices": [[T0, 100.0], [T0 + DAY, 110.0], [T0 + 2 * DAY, 99.0], [T0 + 2 * DAY + 3600, 121.0]],
    "total_volumes": [[T0, 1.0], [T0 + DAY, 2.0], [T0 + 2 * DAY, 3.0], [T0 + 2 * DAY + 3600, 4.0]],
}


def make_provider(**kwargs: object) -> CoinGeckoPriceProvider:
    return CoinGeckoPriceProvider(today=lambda: date(2024, 1, 3), sleep=lambda _: None, **kwargs)


def test_satisfies_port() -> None:
    assert isinstance(CoinGeckoPriceProvider(), PriceProvider)


@responses.activate
def test_happy_path_builds_crypto_price_series() -> None:
    responses.get(
        URL,
        json=PAYLOAD,
        match=[
            matchers.query_param_matcher({"vs_currency": "usd", "days": "3", "interval": "daily"})
        ],
    )
    series = make_provider().fetch_prices(
        "Bitcoin", date(2024, 1, 1), None, Frequency.DAILY, AssetType.EQUITY
    )
    assert isinstance(series, PriceSeries)
    assert series.asset_type is AssetType.CRYPTO  # la fuente fija la clase de activo
    assert (series.ticker, series.source, series.currency) == ("bitcoin", "coingecko", "USD")
    # el punto "en vivo" del 03/01 sustituye al diario del mismo día
    assert series.data["close"].tolist() == [100.0, 110.0, 121.0]
    assert series.data["volume"].tolist() == [1.0, 2.0, 4.0]
    assert math.isnan(series.data["open"].iloc[0])
    assert "x-cg-demo-api-key" not in responses.calls[0].request.headers


@responses.activate
def test_filters_requested_range() -> None:
    responses.get(URL, json=PAYLOAD)
    series = make_provider().fetch_prices(
        "bitcoin", date(2024, 1, 2), date(2024, 1, 2), Frequency.DAILY, AssetType.CRYPTO
    )
    assert series.data.index.strftime("%Y-%m-%d").tolist() == ["2024-01-02"]


@responses.activate
def test_demo_and_pro_keys_use_their_header_and_host() -> None:
    responses.get(URL, json=PAYLOAD)
    responses.get(PRO_URL, json=PAYLOAD)
    make_provider(api_key="demo-key").fetch_prices(
        "bitcoin", None, None, Frequency.DAILY, AssetType.CRYPTO
    )
    make_provider(api_key="pro-key", plan="pro").fetch_prices(
        "bitcoin", None, None, Frequency.DAILY, AssetType.CRYPTO
    )
    assert responses.calls[0].request.headers["x-cg-demo-api-key"] == "demo-key"
    assert "days=365" in responses.calls[0].request.url
    assert responses.calls[1].request.headers["x-cg-pro-api-key"] == "pro-key"


@pytest.mark.parametrize(("plan", "key"), [("pro", None), ("enterprise", "k")])
def test_invalid_plan_configuration(plan: str, key: str | None) -> None:
    with pytest.raises(ConfigurationError):
        make_provider(plan=plan, api_key=key).fetch_prices(
            "bitcoin", None, None, Frequency.DAILY, AssetType.CRYPTO
        )


def test_demo_plan_rejects_history_beyond_365_days() -> None:
    with pytest.raises(ConfigurationError, match="365"):
        make_provider().fetch_prices(
            "bitcoin", date(2022, 1, 1), None, Frequency.DAILY, AssetType.CRYPTO
        )


@responses.activate
def test_unknown_coin_raises_not_found() -> None:
    responses.get(URL.replace("bitcoin", "nope"), status=404, json={"error": "coin not found"})
    with pytest.raises(SeriesNotFoundError):
        make_provider().fetch_prices("nope", None, None, Frequency.DAILY, AssetType.CRYPTO)


@responses.activate
def test_rejected_history_raises_configuration_error_without_leaking_key() -> None:
    responses.get(URL, status=401, json={"error": "exceeds the allowed time range"})
    with pytest.raises(ConfigurationError) as excinfo:
        make_provider(api_key="secret-key").fetch_prices(
            "bitcoin", date(2015, 1, 1), None, Frequency.DAILY, AssetType.CRYPTO
        )
    assert "secret-key" not in str(excinfo.value)


@responses.activate
def test_empty_range_raises_not_found() -> None:
    responses.get(URL, json=PAYLOAD)
    with pytest.raises(SeriesNotFoundError):
        make_provider().fetch_prices(
            "bitcoin", date(2023, 12, 1), date(2023, 12, 2), Frequency.DAILY, AssetType.CRYPTO
        )


def test_parse_market_chart_rejects_garbage() -> None:
    with pytest.raises(ProviderError):
        parse_market_chart({"status": "error"}, "x")
    with pytest.raises(SeriesNotFoundError):
        parse_market_chart({"prices": []}, "x")
    with pytest.raises(ProviderError):
        parse_market_chart({"prices": [[T0, "abc"]]}, "x")


def test_resample_weekly_uses_last_close_and_summed_volume() -> None:
    days = [[T0 + i * DAY, float(100 + i)] for i in range(10)]  # lun 01/01 → mié 10/01
    data = parse_market_chart({"prices": days, "total_volumes": [[t, 1.0] for t, _ in days]}, "x")
    weekly = resample(data, Frequency.WEEKLY)
    assert weekly.index.strftime("%Y-%m-%d").tolist() == ["2024-01-01", "2024-01-08"]
    assert weekly["close"].tolist() == [106.0, 109.0]
    assert weekly["volume"].tolist() == [7.0, 3.0]
