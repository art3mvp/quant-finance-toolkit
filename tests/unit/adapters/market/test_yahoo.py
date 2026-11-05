"""Tests del adaptador de Yahoo con ``yfinance`` mockeado (sin red)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import date
from unittest import mock

import pandas as pd
import pytest
from yfinance.exceptions import YFPricesMissingError

from toolkit.adapters.outbound.market.yahoo import YahooPriceProvider, normalize_history
from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.ports.outbound import PriceProvider


def yahoo_frame() -> pd.DataFrame:
    """DataFrame con el formato de ``Ticker.history(auto_adjust=False)``: tz-aware,
    desordenado, con un duplicado y columnas extra."""
    index = pd.DatetimeIndex(
        ["2024-01-03", "2024-01-02", "2024-01-04", "2024-01-04"], name="Date"
    ).tz_localize("America/New_York")
    return pd.DataFrame(
        {
            "Open": [101.0, 100.0, 102.0, 102.0],
            "High": [102.0, 101.0, 103.0, 103.0],
            "Low": [100.0, 99.0, 101.0, 101.0],
            "Close": [101.5, 100.5, 102.5, 102.6],
            "Adj Close": [101.0, 100.0, 102.0, 102.1],
            "Volume": [1000, 2000, 3000, 3000],
            "Dividends": [0.0, 0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0, 0.0],
        },
        index=index,
    )


@pytest.fixture
def mock_ticker() -> mock.MagicMock:
    ticker = mock.MagicMock()
    ticker.history.return_value = yahoo_frame()
    ticker.get_history_metadata.return_value = {"currency": "USD", "longName": "Apple Inc."}
    return ticker


def test_satisfies_port() -> None:
    assert isinstance(YahooPriceProvider(), PriceProvider)


def test_happy_path(mock_ticker: mock.MagicMock) -> None:
    with mock.patch(
        "toolkit.adapters.outbound.market.yahoo.yf.Ticker", return_value=mock_ticker
    ) as cls:
        series = YahooPriceProvider().fetch_prices(
            "AAPL", date(2024, 1, 1), date(2024, 1, 4), Frequency.DAILY, AssetType.EQUITY
        )

    cls.assert_called_once_with("AAPL")
    kwargs = mock_ticker.history.call_args.kwargs
    assert kwargs["auto_adjust"] is False
    assert kwargs["interval"] == "1d"
    assert kwargs["start"] == date(2024, 1, 1)
    assert kwargs["end"] == date(2024, 1, 5)  # end inclusivo → exclusivo en yfinance

    assert isinstance(series, PriceSeries)
    assert series.source == "yahoo"
    assert series.currency == "USD"
    assert series.name == "Apple Inc."
    assert list(series.data.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    assert series.data.index.tz is None
    assert list(series.data.index) == list(
        pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    )
    assert series.data.loc["2024-01-04", "close"] == 102.6  # duplicado: se queda el último
    assert series.mean_return == pytest.approx(series.data["adj_close"].pct_change().mean())


def test_index_with_weekly_interval_and_full_history(mock_ticker: mock.MagicMock) -> None:
    provider = YahooPriceProvider(ticker_factory=lambda _: mock_ticker)
    series = provider.fetch_prices("^GSPC", None, None, Frequency.WEEKLY, AssetType.INDEX)
    kwargs = mock_ticker.history.call_args.kwargs
    assert kwargs["period"] == "max"
    assert kwargs["interval"] == "1wk"
    assert series.asset_type is AssetType.INDEX
    assert series.frequency is Frequency.WEEKLY


def test_empty_dataframe_raises_not_found(mock_ticker: mock.MagicMock) -> None:
    mock_ticker.history.return_value = pd.DataFrame()
    provider = YahooPriceProvider(ticker_factory=lambda _: mock_ticker)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_prices("NOPE", None, None, Frequency.DAILY, AssetType.EQUITY)


def test_yfinance_missing_ticker_error_is_translated(mock_ticker: mock.MagicMock) -> None:
    mock_ticker.history.side_effect = YFPricesMissingError("NOPE", "")
    provider = YahooPriceProvider(ticker_factory=lambda _: mock_ticker)
    with pytest.raises(SeriesNotFoundError) as excinfo:
        provider.fetch_prices("NOPE", None, None, Frequency.DAILY, AssetType.EQUITY)
    assert not isinstance(excinfo.value, YFPricesMissingError)


@pytest.mark.parametrize("error", [ConnectionError("red caída"), ValueError("json raro")])
def test_library_exception_becomes_provider_error(
    mock_ticker: mock.MagicMock, error: Exception
) -> None:
    mock_ticker.history.side_effect = error
    with (
        mock.patch("toolkit.adapters.outbound.market.yahoo.yf.Ticker", return_value=mock_ticker),
        pytest.raises(ProviderError) as excinfo,
    ):
        YahooPriceProvider().fetch_prices("AAPL", None, None, Frequency.DAILY, AssetType.EQUITY)
    assert type(excinfo.value) is ProviderError
    assert excinfo.value.__cause__ is error


def test_metadata_failure_does_not_break_download(mock_ticker: mock.MagicMock) -> None:
    mock_ticker.get_history_metadata.side_effect = RuntimeError("metadata caída")
    provider = YahooPriceProvider(ticker_factory=lambda _: mock_ticker)
    series = provider.fetch_prices("AAPL", None, None, Frequency.DAILY, AssetType.EQUITY)
    assert series.name is None
    assert series.currency is None
    assert series.n_obs == 3


def test_annual_frequency_not_supported() -> None:
    with pytest.raises(ProviderError, match="annual"):
        YahooPriceProvider(ticker_factory=mock.MagicMock()).fetch_prices(
            "AAPL", None, None, Frequency.ANNUAL, AssetType.EQUITY
        )


def test_normalize_history_handles_multiindex_columns() -> None:
    frame = yahoo_frame()
    frame.columns = pd.MultiIndex.from_product([frame.columns, ["AAPL"]])
    data = normalize_history(frame)
    assert "adj_close" in data.columns
    assert data.index.is_monotonic_increasing


class _MetadataMapping(Mapping[str, object]):
    """Imita ``yfinance.scrapers.history.HistoryMetadata`` (Mapping que no es dict)."""

    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def test_metadata_as_non_dict_mapping(mock_ticker: mock.MagicMock) -> None:
    mock_ticker.get_history_metadata.return_value = _MetadataMapping(
        {"currency": "EUR", "shortName": "IBEX 35"}
    )
    provider = YahooPriceProvider(ticker_factory=lambda _: mock_ticker)
    series = provider.fetch_prices("^IBEX", None, None, Frequency.DAILY, AssetType.INDEX)
    assert series.currency == "EUR"
    assert series.name == "IBEX 35"
