"""Cartera de activos: pesos, alineación temporal y métricas de riesgo/retorno."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from toolkit.domain.errors import InvalidSeriesError
from toolkit.domain.models import PriceSeries
from toolkit.domain.simulation import simulate_gbm

#: Tolerancia para aceptar que los pesos suman 1.
WEIGHT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SimulationResult:
    """Resultado de una simulación de Monte Carlo.

    Attributes:
        paths: Array ``(n_steps + 1, n_simulations)`` con las trayectorias.
        initial_value: Valor de partida.
        mu: Retorno por periodo usado.
        sigma: Volatilidad por periodo usada.
    """

    paths: np.ndarray
    initial_value: float
    mu: float
    sigma: float

    @property
    def final_values(self) -> np.ndarray:
        """Valor final de cada trayectoria."""
        return self.paths[-1]

    def quantile(self, q: float) -> float:
        """Cuantil del valor final (p. ej. 0.05 para el percentil 5)."""
        return float(np.quantile(self.final_values, q))

    @property
    def prob_loss(self) -> float:
        """Probabilidad de terminar por debajo del valor inicial."""
        return float((self.final_values < self.initial_value).mean())


class Portfolio:
    """Cartera de activos con pesos fijos.

    Args:
        series: Series de precios normalizadas (de ``DownloadService``).
        weights: Peso de cada activo, indexado por ``PriceSeries.ticker``.

    Raises:
        InvalidSeriesError: Si las series o los pesos no son válidos.
    """

    def __init__(self, series: list[PriceSeries], weights: dict[str, float]) -> None:
        self.series = {s.ticker: s for s in series}
        self.weights = dict(weights)
        self._validate()
        self.returns = self._aligned_returns()

    def _validate(self) -> None:
        if not self.series:
            raise InvalidSeriesError("Portfolio: se necesita al menos una serie")
        if set(self.series) != set(self.weights):
            raise InvalidSeriesError(
                f"Portfolio: los tickers {sorted(self.series)} no coinciden "
                f"con los pesos {sorted(self.weights)}"
            )
        if any(w < 0 for w in self.weights.values()):
            raise InvalidSeriesError("Portfolio: no se admiten pesos negativos")
        total = sum(self.weights.values())
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            raise InvalidSeriesError(f"Portfolio: los pesos suman {total:.6f}, deben sumar 1")
        frequencies = {s.frequency for s in self.series.values()}
        if len(frequencies) > 1:
            raise InvalidSeriesError("Portfolio: todas las series deben tener la misma frecuencia")

    def _aligned_returns(self) -> pd.DataFrame:
        """Retornos de todos los activos, en las fechas comunes."""
        df = pd.concat(
            {t: s.returns for t, s in self.series.items()}, axis=1, join="inner"
        ).dropna()
        if len(df) < 2:
            raise InvalidSeriesError("Portfolio: menos de 2 fechas comunes entre las series")
        return df

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

        Si no se indican ``mu`` y ``sigma`` (por periodo), se estiman de los datos.
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
        """Simula un único activo de la cartera, partiendo de su último precio."""
        if ticker not in self.series:
            raise InvalidSeriesError(f"Portfolio: el ticker {ticker!r} no está en la cartera")
        s = self.series[ticker]
        mu = s.mean_return if mu is None else mu
        sigma = s.std_return if sigma is None else sigma
        initial = float(s.prices.iloc[-1])
        paths = simulate_gbm(initial, mu, sigma, n_steps, n_simulations, seed)
        return SimulationResult(paths, initial, mu, sigma)