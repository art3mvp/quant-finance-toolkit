"""Tests de la limpieza y alineación de precios."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from toolkit.domain.cleaning import align_prices
from toolkit.domain.errors import InvalidRequestError, InvalidSeriesError


def daily(start: str, values: list[float]) -> pd.Series:
    """Serie con una observación por día natural (calendario 24/7)."""
    return pd.Series(values, index=pd.date_range(start, periods=len(values)), dtype=float)


def business(start: str, values: list[float]) -> pd.Series:
    """Serie con una observación por día hábil."""
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_inner_return_spans_the_same_interval_for_every_asset() -> None:
    """Regresión: el lunes, el retorno de la cripto debe ser viernes→lunes, como la acción.

    2024-01-05 es viernes. La cripto sube un 50 % el sábado y se mantiene: ese movimiento
    debe aparecer en el retorno del lunes, no perderse con el fin de semana.
    """
    crypto = daily("2024-01-05", [100, 150, 150, 150])  # vie, sáb, dom, lun
    equity = business("2024-01-05", [10, 11])  # vie, lun
    aligned = align_prices({"BTC": crypto, "AAPL": equity})

    monday = pd.Timestamp("2024-01-08")
    assert list(aligned.returns.index) == [monday]
    assert aligned.returns.loc[monday, "BTC"] == pytest.approx(0.5)
    assert aligned.returns.loc[monday, "AAPL"] == pytest.approx(0.1)


def test_inner_reports_dropped_dates() -> None:
    crypto = daily("2024-01-05", [100, 150, 150, 150])
    equity = business("2024-01-05", [10, 11])
    report = align_prices({"BTC": crypto, "AAPL": equity}).report

    assert report.n_union == 4
    assert report.n_kept == 2
    assert list(report.dropped_dates) == [pd.Timestamp("2024-01-06"), pd.Timestamp("2024-01-07")]
    assert report.missing_by_ticker == {"BTC": 0, "AAPL": 2}
    assert report.dropped_ratio == pytest.approx(0.5)


def test_holiday_mismatch_is_dropped_and_reported() -> None:
    us = business("2024-01-01", [1, 2, 3, 4, 5]).drop(pd.Timestamp("2024-01-03"))
    es = business("2024-01-01", [1, 2, 3, 4, 5])
    aligned = align_prices({"US": us, "ES": es})

    assert pd.Timestamp("2024-01-03") in aligned.report.dropped_dates
    # El retorno de ES del 04/01 abarca 02→04, el mismo intervalo que el de US.
    assert aligned.returns.loc["2024-01-04", "ES"] == pytest.approx(4 / 2 - 1)


def test_nan_prices_are_removed_and_counted() -> None:
    a = business("2024-01-01", [1, np.nan, 3, 4])
    b = business("2024-01-01", [1, 2, 3, 4])
    aligned = align_prices({"A": a, "B": b})

    assert aligned.report.nan_dropped_by_ticker == {"A": 1, "B": 0}
    assert pd.Timestamp("2024-01-02") not in aligned.prices.index
    assert not aligned.prices.isna().any().any()


def test_ffill_respects_limit() -> None:
    a = business("2024-01-01", [1, np.nan, np.nan, np.nan, 5])
    b = business("2024-01-01", [1, 2, 3, 4, 5])

    filled = align_prices({"A": a, "B": b}, method="ffill", ffill_limit=1)
    assert len(filled.prices) == 3  # 1, relleno del 02/01, 5
    assert filled.report.filled_by_ticker == {"A": 1, "B": 0}

    unlimited = align_prices({"A": a, "B": b}, method="ffill", ffill_limit=None)
    assert len(unlimited.prices) == 5


def test_ffill_keeps_more_dates_than_inner() -> None:
    crypto = daily("2024-01-05", [100, 150, 150, 150])
    equity = business("2024-01-05", [10, 11])
    inner = align_prices({"BTC": crypto, "AAPL": equity})
    ffill = align_prices({"BTC": crypto, "AAPL": equity}, method="ffill")
    assert ffill.report.n_kept > inner.report.n_kept
    assert ffill.report.method == "ffill" and ffill.report.ffill_limit == 5


def test_ffill_never_backfills_nor_extrapolates() -> None:
    early = business("2024-01-01", [1, 2, 3, 4, 5])
    late = business("2024-01-03", [10, 11])  # 03/01 y 04/01
    aligned = align_prices({"E": early, "L": late}, method="ffill")
    assert aligned.prices.index.min() == pd.Timestamp("2024-01-03")
    assert aligned.prices.index.max() == pd.Timestamp("2024-01-04")


def test_no_common_dates_gives_empty_frame() -> None:
    a = business("2024-01-01", [1, 2])
    b = business("2024-02-01", [1, 2])
    aligned = align_prices({"A": a, "B": b})
    assert aligned.prices.empty
    assert aligned.returns.empty


@pytest.mark.parametrize(
    "kwargs",
    [{"method": "outer"}, {"ffill_limit": 0}, {"ffill_limit": 1.5}, {"ffill_limit": True}],
)
def test_rejects_invalid_arguments(kwargs: dict) -> None:
    with pytest.raises(InvalidRequestError):
        align_prices({"A": business("2024-01-01", [1, 2])}, **kwargs)


def test_rejects_empty_input() -> None:
    with pytest.raises(InvalidRequestError):
        align_prices({})


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_rejects_non_positive_prices(bad: float) -> None:
    with pytest.raises(InvalidSeriesError):
        align_prices({"A": business("2024-01-01", [1, bad, 3])})


def test_rejects_non_datetime_index() -> None:
    with pytest.raises(InvalidSeriesError):
        align_prices({"A": pd.Series([1.0, 2.0])})
