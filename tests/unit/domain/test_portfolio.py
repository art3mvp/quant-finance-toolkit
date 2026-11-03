"""Tests de simulación de Monte Carlo y Portfolio."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from toolkit.domain.errors import InvalidSeriesError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.domain.portfolio import Portfolio
from toolkit.domain.simulation import simulate_gbm


def make_series(ticker: str, seed: int, n: int = 100, start: str = "2024-01-01") -> PriceSeries:
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    price = 100 + rng.normal(0, 1, n).cumsum()
    cols = {c: price for c in ["open", "high", "low", "close", "volume"]}
    return PriceSeries(
        ticker, None, AssetType.EQUITY, "fake", "USD", Frequency.DAILY,
        pd.DataFrame(cols, index=idx),
    )


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio([make_series("A", 1), make_series("B", 2)], {"A": 0.6, "B": 0.4})


# --- simulate_gbm ---------------------------------------------------------------


def test_simulate_gbm_shape_and_start() -> None:
    paths = simulate_gbm(100.0, 0.001, 0.01, n_steps=20, n_simulations=50, seed=1)
    assert paths.shape == (21, 50)
    assert np.all(paths[0] == 100.0)


def test_simulate_gbm_is_reproducible_with_seed() -> None:
    a = simulate_gbm(100.0, 0.001, 0.01, 10, 20, seed=7)
    b = simulate_gbm(100.0, 0.001, 0.01, 10, 20, seed=7)
    assert np.array_equal(a, b)


def test_simulate_gbm_zero_volatility_is_deterministic() -> None:
    paths = simulate_gbm(100.0, 0.01, 0.0, 5, 3, seed=1)
    assert np.allclose(paths[-1], 100.0 * np.exp(0.01 * 5))


def test_simulate_gbm_prices_stay_positive() -> None:
    paths = simulate_gbm(100.0, -0.01, 0.05, 100, 200, seed=3)
    assert (paths > 0).all()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_steps": 0},
        {"n_steps": -5},
        {"n_steps": 2.5},
        {"n_simulations": 0},
        {"n_simulations": -1},
        {"sigma": -0.01},
        {"sigma": float("nan")},
        {"sigma": float("inf")},
        {"mu": float("nan")},
        {"mu": float("inf")},
        {"initial_value": 0.0},
        {"initial_value": -10.0},
        {"initial_value": float("nan")},
    ],
)
def test_simulate_gbm_rejects_invalid_parameters(kwargs: dict) -> None:
    params = {"initial_value": 100.0, "mu": 0.001, "sigma": 0.01, "n_steps": 10, "n_simulations": 10}
    params.update(kwargs)
    with pytest.raises(ValueError):
        simulate_gbm(**params)


# --- Portfolio ------------------------------------------------------------------


def test_portfolio_is_a_dataclass(portfolio: Portfolio) -> None:
    assert dataclasses.is_dataclass(portfolio)


def test_portfolio_rejects_weights_not_summing_to_one() -> None:
    with pytest.raises(InvalidSeriesError):
        Portfolio([make_series("A", 1), make_series("B", 2)], {"A": 0.6, "B": 0.6})


def test_portfolio_rejects_mismatched_tickers() -> None:
    with pytest.raises(InvalidSeriesError):
        Portfolio([make_series("A", 1)], {"B": 1.0})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_portfolio_rejects_non_finite_weights(bad: float) -> None:
    with pytest.raises(InvalidSeriesError):
        Portfolio([make_series("A", 1), make_series("B", 2)], {"A": bad, "B": 0.4})


def test_portfolio_rejects_negative_weights() -> None:
    with pytest.raises(InvalidSeriesError):
        Portfolio([make_series("A", 1), make_series("B", 2)], {"A": 1.5, "B": -0.5})


def test_portfolio_rejects_duplicate_tickers() -> None:
    with pytest.raises(InvalidSeriesError):
        Portfolio([make_series("A", 1), make_series("A", 2)], {"A": 1.0})


def test_portfolio_rejects_too_few_common_dates() -> None:
    a = make_series("A", 1, n=50, start="2024-01-01")
    b = make_series("B", 2, n=50, start="2030-01-01")
    with pytest.raises(InvalidSeriesError):
        Portfolio([a, b], {"A": 0.5, "B": 0.5})


def test_portfolio_volatility_is_positive(portfolio: Portfolio) -> None:
    assert portfolio.volatility > 0


# --- monte_carlo ----------------------------------------------------------------


def test_monte_carlo_shape(portfolio: Portfolio) -> None:
    result = portfolio.monte_carlo(n_steps=30, n_simulations=100, seed=1)
    assert result.paths.shape == (31, 100)
    assert result.initial_value == 100.0


def test_monte_carlo_uses_custom_parameters(portfolio: Portfolio) -> None:
    result = portfolio.monte_carlo(mu=0.002, sigma=0.01, seed=1)
    assert result.mu == 0.002
    assert result.sigma == 0.01


def test_monte_carlo_prob_loss_is_a_probability(portfolio: Portfolio) -> None:
    result = portfolio.monte_carlo(seed=1)
    assert 0.0 <= result.prob_loss <= 1.0


def test_monte_carlo_rejects_invalid_parameters(portfolio: Portfolio) -> None:
    with pytest.raises(ValueError):
        portfolio.monte_carlo(n_simulations=0)


def test_monte_carlo_asset_starts_at_last_price(portfolio: Portfolio) -> None:
    result = portfolio.monte_carlo_asset("A", n_steps=10, n_simulations=20, seed=1)
    last_price = float(portfolio.series_by_ticker["A"].prices.iloc[-1])
    assert result.initial_value == last_price
    assert np.allclose(result.paths[0], last_price)


def test_monte_carlo_asset_uses_aligned_sample(portfolio: Portfolio) -> None:
    result = portfolio.monte_carlo_asset("A", seed=1)
    assert result.mu == pytest.approx(float(portfolio.returns["A"].mean()))
    assert result.sigma == pytest.approx(float(portfolio.returns["A"].std(ddof=1)))
    assert np.isfinite(result.sigma)


def test_monte_carlo_asset_unknown_ticker(portfolio: Portfolio) -> None:
    with pytest.raises(InvalidSeriesError):
        portfolio.monte_carlo_asset("ZZZ")