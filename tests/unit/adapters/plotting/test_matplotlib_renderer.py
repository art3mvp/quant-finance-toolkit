"""Tests del renderer de matplotlib (backend Agg: sin ventanas)."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pandas as pd
import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from matplotlib.figure import Figure  # noqa: E402

from toolkit.adapters.outbound.plotting.matplotlib_renderer import (  # noqa: E402
    MatplotlibPlotRenderer,
)
from toolkit.domain.models import AssetType, Frequency, PriceSeries  # noqa: E402
from toolkit.domain.portfolio import Portfolio  # noqa: E402
from toolkit.ports.outbound import PlotRenderer  # noqa: E402


def make(ticker: str, seed: int, n: int = 80) -> PriceSeries:
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


@pytest.fixture
def renderer() -> MatplotlibPlotRenderer:
    return MatplotlibPlotRenderer()


def test_satisfies_port(renderer: MatplotlibPlotRenderer) -> None:
    assert isinstance(renderer, PlotRenderer)


def test_portfolio_figure(portfolio: Portfolio, renderer: MatplotlibPlotRenderer) -> None:
    fig = portfolio.plots_report(renderer, title="Cartera test")
    assert isinstance(fig, Figure)
    titles = [ax.get_title() for ax in fig.axes]
    assert "Rendimiento comparado (base 100)" in titles
    assert "Matriz de correlación" in titles
    assert any(t.startswith("Drawdown") for t in titles)
    assert "Pesos" in titles
    assert fig.get_suptitle() == "Cartera test"
    heatmap = next(ax for ax in fig.axes if ax.get_title() == "Matriz de correlación")
    assert heatmap.images[0].get_array().shape == (3, 3)
    performance = next(ax for ax in fig.axes if ax.get_title().startswith("Rendimiento"))
    assert len(performance.get_lines()) == 4 + 1  # 3 activos + cartera + línea base 100
    fig.savefig(BytesIO(), format="png")


def test_simulation_figure(portfolio: Portfolio, renderer: MatplotlibPlotRenderer) -> None:
    sim = portfolio.monte_carlo(n_steps=20, n_simulations=300, seed=1)
    fig = sim.plot(renderer, max_paths=10)
    assert isinstance(fig, Figure)
    paths_ax, hist_ax = fig.axes
    assert paths_ax.get_title() == "Trayectorias simuladas"
    assert len(paths_ax.get_lines()) >= 10
    assert hist_ax.get_title() == "Distribución del valor final"
    assert len(hist_ax.patches) == 60
    fig.savefig(BytesIO(), format="png")


def test_single_asset_portfolio_renders(renderer: MatplotlibPlotRenderer) -> None:
    fig = Portfolio([make("A", 1)], {"A": 1.0}).plots_report(renderer)
    fig.savefig(BytesIO(), format="png")


def test_does_not_use_pyplot_state(portfolio: Portfolio, renderer: MatplotlibPlotRenderer) -> None:
    import matplotlib.pyplot as plt

    before = plt.get_fignums()
    portfolio.plots_report(renderer)
    assert plt.get_fignums() == before
