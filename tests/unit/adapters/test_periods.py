"""Tests del helper de periodos y frecuencias."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from toolkit.adapters.outbound._periods import (
    clip,
    frequency_from_code,
    infer_frequency,
    parse_period,
    to_period_start,
    to_series,
)
from toolkit.domain.models import Frequency


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2024-01-02", "2024-01-02"),
        ("2024-10-01T08:15:00Z", "2024-10-01"),
        ("2024-03", "2024-03-01"),
        ("2024M03", "2024-03-01"),
        ("2024-Q3", "2024-07-01"),
        ("2024Q1", "2024-01-01"),
        ("2024-S2", "2024-07-01"),
        ("2024-W02", "2024-01-08"),
        ("2024", "2024-01-01"),
    ],
)
def test_parse_period(text: str, expected: str) -> None:
    assert parse_period(text) == pd.Timestamp(expected)


def test_parse_period_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_period("ayer")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("D", Frequency.DAILY),
        ("M", Frequency.MONTHLY),
        ("T", Frequency.QUARTERLY),
        ("a", Frequency.ANNUAL),
    ],
)
def test_frequency_from_code(code: str, expected: Frequency) -> None:
    assert frequency_from_code(code, pd.DatetimeIndex([]), "X") is expected


def test_frequency_is_inferred_when_unknown() -> None:
    index = pd.date_range("2020-01-01", periods=6, freq="MS")
    assert frequency_from_code(None, index, "X") is Frequency.MONTHLY
    assert infer_frequency(pd.DatetimeIndex(["2020-01-01"])) is Frequency.DAILY


def test_to_series_sorts_dedups_and_keeps_gaps() -> None:
    series = to_series(["2024-02", "2024-01", "2024-02"], [2, None, "3"], "X")
    assert series.index.strftime("%Y-%m").tolist() == ["2024-01", "2024-02"]
    assert math.isnan(series.iloc[0])
    assert series.iloc[1] == 3.0
    with pytest.raises(ValueError):
        to_series(["2024"], ["abc"], "X")


def test_clip_is_inclusive_for_series_and_frames() -> None:
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    series = pd.Series([1.0, 2.0, 3.0], index=index)
    assert clip(series, date(2024, 1, 2), date(2024, 1, 2)).tolist() == [2.0]
    assert len(clip(series.to_frame("close"), None, None)) == 3


@pytest.mark.parametrize(
    ("dates", "frequency", "expected"),
    [
        (["2024-01-05", "2024-01-12"], Frequency.WEEKLY, ["2024-01-01", "2024-01-08"]),
        (["2024-01-31", "2024-02-29"], Frequency.MONTHLY, ["2024-01-01", "2024-02-01"]),
        (["2024-03-29"], Frequency.QUARTERLY, ["2024-01-01"]),
        (["2024-01-02", "2024-01-03"], Frequency.DAILY, ["2024-01-02", "2024-01-03"]),
    ],
)
def test_to_period_start(dates: list[str], frequency: Frequency, expected: list[str]) -> None:
    series = pd.Series(1.0, index=pd.DatetimeIndex(dates, name="date"))
    result = to_period_start(series, frequency)
    assert result.index.strftime("%Y-%m-%d").tolist() == expected
    assert to_period_start(result, frequency).index.equals(result.index)  # idempotente
