"""Tests del contrato de visualización: el dominio prepara datos y delega el dibujo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.fakes import RecordingRenderer
from toolkit.domain import metrics
from toolkit.domain.errors import ConfigurationError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.domain.plotting import (
    PlotRenderer,
    get_default_renderer,
    resolve_renderer,
    set_default_renderer,
)
from toolkit.domain.portfolio import Portfolio


def make(ticker: str, seed: int, n: int = 120) -> PriceSeries:
    rng = np.random.default_rng(seed)
    prices = 100 * np.exp(rng.normal(0, 0.01, n).cumsum())
    cols = {c: prices for c in ["open", "high", "low", "close", "volume"]}
    return PriceSeries(
        ticker,
        None,
        AssetType.EQUITY,
        "fake",
        "USD",
        Frequency.DAILY,
        pd.DataFrame(cols, index=pd.bdate_range("2024-01-01", periods=n)),
    )


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio([make("A", 1), make("B", 2), make("C", 3)], {"A": 0.5, "B": 0.3, "C": 0.2})


# --- Portfolio.plots_report -------------------------------------------------------


def test_plots_report_delegates_to_renderer(portfolio: Portfolio) -> None:
    renderer = RecordingRenderer()
    assert portfolio.plots_report(renderer, title="Mi cartera") == "portfolio-figure"
    assert len(renderer.portfolios) == 1
    assert renderer.portfolios[0].title == "Mi cartera"


def test_portfolio_plot_data(portfolio: Portfolio) -> None:
    data = portfolio.plot_data()
    assert list(data.performance.columns) == ["A", "B", "C", "cartera"]
    assert np.allclose(data.performance.iloc[0], 100.0)
    assert data.performance.index.equals(portfolio.prices.index)
    expected_value = metrics.wealth_index(portfolio.portfolio_returns, 100.0)
    assert np.allclose(data.value.iloc[1:], expected_value)
    assert (data.drawdown <= 0).all()
    assert np.allclose(data.correlation, data.correlation.T)
    assert data.weights.to_dict() == pytest.approx(portfolio.weights)
    assert list(data.risk_return.index) == ["A", "B", "C", "cartera"]
    assert list(data.risk_return.columns) == ["retorno", "volatilidad"]


# --- SimulationResult.plot --------------------------------------------------------


def test_simulation_plot_delegates_to_renderer(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=30, n_simulations=200, seed=1)
    renderer = RecordingRenderer()
    assert sim.plot(renderer, max_paths=20) == "simulation-figure"
    data = renderer.simulations[0]
    assert data.sample_paths.shape == (31, 20)
    pd.testing.assert_frame_equal(data.bands, sim.percentile_bands())
    assert data.var_level == pytest.approx(sim.quantile(0.05))
    assert len(data.final_values) == 200


def test_simulation_plot_data_caps_paths(portfolio: Portfolio) -> None:
    sim = portfolio.monte_carlo(n_steps=5, n_simulations=10, seed=1)
    assert sim.plot_data(max_paths=500).sample_paths.shape == (6, 10)
    with pytest.raises(ValueError):
        sim.plot_data(max_paths=0)


# --- Renderer predeterminado ------------------------------------------------------


def test_without_renderer_raises_configuration_error(portfolio: Portfolio) -> None:
    assert get_default_renderer() is None
    with pytest.raises(ConfigurationError, match="configure_plotting"):
        portfolio.plots_report()
    with pytest.raises(ConfigurationError):
        portfolio.monte_carlo(n_steps=5, n_simulations=5, seed=1).plot()


def test_default_renderer_is_used(portfolio: Portfolio) -> None:
    renderer = RecordingRenderer()
    set_default_renderer(renderer)
    assert portfolio.plots_report() == "portfolio-figure"
    assert portfolio.monte_carlo(n_steps=5, n_simulations=5, seed=1).plot() == "simulation-figure"
    assert len(renderer.portfolios) == len(renderer.simulations) == 1


def test_explicit_renderer_wins_over_default(portfolio: Portfolio) -> None:
    default, explicit = RecordingRenderer(), RecordingRenderer()
    set_default_renderer(default)
    portfolio.plots_report(explicit)
    assert explicit.portfolios and not default.portfolios


def test_rejects_objects_that_do_not_satisfy_protocol() -> None:
    with pytest.raises(ConfigurationError):
        set_default_renderer(object())  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError):
        resolve_renderer(object())  # type: ignore[arg-type]


def test_recording_renderer_satisfies_protocol() -> None:
    assert isinstance(RecordingRenderer(), PlotRenderer)
