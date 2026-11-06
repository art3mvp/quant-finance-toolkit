"""Comprobaciones del contrato común que toda fuente debe cumplir."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from toolkit.domain.models import Frequency, MacroSeries, PriceSeries


def assert_series_contract(
    series: PriceSeries | MacroSeries,
    *,
    source: str,
    frequency: Frequency,
    start: date | None = None,
    end: date | None = None,
    period_start: bool = True,
) -> None:
    """Índice limpio, rango pedido, convención de fechas y estadísticos calculados.

    Args:
        period_start: Si las fechas de frecuencia no diaria deben ser inicio de periodo
            (todas las fuentes salvo los fundamentales de SEC EDGAR).
    """
    index = series.data.index
    assert isinstance(index, pd.DatetimeIndex)
    assert index.tz is None
    assert index.is_monotonic_increasing and index.is_unique
    assert series.n_obs > 0
    assert series.source == source
    assert series.frequency is frequency
    if start is not None:
        assert series.start >= start
    if end is not None:
        assert series.end <= end
    if period_start and frequency is not Frequency.DAILY:
        expected = {
            Frequency.WEEKLY: index.to_period("W-SUN").start_time,
            Frequency.MONTHLY: index.to_period("M").start_time,
            Frequency.QUARTERLY: index.to_period("Q").start_time,
            Frequency.ANNUAL: index.to_period("Y").start_time,
        }[frequency]
        assert list(index) == list(expected), "las fechas deben ser inicio de periodo"
    stats = (
        (series.mean_return, series.std_return)
        if isinstance(series, PriceSeries)
        else (series.mean, series.std)
    )
    assert all(math.isfinite(v) for v in stats)
