"""Tests de los proveedores fake."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.ports.outbound import MacroProvider, PriceProvider

START, END = date(2023, 1, 1), date(2023, 12, 31)


def test_fakes_satisfy_ports() -> None:
    assert isinstance(FakePriceProvider(), PriceProvider)
    assert isinstance(FakeMacroProvider(), MacroProvider)


def test_price_series_is_deterministic_and_valid() -> None:
    provider = FakePriceProvider()
    a = provider.fetch_prices("AAPL", START, END, Frequency.DAILY, AssetType.EQUITY)
    b = provider.fetch_prices("AAPL", START, END, Frequency.DAILY, AssetType.EQUITY)
    c = provider.fetch_prices("MSFT", START, END, Frequency.DAILY, AssetType.EQUITY)
    pd.testing.assert_frame_equal(a.data, b.data)
    assert not a.data["close"].equals(c.data["close"])
    assert a.source == "fake"
    assert a.start >= START and a.end <= END
    assert (a.data["high"] >= a.data["low"]).all()


@pytest.mark.parametrize("interval", list(Frequency))
def test_supports_all_frequencies(interval: Frequency) -> None:
    series = FakePriceProvider().fetch_prices(
        "^GSPC", date(2015, 1, 1), END, interval, AssetType.INDEX
    )
    assert series.frequency is interval
    assert series.asset_type is AssetType.INDEX
    assert series.n_obs > 1


def test_forced_failures() -> None:
    provider = FakePriceProvider(not_found={"nope"}, fail_on={"BOOM"})
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_prices("NOPE", START, END, Frequency.DAILY, AssetType.EQUITY)
    with pytest.raises(ProviderError):
        provider.fetch_prices("boom", START, END, Frequency.DAILY, AssetType.EQUITY)
    assert len(provider.calls) == 2


def test_fixture_is_returned() -> None:
    fixture = FakePriceProvider().fetch_prices("X", START, END, Frequency.DAILY, AssetType.EQUITY)
    provider = FakePriceProvider(fixtures={"MY": fixture})
    assert provider.fetch_prices("MY", None, None, Frequency.DAILY, AssetType.EQUITY) is fixture


def test_default_range_when_dates_missing() -> None:
    series = FakePriceProvider().fetch_prices("AAPL", None, None, Frequency.DAILY, AssetType.EQUITY)
    assert isinstance(series, PriceSeries)
    assert series.end <= date(2024, 12, 31)


def test_macro_fake_alfred_mode_truncates_and_sets_vintage() -> None:
    provider = FakeMacroProvider()
    full = provider.fetch_series("CPI", date(2010, 1, 1), date(2020, 1, 1), None)
    vintage = provider.fetch_series("CPI", date(2010, 1, 1), date(2020, 1, 1), date(2015, 6, 30))
    assert full.vintage is None
    assert vintage.vintage == date(2015, 6, 30)
    assert vintage.end <= date(2015, 6, 30) < full.end


def test_macro_fake_failures() -> None:
    provider = FakeMacroProvider(not_found={"X"}, fail_on={"Y"})
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("X", None, None, None)
    with pytest.raises(ProviderError):
        provider.fetch_series("Y", None, None, None)
