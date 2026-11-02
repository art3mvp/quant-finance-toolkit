"""Cartera de activos: pesos, alineación temporal y métricas de riesgo/retorno."""

from __future__ import annotations

import numpy as np
import pandas as pd

from toolkit.domain.errors import InvalidSeriesError
from toolkit.domain.models import PriceSeries

#: Tolerancia para aceptar que los pesos suman 1.
WEIGHT_TOLERANCE = 1e-6


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
        
