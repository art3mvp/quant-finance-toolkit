"""Tests del informe Markdown de la cartera."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from toolkit.domain import metrics
from toolkit.domain.errors import InvalidRequestError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.domain.portfolio import Portfolio
from toolkit.domain.report import SECTIONS, RiskThresholds

HEADINGS = {
    "resumen": "## Resumen",
    "metricas": "## Métricas de la cartera",
    "pesos": "## Pesos",
    "activos": "## Activos",
    "correlaciones": "## Correlaciones",
    "diagnostico": "## Diagnóstico de datos",
    "simulacion": "## Simulación de Monte Carlo",
    "advertencias": "## Advertencias de riesgo",
}


def make(ticker: str, prices: np.ndarray, currency: str = "USD", start: str = "2023-01-02"):
    idx = pd.bdate_range(start, periods=len(prices))
    cols = {c: prices for c in ["open", "high", "low", "close", "volume"]}
    return PriceSeries(
        ticker,
        None,
        AssetType.EQUITY,
        "fake",
        currency,
        Frequency.DAILY,
        pd.DataFrame(cols, index=idx),
    )


def walk(seed: int, n: int = 300) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(rng.normal(0, 0.01, n).cumsum())


@pytest.fixture
def balanced() -> Portfolio:
    """Cuatro activos independientes al 25 %, muestra larga: no debería haber avisos."""
    series = [make(t, walk(i)) for i, t in enumerate(["A", "B", "C", "D"])]
    return Portfolio(series, dict.fromkeys(["A", "B", "C", "D"], 0.25))


def test_report_is_markdown_with_all_sections(balanced: Portfolio) -> None:
    text = balanced.report()
    assert text.startswith("# Informe de cartera\n")
    for heading in HEADINGS.values():
        assert heading in text
    assert "| :--- |" in text
    assert text.index("## Resumen") < text.index("## Advertencias de riesgo")


def test_balanced_portfolio_has_no_warnings(balanced: Portfolio) -> None:
    assert "- Sin advertencias." in balanced.report(sections=["advertencias"])


def test_sections_filter(balanced: Portfolio) -> None:
    text = balanced.report(sections=["pesos"], title="Solo pesos")
    assert text.startswith("# Solo pesos")
    assert "## Pesos" in text
    assert all(h not in text for k, h in HEADINGS.items() if k != "pesos")
    assert "| A | 25.0% |" in text


def test_sections_accepts_a_single_string(balanced: Portfolio) -> None:
    assert "## Pesos" in balanced.report(sections="pesos")


@pytest.mark.parametrize("bad", [["inventada"], []])
def test_invalid_sections_raise(balanced: Portfolio, bad: list) -> None:
    with pytest.raises(InvalidRequestError):
        balanced.report(sections=bad)


def test_metrics_match_metric_functions(balanced: Portfolio) -> None:
    text = balanced.report(sections=["metricas"])
    r = balanced.portfolio_returns
    assert f"{metrics.annualized_volatility(r, 252):.2%}" in text
    assert f"{metrics.max_drawdown(r):.2%}" in text
    assert f"{metrics.historical_var(r, 0.95):.2%}" in text


def test_risk_free_changes_sharpe(balanced: Portfolio) -> None:
    text = balanced.report(sections=["metricas"], risk_free=0.04)
    sharpe = metrics.sharpe_ratio(balanced.portfolio_returns, 252, 0.04)
    assert "Sharpe (rf = 4.00%)" in text
    assert f"| {sharpe:.2f} |" in text


def test_periods_per_year_override(balanced: Portfolio) -> None:
    text = balanced.report(sections=["metricas"], periods_per_year=12)
    vol = metrics.annualized_volatility(balanced.portfolio_returns, 12)
    assert f"| Volatilidad anualizada | {vol:.2%} |" in text


def test_confidence_level_is_parametrizable(balanced: Portfolio) -> None:
    text = balanced.report(sections=["metricas"], confidence=0.99)
    assert "VaR histórico 99%" in text
    with pytest.raises(InvalidRequestError):
        balanced.report(confidence=1.5)


def test_concentration_and_short_sample_warnings() -> None:
    pf = Portfolio([make("A", walk(1, 50)), make("B", walk(2, 50))], {"A": 0.9, "B": 0.1})
    text = pf.report(sections=["advertencias"])
    assert "Concentración: A pesa un 90%" in text
    assert "Muestra corta" in text


def test_custom_thresholds_silence_warnings() -> None:
    pf = Portfolio([make("A", walk(1, 50)), make("B", walk(2, 50))], {"A": 0.9, "B": 0.1})
    text = pf.report(
        sections=["advertencias"], thresholds=RiskThresholds(max_weight=0.95, min_obs=10)
    )
    assert "- Sin advertencias." in text


def test_currency_warning_in_report() -> None:
    pf = Portfolio([make("A", walk(1)), make("B", walk(2), currency="EUR")], {"A": 0.5, "B": 0.5})
    assert "Divisas mezcladas (EUR, USD)" in pf.report(sections=["advertencias"])


def test_high_correlation_warning() -> None:
    base = walk(1)
    noise = np.exp(np.random.default_rng(9).normal(0, 0.0005, len(base)).cumsum())
    pf = Portfolio([make("A", base), make("B", base * noise)], {"A": 0.5, "B": 0.5})
    assert "Correlación alta entre A y B" in pf.report(sections=["advertencias"])


def test_high_volatility_warning() -> None:
    rng = np.random.default_rng(3)
    wild = 100 * np.exp(rng.normal(0, 0.05, 300).cumsum())
    pf = Portfolio([make("A", wild)], {"A": 1.0})
    text = pf.report(sections=["advertencias"])
    assert "Volatilidad anual elevada" in text
    assert "un solo activo" in text


def test_dropped_dates_are_diagnosed() -> None:
    a = make("A", walk(1))
    b_full = make("B", walk(2))
    b = PriceSeries(
        "B", None, AssetType.EQUITY, "fake", "USD", Frequency.DAILY, b_full.data.iloc[::2]
    )
    pf = Portfolio([a, b], {"A": 0.5, "B": 0.5})
    text = pf.report(sections=["diagnostico", "advertencias"])
    assert f"**Fechas descartadas:** {pf.alignment_report.n_dropped}" in text
    assert " más" in text  # más de MAX_LISTED_DATES fechas listadas
    assert "La alineación descartó" in text


def test_simulation_section(balanced: Portfolio) -> None:
    assert "No incluida" in balanced.report(sections=["simulacion"])
    sim = balanced.monte_carlo(n_steps=50, n_simulations=500, seed=1)
    text = balanced.report(sections=["simulacion"], simulation=sim)
    assert f"{sim.quantile(0.05):.2f}" in text
    assert "| Trayectorias | 500 |" in text


def test_report_is_deterministic(balanced: Portfolio) -> None:
    assert balanced.report() == balanced.report()


def test_sections_constant_matches_headings() -> None:
    assert set(SECTIONS) == set(HEADINGS)
