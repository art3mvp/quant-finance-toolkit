"""Tests de simulación de Monte Carlo y Portfolio."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from toolkit.domain.errors import InvalidRequestError, InvalidSeriesError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.domain.portfolio import Portfolio
from toolkit.domain.simulation import simulate_gbm


def make_series(
    ticker: str, seed: int, n: int = 100, start: str = "2024-01-01", currency: str | None = "USD"
) -> PriceSeries:
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    price = 100 + rng.normal(0, 1, n).cumsum()
    cols = {c: price for c in ["open", "high", "low", "close", "volume"]}
    return PriceSeries(
        ticker,
        None,
        AssetType.EQUITY,
        "fake",
        currency,
        Frequency.DAILY,
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
    params = {
        "initial_value": 100.0,
        "mu": 0.001,
        "sigma": 0.01,
        "n_steps": 10,
        "n_simulations": 10,
    }
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


# --- Alineación de calendarios ---------------------------------------------------


def _calendar_series(ticker: str, index: pd.DatetimeIndex, prices, asset_type) -> PriceSeries:
    cols = {c: np.asarray(prices, dtype=float) for c in ["open", "high", "low", "close"]}
    cols["volume"] = np.ones(len(index))
    return PriceSeries(
        ticker, None, asset_type, "fake", "USD", Frequency.DAILY, pd.DataFrame(cols, index=index)
    )


@pytest.fixture
def mixed_calendar() -> list[PriceSeries]:
    """Cripto 24/7 (sube un 50 % un sábado) y acción en días hábiles, desde un viernes."""
    days = pd.date_range("2024-01-05", periods=11)  # vie 05 → lun 15
    crypto = [100, 150, 150, 150, 160, 170, 180, 190, 200, 200, 210]
    btc = _calendar_series("BTC", days, crypto, AssetType.CRYPTO)
    bdays = pd.bdate_range("2024-01-05", periods=7)  # vie 05 → lun 15
    aapl = _calendar_series("AAPL", bdays, [10, 11, 12, 13, 14, 15, 16], AssetType.EQUITY)
    return [btc, aapl]


def test_portfolio_aligns_prices_before_returns(mixed_calendar: list[PriceSeries]) -> None:
    """Regresión: el lunes, BTC debe rendir viernes→lunes (+50 %), no domingo→lunes (0 %)."""
    pf = Portfolio(mixed_calendar, {"BTC": 0.5, "AAPL": 0.5})
    assert list(pf.returns.index) == list(pd.bdate_range("2024-01-08", periods=6))
    assert pf.returns.loc["2024-01-08", "BTC"] == pytest.approx(150 / 100 - 1)
    assert pf.returns.loc["2024-01-08", "AAPL"] == pytest.approx(11 / 10 - 1)


def test_portfolio_exposes_aligned_prices_and_report(mixed_calendar: list[PriceSeries]) -> None:
    pf = Portfolio(mixed_calendar, {"BTC": 0.5, "AAPL": 0.5})
    assert list(pf.prices.columns) == ["BTC", "AAPL"]
    assert not pf.prices.isna().any().any()
    assert pf.alignment_report.method == "inner"
    assert pf.alignment_report.n_dropped == 4  # dos fines de semana


def test_portfolio_ffill_alignment_keeps_more_dates(mixed_calendar: list[PriceSeries]) -> None:
    inner = Portfolio(mixed_calendar, {"BTC": 0.5, "AAPL": 0.5})
    ffill = Portfolio(mixed_calendar, {"BTC": 0.5, "AAPL": 0.5}, alignment="ffill")
    assert len(ffill.returns) > len(inner.returns)
    assert ffill.alignment_report.filled_by_ticker["AAPL"] == 4


def test_portfolio_rejects_invalid_alignment(mixed_calendar: list[PriceSeries]) -> None:
    with pytest.raises(InvalidRequestError):
        Portfolio(mixed_calendar, {"BTC": 0.5, "AAPL": 0.5}, alignment="outer")


# --- SimulationResult -----------------------------------------------------------


def test_simulation_result_importable_from_both_modules() -> None:
    from toolkit.domain import portfolio, simulation

    assert portfolio.SimulationResult is simulation.SimulationResult


def test_simulation_result_dimensions(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=15, n_simulations=40, seed=1)
    assert (sim.n_steps, sim.n_simulations) == (15, 40)


def test_percentile_bands_shape_and_monotonic(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=30, n_simulations=200, seed=1)
    bands = sim.percentile_bands()
    assert bands.shape == (31, 5)
    assert (bands.diff(axis=1).iloc[:, 1:] >= 0).all().all()
    assert np.allclose(bands.iloc[0], sim.initial_value)


def test_percentile_bands_rejects_invalid_quantiles(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=5, n_simulations=10, seed=1)
    with pytest.raises(ValueError):
        sim.percentile_bands([1.5])


def test_var_with_zero_volatility_is_deterministic(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=10, n_simulations=5, mu=-0.01, sigma=0.0, seed=1)
    expected = 100.0 - 100.0 * np.exp(-0.01 * 10)
    assert sim.var(0.95) == pytest.approx(expected)


@pytest.mark.parametrize("bad", [0.0, 1.0, 1.5, float("nan")])
def test_var_rejects_invalid_confidence(portfolio: Portfolio, bad: float) -> None:
    sim = portfolio.monte_carlo(n_steps=5, n_simulations=10, seed=1)
    with pytest.raises(ValueError):
        sim.var(bad)


# --- Divisas --------------------------------------------------------------------


def test_single_currency_has_no_warnings(portfolio: Portfolio) -> None:
    assert portfolio.warnings == ()
    assert portfolio.currencies == {"A": "USD", "B": "USD"}


def test_mixed_currencies_warn() -> None:
    pf = Portfolio(
        [make_series("A", 1, currency="USD"), make_series("B", 2, currency="EUR")],
        {"A": 0.5, "B": 0.5},
    )
    assert len(pf.warnings) == 1
    assert "EUR" in pf.warnings[0] and "USD" in pf.warnings[0]


def test_unknown_currency_warns() -> None:
    pf = Portfolio([make_series("A", 1), make_series("B", 2, currency=None)], {"A": 0.5, "B": 0.5})
    assert any("desconocida" in w and "B" in w for w in pf.warnings)


def test_strict_currency_rejects_mixed_currencies() -> None:
    with pytest.raises(InvalidSeriesError, match="Divisas mezcladas"):
        Portfolio(
            [make_series("A", 1, currency="USD"), make_series("B", 2, currency="EUR")],
            {"A": 0.5, "B": 0.5},
            strict_currency=True,
        )


def test_portfolio_periods_per_year(portfolio: Portfolio, mixed_calendar: list) -> None:
    assert portfolio.frequency is Frequency.DAILY
    assert portfolio.periods_per_year == 252
    btc = Portfolio([mixed_calendar[0]], {"BTC": 1.0})
    assert btc.asset_types == {AssetType.CRYPTO}
    assert btc.periods_per_year == 365


def test_periods_per_year_follows_aligned_calendar(mixed_calendar: list) -> None:
    """Cripto + acción: con inner quedan días hábiles (252); con ffill, todos los días (365)."""
    weights = {"BTC": 0.5, "AAPL": 0.5}
    inner = Portfolio(mixed_calendar, weights)
    ffill = Portfolio(mixed_calendar, weights, alignment="ffill")
    assert inner.periods_per_year == 252
    assert ffill.periods_per_year == 365

    vol = ffill.portfolio_returns.std(ddof=1) * np.sqrt(365)
    assert f"| Volatilidad anualizada | {vol:.2%} |" in ffill.report(sections=["metricas"])
