"""Tests del helper de periodos y frecuencias."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from toolkit.adapters.outbound._periods import (
    frequency_from_code,
    infer_frequency,
    parse_period,
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
