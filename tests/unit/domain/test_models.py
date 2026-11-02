"""Tests del dominio: PriceSeries, MacroSeries y DownloadResult."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from toolkit.domain.errors import InvalidSeriesError, ToolkitError
from toolkit.domain.models import (
    AssetType,
    DownloadResult,
    Frequency,
    MacroSeries,
    PriceSeries,
)
from toolkit.domain.portfolio import Portfolio


def make_ohlcv(closes: list[float], start: str = "2024-01-01", adj: bool = True) -> pd.DataFrame:
    """Construye un DataFrame OHLCV válido a partir de una lista de cierres."""
    index = pd.date_range(start, periods=len(closes), freq="D")
    close = np.array(closes, dtype=float)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(len(closes), 1000.0),
        },
        index=index,
    )
    if adj:
        df["adj_close"] = close / 2  # mismo retorno relativo, distinto nivel
    return df


def make_price_series(data: pd.DataFrame, ticker: str = "TEST") -> PriceSeries:
    return PriceSeries(
        ticker=ticker,
        name="Test Inc.",
        asset_type=AssetType.EQUITY,
        source="unit",
        currency="USD",
        frequency=Frequency.DAILY,
        data=data,
    )


class TestPriceSeries:
    def test_computes_stats_on_post_init(self) -> None:
        series = make_price_series(make_ohlcv([100, 110, 99]))
        expected = pd.Series([0.10, -0.10])
        assert series.mean_return == pytest.approx(expected.mean())
        assert series.std_return == pytest.approx(expected.std(ddof=1))

    def test_uses_adj_close_when_available(self) -> None:
        df = make_ohlcv([100, 110, 121])
        df["adj_close"] = [10.0, 10.0, 10.0]  # retornos nulos en adj_close
        series = make_price_series(df)
        assert series.price_column == "adj_close"
        assert series.mean_return == pytest.approx(0.0)

    def test_falls_back_to_close_without_adj_close(self) -> None:
        series = make_price_series(make_ohlcv([100, 110, 121], adj=False))
        assert series.price_column == "close"
        assert series.mean_return == pytest.approx(0.10)

    def test_returns_and_log_returns(self) -> None:
        series = make_price_series(make_ohlcv([100, 110, 121]))
        assert series.returns.tolist() == pytest.approx([0.10, 0.10])
        assert series.log_returns.tolist() == pytest.approx([math.log(1.1)] * 2)

    def test_metadata_properties(self) -> None:
        series = make_price_series(make_ohlcv([1, 2, 3, 4], start="2024-03-01"))
        assert series.start == date(2024, 3, 1)
        assert series.end == date(2024, 3, 4)
        assert series.n_obs == 4

    def test_single_observation_gives_nan_stats(self) -> None:
        series = make_price_series(make_ohlcv([100]))
        assert math.isnan(series.mean_return)
        assert math.isnan(series.std_return)

    def test_is_frozen(self) -> None:
        series = make_price_series(make_ohlcv([1, 2]))
        with pytest.raises(AttributeError):
            series.ticker = "OTHER"  # type: ignore[misc]

    def test_rejects_unsorted_index(self) -> None:
        df = make_ohlcv([1, 2, 3]).iloc[[2, 0, 1]]
        with pytest.raises(InvalidSeriesError, match="ordenado"):
            make_price_series(df)

    def test_rejects_duplicated_index(self) -> None:
        df = make_ohlcv([1, 2, 3])
        df.index = pd.DatetimeIndex(["2024-01-01", "2024-01-01", "2024-01-02"])
        with pytest.raises(InvalidSeriesError, match="duplicadas"):
            make_price_series(df)

    def test_rejects_missing_columns(self) -> None:
        df = make_ohlcv([1, 2, 3]).drop(columns=["volume"])
        with pytest.raises(InvalidSeriesError, match="faltan columnas"):
            make_price_series(df)

    def test_rejects_unknown_columns(self) -> None:
        df = make_ohlcv([1, 2, 3])
        df["Dividends"] = 0.0
        with pytest.raises(InvalidSeriesError, match="no estándar"):
            make_price_series(df)

    def test_rejects_tz_aware_index(self) -> None:
        df = make_ohlcv([1, 2, 3])
        df.index = df.index.tz_localize("UTC")
        with pytest.raises(InvalidSeriesError, match="tz-naive"):
            make_price_series(df)

    def test_rejects_non_datetime_index(self) -> None:
        df = make_ohlcv([1, 2, 3]).reset_index(drop=True)
        with pytest.raises(InvalidSeriesError, match="DatetimeIndex"):
            make_price_series(df)

    def test_rejects_empty_data(self) -> None:
        with pytest.raises(InvalidSeriesError, match="observaciones"):
            make_price_series(make_ohlcv([1]).iloc[0:0])

    def test_invalid_series_error_is_toolkit_error(self) -> None:
        assert issubclass(InvalidSeriesError, ToolkitError)


class TestMacroSeries:
    def make(self, values: list[float], **kwargs: object) -> MacroSeries:
        index = pd.date_range("2020-01-01", periods=len(values), freq="MS")
        return MacroSeries(
            series_id="CPI",
            name="CPI",
            source="unit",
            units="Index",
            frequency=Frequency.MONTHLY,
            data=pd.Series(values, index=index, dtype=float),
            **kwargs,  # type: ignore[arg-type]
        )

    def test_computes_stats_ignoring_nan(self) -> None:
        series = self.make([1.0, math.nan, 3.0])
        assert series.mean == pytest.approx(2.0)
        assert series.std == pytest.approx(pd.Series([1.0, 3.0]).std())
        assert series.n_obs == 3

    def test_keeps_vintage(self) -> None:
        series = self.make([1.0, 2.0], vintage=date(2015, 6, 30))
        assert series.vintage == date(2015, 6, 30)

    def test_rejects_non_float_values(self) -> None:
        index = pd.date_range("2020-01-01", periods=2, freq="MS")
        with pytest.raises(InvalidSeriesError, match="float"):
            MacroSeries(
                "X", None, "unit", None, Frequency.MONTHLY, pd.Series(["a", "b"], index=index)
            )

    def test_rejects_unsorted_index(self) -> None:
        index = pd.DatetimeIndex(["2020-02-01", "2020-01-01"])
        with pytest.raises(InvalidSeriesError, match="ordenado"):
            MacroSeries(
                "X", None, "unit", None, Frequency.MONTHLY, pd.Series([1.0, 2.0], index=index)
            )


class TestDownloadResult:
    def test_counts_and_ok(self) -> None:
        result: DownloadResult[int] = DownloadResult(series={"A": 1, "B": 2}, errors={"C": "boom"})
        assert result.n_success == 2
        assert result.n_failed == 1
        assert not result.ok
        assert not result.all_failed

    def test_empty_is_ok(self) -> None:
        result: DownloadResult[int] = DownloadResult()
        assert result.ok
        assert result.n_success == 0

    def test_all_failed(self) -> None:
        result: DownloadResult[int] = DownloadResult(errors={"A": "x"})
        assert result.all_failed


def test_portfolio_is_a_stub() -> None:
    with pytest.raises(NotImplementedError):
        Portfolio(series=[], weights={})
