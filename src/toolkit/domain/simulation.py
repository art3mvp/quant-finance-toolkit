"""Simulación de Monte Carlo (movimiento browniano geométrico)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from toolkit.domain.plotting import PlotRenderer, SimulationPlotData, resolve_renderer

#: Percentiles por defecto para las bandas de las trayectorias.
DEFAULT_BANDS: tuple[float, ...] = (0.05, 0.25, 0.5, 0.75, 0.95)


def _check_positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} debe ser un entero >= 1, recibido {value!r}")


def _check_finite(name: str, value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} debe ser numérico, recibido {value!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} debe ser finito, recibido {value}")
    return value


def simulate_gbm(
    initial_value: float,
    mu: float,
    sigma: float,
    n_steps: int,
    n_simulations: int,
    seed: int | None = None,
) -> np.ndarray:
    """Simula trayectorias de un valor con movimiento browniano geométrico.

    Args:
        initial_value: Valor de partida (> 0 y finito).
        mu: Retorno esperado por periodo (finito).
        sigma: Volatilidad por periodo (finita y >= 0).
        n_steps: Horizonte temporal en periodos (entero >= 1).
        n_simulations: Número de trayectorias (entero >= 1).
        seed: Semilla para reproducibilidad.

    Returns:
        Array de forma ``(n_steps + 1, n_simulations)``; la fila 0 es ``initial_value``.

    Raises:
        ValueError: Si algún parámetro es inválido (NaN, infinito, fuera de rango).
    """
    _check_positive_int("n_steps", n_steps)
    _check_positive_int("n_simulations", n_simulations)
    initial_value = _check_finite("initial_value", initial_value)
    mu = _check_finite("mu", mu)
    sigma = _check_finite("sigma", sigma)
    if initial_value <= 0:
        raise ValueError(f"initial_value debe ser > 0, recibido {initial_value}")
    if sigma < 0:
        raise ValueError(f"sigma debe ser >= 0, recibido {sigma}")

    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_steps, n_simulations))
    log_steps = (mu - 0.5 * sigma**2) + sigma * z
    paths = initial_value * np.exp(np.cumsum(log_steps, axis=0))
    return np.vstack([np.full(n_simulations, initial_value), paths])


def _check_probability(name: str, value: float) -> float:
    value = _check_finite(name, value)
    if not 0.0 < value < 1.0:
        raise ValueError(f"{name} debe estar en (0, 1), recibido {value}")
    return value


@dataclass(frozen=True, eq=False)
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
    def n_steps(self) -> int:
        """Horizonte simulado, en periodos."""
        return self.paths.shape[0] - 1

    @property
    def n_simulations(self) -> int:
        """Número de trayectorias."""
        return self.paths.shape[1]

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

    def var(self, confidence: float = 0.95) -> float:
        """VaR del valor final: pérdida respecto al inicial en el cuantil ``1 - confidence``.

        Positivo significa pérdida; negativo, que incluso ese escenario adverso gana.
        """
        confidence = _check_probability("confidence", confidence)
        return self.initial_value - self.quantile(1.0 - confidence)

    def percentile_bands(self, qs: Sequence[float] = DEFAULT_BANDS) -> pd.DataFrame:
        """Percentiles de las trayectorias en cada paso.

        Returns:
            ``DataFrame`` con índice = paso (0..n_steps) y una columna por cuantil.
        """
        qs = [_check_finite("q", q) for q in qs]
        if not qs or any(not 0.0 <= q <= 1.0 for q in qs):
            raise ValueError(f"los cuantiles deben estar en [0, 1], recibido {qs}")
        bands = np.quantile(self.paths, qs, axis=1).T
        return pd.DataFrame(bands, index=pd.RangeIndex(self.n_steps + 1, name="step"), columns=qs)

    def plot_data(
        self,
        max_paths: int = 50,
        qs: Sequence[float] = DEFAULT_BANDS,
        var_quantile: float = 0.05,
        title: str = "Simulación de Monte Carlo",
    ) -> SimulationPlotData:
        """Datos para dibujar la simulación (muestra de trayectorias, bandas y finales)."""
        _check_positive_int("max_paths", max_paths)
        var_quantile = _check_probability("var_quantile", var_quantile)
        return SimulationPlotData(
            sample_paths=self.paths[:, : min(max_paths, self.n_simulations)],
            bands=self.percentile_bands(qs),
            final_values=self.final_values,
            initial_value=self.initial_value,
            var_quantile=var_quantile,
            var_level=self.quantile(var_quantile),
            title=title,
        )

    def plot(
        self,
        renderer: PlotRenderer | None = None,
        *,
        max_paths: int = 50,
        title: str = "Simulación de Monte Carlo",
    ) -> Any:
        """Muestra las trayectorias simuladas y la distribución del valor final.

        Args:
            renderer: Adaptador que dibuja (p. ej. ``build_plot_renderer()``); por
                defecto, el registrado con ``bootstrap.configure_plotting()``.
            max_paths: Trayectorias individuales que se dibujan (las bandas usan todas).
            title: Título del gráfico.

        Returns:
            Lo que devuelva el renderer (una ``Figure`` con matplotlib).

        Raises:
            ConfigurationError: Si no hay renderer.
        """
        return resolve_renderer(renderer).render_simulation(
            self.plot_data(max_paths=max_paths, title=title)
        )
