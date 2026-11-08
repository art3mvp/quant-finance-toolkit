"""Tests de las métricas de riesgo y retorno."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from toolkit.domain import metrics
from toolkit.domain.errors import InvalidRequestError
from toolkit.domain.models import AssetType, Frequency


def series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)


@pytest.mark.parametrize(
    ("frequency", "types", "expected"),
    [
        (Frequency.DAILY, [AssetType.EQUITY], 252),
        (Frequency.DAILY, [AssetType.CRYPTO], 365),
        (Frequency.DAILY, [AssetType.CRYPTO, AssetType.EQUITY], 252),
        (Frequency.WEEKLY, [AssetType.CRYPTO], 52),
        (Frequency.MONTHLY, [], 12),
        (Frequency.QUARTERLY, [], 4),
        (Frequency.ANNUAL, [], 1),
    ],
)
def test_periods_per_year(frequency: Frequency, types: list, expected: int) -> None:
    assert metrics.periods_per_year(frequency, types) == expected


def test_annualized_return_is_geometric() -> None:
    r = series([0.01] * 12)
    assert metrics.annualized_return(r, 12) == pytest.approx(1.01**12 - 1)
    # Medio año al 1 % mensual → anualizado igual que un año completo.
    assert metrics.annualized_return(series([0.01] * 6), 12) == pytest.approx(1.01**12 - 1)


def test_annualized_return_total_loss() -> None:
    assert metrics.annualized_return(series([0.1, -1.0]), 12) == -1.0


def test_annualized_volatility() -> None:
    r = series([0.01, -0.01, 0.02, -0.02])
    assert metrics.annualized_volatility(r, 252) == pytest.approx(r.std(ddof=1) * math.sqrt(252))
    assert metrics.annualized_volatility(series([0.01] * 5), 252) == 0.0


def test_sharpe_ratio_with_and_without_risk_free() -> None:
    r = series([0.01, -0.005, 0.02, 0.0, 0.004])
    base = r.mean() / r.std(ddof=1) * math.sqrt(252)
    assert metrics.sharpe_ratio(r, 252) == pytest.approx(base)
    rf_p = 1.03 ** (1 / 252) - 1
    expected = (r.mean() - rf_p) / r.std(ddof=1) * math.sqrt(252)
    assert metrics.sharpe_ratio(r, 252, risk_free=0.03) == pytest.approx(expected)


def test_sharpe_ratio_zero_volatility_is_nan() -> None:
    assert math.isnan(metrics.sharpe_ratio(series([0.01] * 5), 252))


def test_wealth_index_and_drawdown() -> None:
    r = series([0.1, -0.5, 0.2])
    wealth = metrics.wealth_index(r)
    assert list(wealth.round(6)) == [110.0, 55.0, 66.0]
    dd = metrics.drawdown(r)
    assert list(dd.round(6)) == [0.0, -0.5, -0.4]
    assert metrics.max_drawdown(r) == pytest.approx(-0.5)


def test_drawdown_counts_initial_capital_as_peak() -> None:
    assert metrics.max_drawdown(series([-0.1, 0.05])) == pytest.approx(-0.1)


def test_var_and_cvar() -> None:
    r = series(list(np.linspace(-0.10, 0.09, 20)))
    var = metrics.historical_var(r, 0.95)
    cvar = metrics.historical_cvar(r, 0.95)
    assert var == pytest.approx(-r.quantile(0.05))
    assert cvar >= var
    assert cvar == pytest.approx(0.10)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.5, float("nan")])
def test_invalid_confidence(bad: float) -> None:
    with pytest.raises(InvalidRequestError):
        metrics.historical_var(series([0.01, 0.02]), bad)


@pytest.mark.parametrize("bad", [0, -1, 2.5, True])
def test_invalid_periods_per_year(bad) -> None:
    with pytest.raises(InvalidRequestError):
        metrics.annualized_volatility(series([0.01, 0.02]), bad)


def test_invalid_risk_free() -> None:
    with pytest.raises(InvalidRequestError):
        metrics.sharpe_ratio(series([0.01, 0.02]), 252, risk_free=float("inf"))
