"""Tests del helper de normalización OHLCV."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from toolkit.adapters.outbound._prices import clip, normalize_ohlcv
from toolkit.domain.errors import ProviderError, SeriesNotFoundError


def raw(index: list[str], **columns: list[object]) -> pd.DataFrame:
    return pd.DataFrame(columns, index=index)


def test_normalizes_types_order_and_duplicates() -> None:
    frame = raw(
        ["2024-01-03", "2024-01-02", "2024-01-03"],
        open=["1", "2", "3"],
        high=["1", "2", "3"],
        low=["1", "2", "3"],
        close=["10", "20", "30"],
        volume=["5", "6", "7"],
    )
    data = normalize_ohlcv(frame, "src", "X")
    assert data.index.strftime("%Y-%m-%d").tolist() == ["2024-01-02", "2024-01-03"]
    assert data["close"].tolist() == [20.0, 30.0]  # duplicado: gana el último
    assert list(data.columns) == ["open", "high", "low", "close", "volume"]
    assert data.index.name == "date"


def test_missing_volume_becomes_nan_and_tz_is_dropped() -> None:
    frame = raw(["2024-01-02T09:30:00+01:00"], open=[1], high=[1], low=[1], close=[1])
    data = normalize_ohlcv(frame, "src", "X")
    assert math.isnan(data["volume"].iloc[0])
    assert data.index.tz is None
    assert data.index[0] == pd.Timestamp("2024-01-02")


def test_rejects_garbage_and_empty() -> None:
    with pytest.raises(ProviderError):
        normalize_ohlcv(raw(["2024-01-02"], close=["abc"]), "src", "X")
    with pytest.raises(SeriesNotFoundError):
        normalize_ohlcv(raw(["2024-01-02"], close=[None]), "src", "X")


def test_clip_is_inclusive() -> None:
    data = normalize_ohlcv(
        raw(["2024-01-01", "2024-01-02", "2024-01-03"], close=[1, 2, 3]), "s", "X"
    )
    assert clip(data, date(2024, 1, 2), date(2024, 1, 2))["close"].tolist() == [2.0]
    assert len(clip(data, None, None)) == 3
