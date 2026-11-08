"""Informe Markdown de una cartera: métricas, diagnósticos y advertencias de riesgo.

Construcción de texto pura (sin dependencias de presentación), por eso vive en el
dominio. Lo usa ``Portfolio.report()``; las tablas se escriben a mano para no depender
de ``tabulate``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from toolkit.domain import metrics
from toolkit.domain.errors import InvalidRequestError
from toolkit.domain.simulation import SimulationResult

if TYPE_CHECKING:
    from toolkit.domain.portfolio import Portfolio

#: Secciones disponibles, en el orden en que aparecen.
SECTIONS: tuple[str, ...] = (
    "resumen",
    "metricas",
    "pesos",
    "activos",
    "correlaciones",
    "diagnostico",
    "simulacion",
    "advertencias",
)

#: Número máximo de fechas descartadas que se listan en el diagnóstico.
MAX_LISTED_DATES = 10


@dataclass(frozen=True)
class RiskThresholds:
    """Umbrales a partir de los cuales el informe emite una advertencia.

    Attributes:
        max_weight: Peso máximo de un activo antes de avisar de concentración.
        min_obs: Mínimo de retornos para considerar fiable la muestra.
        high_corr: Correlación entre dos activos que se considera alta.
        high_vol: Volatilidad anual de la cartera que se considera alta.
        max_dropped_ratio: Proporción de fechas descartadas al alinear que merece aviso.
    """

    max_weight: float = 0.40
    min_obs: int = 252
    high_corr: float = 0.80
    high_vol: float = 0.30
    max_dropped_ratio: float = 0.10


DEFAULT_THRESHOLDS = RiskThresholds()


def _pct(value: float, digits: int = 2) -> str:
    return "n/d" if not math.isfinite(value) else f"{value:.{digits}%}"


def _num(value: float, digits: int = 2) -> str:
    return "n/d" if not math.isfinite(value) else f"{value:.{digits}f}"


def _md_table(header: list[str], rows: Iterable[list[str]]) -> str:
    """Tabla Markdown (la primera columna alineada a la izquierda, el resto a la derecha)."""
    align = [":---"] + ["---:"] * (len(header) - 1)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _high_correlations(corr: pd.DataFrame, threshold: float) -> list[tuple[str, str, float]]:
    pairs = []
    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            value = float(corr.loc[a, b])
            if math.isfinite(value) and value >= threshold:
                pairs.append((a, b, value))
    return pairs


def risk_warnings(portfolio: Portfolio, ppy: int, thresholds: RiskThresholds) -> list[str]:
    """Advertencias de riesgo y de calidad de datos de la cartera."""
    found = list(portfolio.warnings)
    for ticker, weight in portfolio.weights.items():
        if weight > thresholds.max_weight and len(portfolio.weights) > 1:
            found.append(
                f"Concentración: {ticker} pesa un {weight:.0%} "
                f"(umbral {thresholds.max_weight:.0%})."
            )
    if len(portfolio.weights) == 1:
        found.append("Cartera de un solo activo: sin diversificación.")
    n = len(portfolio.returns)
    if n < thresholds.min_obs:
        found.append(
            f"Muestra corta: {n} retornos (< {thresholds.min_obs}); las métricas son poco fiables."
        )
    for a, b, value in _high_correlations(portfolio.returns.corr(), thresholds.high_corr):
        found.append(f"Correlación alta entre {a} y {b} ({value:.2f}): diversificación limitada.")
    vol = metrics.annualized_volatility(portfolio.portfolio_returns, ppy)
    if math.isfinite(vol) and vol > thresholds.high_vol:
        found.append(f"Volatilidad anual elevada: {vol:.1%} (umbral {thresholds.high_vol:.0%}).")
    report = portfolio.alignment_report
    if report.dropped_ratio > thresholds.max_dropped_ratio:
        found.append(
            f"La alineación descartó {report.n_dropped} de {report.n_union} fechas "
            f"({report.dropped_ratio:.0%}): revisa calendarios o huecos."
        )
    if report.method == "ffill" and any(report.filled_by_ticker.values()):
        found.append(
            "Se han rellenado precios (ffill): la volatilidad y la correlación están "
            "sesgadas a la baja."
        )
    return found


@dataclass(frozen=True)
class _Context:
    portfolio: Portfolio
    ppy: int
    risk_free: float
    confidence: float
    simulation: SimulationResult | None
    thresholds: RiskThresholds


def _section_resumen(ctx: _Context) -> str:
    pf, report = ctx.portfolio, ctx.portfolio.alignment_report
    sources = sorted({s.source for s in pf.series})
    currencies = sorted({c or "desconocida" for c in pf.currencies.values()})
    return "\n".join(
        [
            "## Resumen",
            "",
            f"- **Activos:** {len(pf.series)} ({', '.join(pf.tickers)})",
            f"- **Periodo:** {pf.returns.index[0].date()} → {pf.returns.index[-1].date()}",
            f"- **Retornos:** {len(pf.returns)} ({pf.frequency.value}, {ctx.ppy} periodos/año)",
            f"- **Fuentes:** {', '.join(sources)} · **Divisas:** {', '.join(currencies)}",
            f"- **Alineación:** `{report.method}`",
        ]
    )


def _section_metricas(ctx: _Context) -> str:
    r = ctx.portfolio.portfolio_returns
    c = ctx.confidence
    rows = [
        ["Retorno anualizado (CAGR)", _pct(metrics.annualized_return(r, ctx.ppy))],
        ["Volatilidad anualizada", _pct(metrics.annualized_volatility(r, ctx.ppy))],
        [
            f"Sharpe (rf = {ctx.risk_free:.2%})",
            _num(metrics.sharpe_ratio(r, ctx.ppy, ctx.risk_free)),
        ],
        ["Máximo drawdown", _pct(metrics.max_drawdown(r))],
        [f"VaR histórico {c:.0%} (1 periodo)", _pct(metrics.historical_var(r, c))],
        [f"CVaR histórico {c:.0%} (1 periodo)", _pct(metrics.historical_cvar(r, c))],
        ["Retorno medio por periodo", _pct(ctx.portfolio.mean_return, 4)],
        ["Volatilidad por periodo", _pct(ctx.portfolio.volatility, 4)],
    ]
    return "\n".join(
        [
            "## Métricas de la cartera",
            "",
            _md_table(["Métrica", "Valor"], rows),
            "",
            "_Pesos constantes: la cartera se rebalancea a sus pesos objetivo cada periodo._",
        ]
    )


def _section_pesos(ctx: _Context) -> str:
    rows = [[t, _pct(ctx.portfolio.weights[t], 1)] for t in ctx.portfolio.tickers]
    return "\n".join(["## Pesos", "", _md_table(["Activo", "Peso"], rows)])


def _section_activos(ctx: _Context) -> str:
    rows = []
    for t in ctx.portfolio.tickers:
        r = ctx.portfolio.returns[t]
        rows.append(
            [
                t,
                _pct(metrics.annualized_return(r, ctx.ppy)),
                _pct(metrics.annualized_volatility(r, ctx.ppy)),
                _num(metrics.sharpe_ratio(r, ctx.ppy, ctx.risk_free)),
                _pct(metrics.max_drawdown(r)),
                _pct(metrics.historical_var(r, ctx.confidence)),
                _pct(metrics.historical_cvar(r, ctx.confidence)),
            ]
        )
    header = [
        "Activo",
        "Retorno anual",
        "Volatilidad anual",
        "Sharpe",
        "Máx. drawdown",
        "VaR",
        "CVaR",
    ]
    return "\n".join(
        [
            "## Activos",
            "",
            _md_table(header, rows),
            "",
            "_Calculado sobre la muestra alineada de la cartera; puede diferir de los "
            "estadísticos de cada `PriceSeries`, que usan su serie completa._",
        ]
    )


def _section_correlaciones(ctx: _Context) -> str:
    corr = ctx.portfolio.returns.corr()
    rows = [[a, *(_num(float(corr.loc[a, b])) for b in corr.columns)] for a in corr.index]
    return "\n".join(["## Correlaciones", "", _md_table(["", *corr.columns], rows)])


def _section_diagnostico(ctx: _Context) -> str:
    report = ctx.portfolio.alignment_report
    lines = [
        "## Diagnóstico de datos",
        "",
        f"- **Método de alineación:** `{report.method}`"
        + (f" (límite {report.ffill_limit})" if report.ffill_limit else ""),
        f"- **Fechas en la unión de calendarios:** {report.n_union}",
        f"- **Fechas conservadas:** {report.n_kept}",
        f"- **Fechas descartadas:** {report.n_dropped} ({report.dropped_ratio:.1%})",
    ]
    if report.n_dropped:
        listed = ", ".join(str(d.date()) for d in report.dropped_dates[:MAX_LISTED_DATES])
        more = report.n_dropped - MAX_LISTED_DATES
        lines.append(f"  - {listed}" + (f" y {more} más" if more > 0 else ""))
    rows = [
        [
            t,
            str(ctx.portfolio.series_by_ticker[t].n_obs),
            str(report.missing_by_ticker.get(t, 0)),
            str(report.nan_dropped_by_ticker.get(t, 0)),
            str(report.filled_by_ticker.get(t, 0)),
        ]
        for t in ctx.portfolio.tickers
    ]
    header = ["Activo", "Observaciones", "Sin precio en la unión", "NaN eliminados", "Rellenados"]
    lines += ["", _md_table(header, rows)]
    return "\n".join(lines)


def _section_simulacion(ctx: _Context) -> str:
    sim = ctx.simulation
    if sim is None:
        return "\n".join(
            [
                "## Simulación de Monte Carlo",
                "",
                "_No incluida: pasa `simulation=cartera.monte_carlo(...)` a `report()`._",
            ]
        )
    c = ctx.confidence
    rows = [
        ["Horizonte (periodos)", str(sim.n_steps)],
        ["Trayectorias", str(sim.n_simulations)],
        ["μ / σ por periodo", f"{sim.mu:.5f} / {sim.sigma:.5f}"],
        ["Valor inicial", _num(sim.initial_value)],
        ["Mediana del valor final", _num(sim.quantile(0.5))],
        [f"Percentil {1 - c:.0%} del valor final", _num(sim.quantile(1 - c))],
        [f"VaR {c:.0%} al horizonte", _num(sim.var(c))],
        [f"CVaR {c:.0%} al horizonte (pérdida media en la cola)", _num(sim.cvar(c))],
        ["Probabilidad de pérdida", _pct(sim.prob_loss, 1)],
    ]
    return "\n".join(
        [
            "## Simulación de Monte Carlo",
            "",
            _md_table(["Resultado", "Valor"], rows),
            "",
            "_Movimiento browniano geométrico con μ y σ constantes: no recoge colas gruesas "
            "ni cambios de régimen._",
        ]
    )


def _section_advertencias(ctx: _Context) -> str:
    found = risk_warnings(ctx.portfolio, ctx.ppy, ctx.thresholds)
    body = "\n".join(f"- ⚠️ {w}" for w in found) if found else "- Sin advertencias."
    return "\n".join(["## Advertencias de riesgo", "", body])


_BUILDERS: dict[str, Callable[[_Context], str]] = {
    "resumen": _section_resumen,
    "metricas": _section_metricas,
    "pesos": _section_pesos,
    "activos": _section_activos,
    "correlaciones": _section_correlaciones,
    "diagnostico": _section_diagnostico,
    "simulacion": _section_simulacion,
    "advertencias": _section_advertencias,
}


def _resolve_sections(sections: Iterable[str] | None) -> list[str]:
    if sections is None:
        return list(SECTIONS)
    if isinstance(sections, str):
        sections = [sections]
    chosen = list(sections)
    unknown = [s for s in chosen if s not in SECTIONS]
    if unknown:
        raise InvalidRequestError(f"report: secciones desconocidas {unknown}; usa {SECTIONS}")
    if not chosen:
        raise InvalidRequestError("report: indica al menos una sección")
    return [s for s in SECTIONS if s in chosen]


def build_report(
    portfolio: Portfolio,
    *,
    risk_free: float = 0.0,
    confidence: float = 0.95,
    periods_per_year: int | None = None,
    sections: Iterable[str] | None = None,
    simulation: SimulationResult | None = None,
    thresholds: RiskThresholds | None = None,
    title: str = "Informe de cartera",
) -> str:
    """Genera el informe Markdown de ``portfolio`` (ver ``Portfolio.report``)."""
    chosen = _resolve_sections(sections)
    ppy = portfolio.periods_per_year if periods_per_year is None else periods_per_year
    ctx = _Context(
        portfolio=portfolio,
        ppy=metrics.check_periods_per_year(ppy),
        risk_free=risk_free,
        confidence=metrics.check_confidence(confidence),
        simulation=simulation,
        thresholds=thresholds or DEFAULT_THRESHOLDS,
    )
    parts = [f"# {title}"] + [_BUILDERS[name](ctx) for name in chosen]
    return "\n\n".join(parts) + "\n"
