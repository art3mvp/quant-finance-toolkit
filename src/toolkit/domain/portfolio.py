"""Cartera de activos: pesos, alineación temporal y métricas de riesgo/retorno."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from toolkit.domain import metrics
from toolkit.domain.cleaning import AlignmentReport, AlignMethod, align_prices
from toolkit.domain.errors import InvalidSeriesError
from toolkit.domain.models import AssetType, Frequency, PriceSeries
from toolkit.domain.plotting import PlotRenderer, PortfolioPlotData, resolve_renderer
from toolkit.domain.report import RiskThresholds, build_report
from toolkit.domain.simulation import SimulationResult, simulate_gbm

#: Tolerancia para aceptar que los pesos suman 1.
WEIGHT_TOLERANCE = 1e-6


@dataclass(frozen=True, eq=False)
class Portfolio:
    """Cartera de activos con pesos fijos.

    Se valida al crearla y alinea automáticamente los **precios** de todos los activos
    en un calendario común (``toolkit.domain.cleaning.align_prices``) antes de calcular
    los retornos: así cada retorno cubre el mismo intervalo en todos los activos, aunque
    sus calendarios difieran (cripto 24/7, festivos de cada mercado...).

    Attributes:
        series: Series de precios normalizadas (de ``DownloadService``).
        weights: Peso de cada activo, indexado por ``PriceSeries.ticker``.
        alignment: ``"inner"`` (fechas comunes, por defecto) o ``"ffill"`` (unión con
            relleno hacia delante limitado; sesga a la baja volatilidad y correlación).
        ffill_limit: Máximo de periodos seguidos rellenados con ``"ffill"``.
        strict_currency: Si es ``True``, mezclar divisas (o tener alguna desconocida)
            es un error; por defecto solo se avisa en ``warnings``.
        prices: Precios alineados, una columna por activo (calculado).
        alignment_report: Fechas descartadas, huecos y NaNs de la alineación (calculado).
        returns: Retornos simples por periodo sobre los precios alineados (calculado).
        warnings: Advertencias detectadas al construirla, p. ej. divisas mezcladas
            (calculado). ``report()`` las muestra.

    Divisas: no se convierten. Con activos en varias divisas, el retorno de la cartera
    es la media ponderada de retornos en moneda local e ignora el tipo de cambio. Se
    avisa en lugar de rechazarlo porque comparar mercados en moneda local es un análisis
    legítimo y convertir exigiría una serie de FX y una política de conversión.

    Raises:
        InvalidSeriesError: Si las series o los pesos no son válidos.
    """

    series: list[PriceSeries]
    weights: dict[str, float]
    alignment: AlignMethod = "inner"
    ffill_limit: int | None = 5
    strict_currency: bool = False
    prices: pd.DataFrame = field(init=False, repr=False)
    alignment_report: AlignmentReport = field(init=False, repr=False)
    returns: pd.DataFrame = field(init=False, repr=False)
    warnings: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "series", list(self.series))
        object.__setattr__(self, "weights", dict(self.weights))
        self._validate()
        object.__setattr__(self, "warnings", tuple(self._currency_warnings()))
        self._align()

    def _validate(self) -> None:
        if not self.series:
            raise InvalidSeriesError("Portfolio: se necesita al menos una serie")
        tickers = [s.ticker for s in self.series]
        if len(set(tickers)) != len(tickers):
            raise InvalidSeriesError("Portfolio: hay tickers duplicados en las series")
        if set(tickers) != set(self.weights):
            raise InvalidSeriesError(
                f"Portfolio: los tickers {sorted(tickers)} no coinciden "
                f"con los pesos {sorted(self.weights)}"
            )
        for ticker, w in self.weights.items():
            if not isinstance(w, (int, float, np.integer, np.floating)) or isinstance(w, bool):
                raise InvalidSeriesError(f"Portfolio: el peso de {ticker} no es numérico")
            if not math.isfinite(w):
                raise InvalidSeriesError(f"Portfolio: el peso de {ticker} no es finito ({w})")
            if w < 0:
                raise InvalidSeriesError("Portfolio: no se admiten pesos negativos")
        total = sum(self.weights.values())
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            raise InvalidSeriesError(f"Portfolio: los pesos suman {total:.6f}, deben sumar 1")
        if len({s.frequency for s in self.series}) > 1:
            raise InvalidSeriesError("Portfolio: todas las series deben tener la misma frecuencia")

    def _currency_warnings(self) -> list[str]:
        """Avisos de divisas mezcladas o desconocidas (error si ``strict_currency``)."""
        found: list[str] = []
        known = sorted({c for c in self.currencies.values() if c is not None})
        if len(known) > 1:
            found.append(
                f"Divisas mezcladas ({', '.join(known)}): los retornos están en moneda local "
                "y no incluyen el efecto del tipo de cambio."
            )
        unknown = [t for t, c in self.currencies.items() if c is None]
        if unknown:
            found.append(f"Divisa desconocida para {', '.join(unknown)}.")
        if found and self.strict_currency:
            raise InvalidSeriesError(f"Portfolio: {' '.join(found)}")
        return found

    def _align(self) -> None:
        """Alinea los precios y calcula los retornos sobre el calendario común."""
        aligned = align_prices(
            {s.ticker: s.prices for s in self.series}, self.alignment, self.ffill_limit
        )
        returns = aligned.returns
        if len(returns) < 2:
            raise InvalidSeriesError("Portfolio: menos de 2 fechas comunes entre las series")
        object.__setattr__(self, "prices", aligned.prices)
        object.__setattr__(self, "alignment_report", aligned.report)
        object.__setattr__(self, "returns", returns)

    @property
    def series_by_ticker(self) -> dict[str, PriceSeries]:
        """Series indexadas por ticker."""
        return {s.ticker: s for s in self.series}

    @property
    def currencies(self) -> dict[str, str | None]:
        """Divisa de cada activo (``None`` si la fuente no la informa)."""
        return {s.ticker: s.currency for s in self.series}

    @property
    def frequency(self) -> Frequency:
        """Frecuencia común de todas las series."""
        return self.series[0].frequency

    @property
    def asset_types(self) -> set[AssetType]:
        """Tipos de activo presentes en la cartera."""
        return {s.asset_type for s in self.series}

    @property
    def periods_per_year(self) -> int:
        """Periodos por año para anualizar, según el calendario **alineado**.

        En frecuencia diaria se miran las fechas: si incluyen fines de semana (cripto
        sola, o mezclada con acciones y alineada con ``ffill``) se usan 365; si solo hay
        días hábiles, 252. En el resto de frecuencias, 52, 12, 4 o 1.
        """
        if self.frequency is Frequency.DAILY:
            has_weekends = bool((self.prices.index.day_of_week >= 5).any())
            return (
                metrics.CRYPTO_DAYS_PER_YEAR
                if has_weekends
                else metrics.PERIODS_PER_YEAR[Frequency.DAILY]
            )
        return metrics.periods_per_year(self.frequency, self.asset_types)

    @property
    def tickers(self) -> list[str]:
        """Tickers en el orden de las columnas de ``returns``."""
        return list(self.returns.columns)

    @property
    def weight_vector(self) -> np.ndarray:
        """Pesos en el mismo orden que ``tickers``."""
        return np.array([self.weights[t] for t in self.tickers])

    @property
    def covariance(self) -> pd.DataFrame:
        """Matriz de covarianzas de los retornos por periodo."""
        return self.returns.cov()

    @property
    def portfolio_returns(self) -> pd.Series:
        """Serie de retornos de la cartera (pesos constantes)."""
        return (self.returns @ self.weight_vector).rename("portfolio")

    @property
    def mean_return(self) -> float:
        """Retorno medio de la cartera por periodo."""
        return float(self.portfolio_returns.mean())

    @property
    def volatility(self) -> float:
        """Volatilidad de la cartera por periodo: sqrt(w' Σ w)."""
        w = self.weight_vector
        return float(np.sqrt(w @ self.covariance.to_numpy() @ w))

    def monte_carlo(
        self,
        n_steps: int = 252,
        n_simulations: int = 1000,
        initial_value: float = 100.0,
        mu: float | None = None,
        sigma: float | None = None,
        seed: int | None = None,
    ) -> SimulationResult:
        """Simula la evolución de la cartera completa.

        Si no se indican ``mu`` y ``sigma`` (por periodo), se estiman de los
        retornos alineados de la cartera.
        """
        mu = self.mean_return if mu is None else mu
        sigma = self.volatility if sigma is None else sigma
        paths = simulate_gbm(initial_value, mu, sigma, n_steps, n_simulations, seed)
        return SimulationResult(paths, initial_value, mu, sigma)

    def monte_carlo_asset(
        self,
        ticker: str,
        n_steps: int = 252,
        n_simulations: int = 1000,
        mu: float | None = None,
        sigma: float | None = None,
        seed: int | None = None,
    ) -> SimulationResult:
        """Simula un único activo de la cartera, partiendo de su último precio.

        ``mu`` y ``sigma`` se estiman de los mismos retornos alineados que
        ``monte_carlo`` (misma muestra, al menos 2 observaciones). El precio inicial es
        el último de la serie original, que puede ser posterior a la última fecha común.
        """
        if ticker not in self.returns.columns:
            raise InvalidSeriesError(f"Portfolio: el ticker {ticker!r} no está en la cartera")
        asset_returns = self.returns[ticker]
        mu = float(asset_returns.mean()) if mu is None else mu
        sigma = float(asset_returns.std(ddof=1)) if sigma is None else sigma
        initial = float(self.series_by_ticker[ticker].prices.iloc[-1])
        paths = simulate_gbm(initial, mu, sigma, n_steps, n_simulations, seed)
        return SimulationResult(paths, initial, mu, sigma)

    def report(
        self,
        *,
        risk_free: float = 0.0,
        confidence: float = 0.95,
        periods_per_year: int | None = None,
        sections: Iterable[str] | None = None,
        simulation: SimulationResult | None = None,
        thresholds: RiskThresholds | None = None,
        title: str = "Informe de cartera",
    ) -> str:
        """Informe en Markdown con métricas clave, diagnósticos y advertencias de riesgo.

        Args:
            risk_free: Tipo libre de riesgo **anual** para el Sharpe (``0.03`` = 3 %).
            confidence: Nivel de confianza del VaR/CVaR (``0.95`` o ``0.99``...).
            periods_per_year: Periodos por año para anualizar; por defecto se deduce
                de la frecuencia (``self.periods_per_year``).
            sections: Secciones a incluir, de ``toolkit.domain.report.SECTIONS``
                (``resumen``, ``metricas``, ``pesos``, ``activos``, ``correlaciones``,
                ``diagnostico``, ``simulacion``, ``advertencias``). Por defecto, todas.
            simulation: Resultado de ``monte_carlo()`` para la sección ``simulacion``.
                El informe no simula por sí mismo, así es reproducible.
            thresholds: Umbrales de las advertencias (``RiskThresholds``).
            title: Título del informe.

        Returns:
            Texto Markdown (muéstralo con ``IPython.display.Markdown`` o guárdalo en un
            ``.md``).

        Raises:
            InvalidRequestError: Si una sección o un parámetro no son válidos.
        """
        return build_report(
            self,
            risk_free=risk_free,
            confidence=confidence,
            periods_per_year=periods_per_year,
            sections=sections,
            simulation=simulation,
            thresholds=thresholds,
            title=title,
        )

    def plot_data(
        self, base: float = 100.0, title: str = "Informe visual de la cartera"
    ) -> PortfolioPlotData:
        """Datos de los gráficos de la cartera, calculados sobre la muestra alineada."""
        ppy = self.periods_per_year
        asset_perf = base * self.prices / self.prices.iloc[0]
        value = pd.concat(
            [
                pd.Series([base], index=self.prices.index[:1]),
                metrics.wealth_index(self.portfolio_returns, base),
            ]
        ).rename("cartera")
        performance = asset_perf.assign(cartera=value)
        columns = {**{t: self.returns[t] for t in self.tickers}, "cartera": self.portfolio_returns}
        risk_return = pd.DataFrame(
            {
                "retorno": {k: metrics.annualized_return(r, ppy) for k, r in columns.items()},
                "volatilidad": {
                    k: metrics.annualized_volatility(r, ppy) for k, r in columns.items()
                },
            }
        )
        return PortfolioPlotData(
            performance=performance,
            value=value,
            drawdown=metrics.drawdown(self.portfolio_returns),
            correlation=self.returns.corr(),
            weights=pd.Series(self.weight_vector, index=self.tickers, name="peso"),
            risk_return=risk_return,
            title=title,
        )

    def plots_report(
        self, renderer: PlotRenderer | None = None, *, title: str = "Informe visual de la cartera"
    ) -> Any:
        """Visualizaciones de la cartera: rendimiento comparado (base 100), evolución del
        valor, drawdown, matriz de correlación, pesos y riesgo/retorno por activo.

        El dominio prepara los datos (``plot_data``) y el dibujo lo hace el ``renderer``
        inyectado, así el núcleo no depende de ninguna librería gráfica.

        Args:
            renderer: Adaptador que dibuja (p. ej. ``build_plot_renderer()``); por
                defecto, el registrado con ``bootstrap.configure_plotting()``.
            title: Título del conjunto de gráficos.

        Returns:
            Lo que devuelva el renderer (una ``Figure`` con matplotlib).

        Raises:
            ConfigurationError: Si no hay renderer.
        """
        return resolve_renderer(renderer).render_portfolio(self.plot_data(title=title))
