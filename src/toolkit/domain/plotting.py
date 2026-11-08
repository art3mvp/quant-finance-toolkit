"""Contrato de visualización: el dominio prepara los datos, un adaptador los dibuja.

``Portfolio.plots_report()`` y ``SimulationResult.plot()`` son métodos del dominio, pero
el dominio no depende de ninguna librería gráfica. Cada método:

1. Calcula **qué** hay que mostrar (``PortfolioPlotData`` / ``SimulationPlotData``: solo
   ``pandas`` y ``numpy``).
2. Delega el **cómo** en un ``PlotRenderer`` inyectado, que vive en
   ``toolkit.adapters.outbound.plotting`` (p. ej. ``MatplotlibPlotRenderer``).

El protocolo se define aquí, y no en ``toolkit.ports.outbound``, porque el dominio no
puede importar los puertos (regla de dependencias). Es una interfaz **requerida** por el
núcleo; ``ports.outbound`` la reexporta para que los adaptadores la usen igual que el
resto de puertos.

El renderer se pasa en cada llamada o se registra una vez como predeterminado con
``set_default_renderer`` (lo hace ``bootstrap.configure_plotting()``). Ese registro es
el único estado global del dominio: afecta a todo el proceso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from toolkit.domain.errors import ConfigurationError


@dataclass(frozen=True, eq=False)
class PortfolioPlotData:
    """Datos de los gráficos de una cartera, listos para dibujar.

    Attributes:
        performance: Evolución base ``base`` de cada activo y de la cartera
            (columna ``"cartera"``), en las fechas alineadas.
        value: Valor de la cartera (base ``base``) en cada fecha.
        drawdown: Caída desde el máximo previo de la cartera (``<= 0``).
        correlation: Matriz de correlación de los retornos alineados.
        weights: Peso de cada activo.
        risk_return: Retorno y volatilidad anualizados por activo y de la cartera
            (columnas ``"retorno"`` y ``"volatilidad"``).
        title: Título del conjunto de gráficos.
    """

    performance: pd.DataFrame
    value: pd.Series
    drawdown: pd.Series
    correlation: pd.DataFrame
    weights: pd.Series
    risk_return: pd.DataFrame
    title: str


@dataclass(frozen=True, eq=False)
class SimulationPlotData:
    """Datos de los gráficos de una simulación de Monte Carlo.

    Attributes:
        sample_paths: Muestra de trayectorias ``(n_steps + 1, k)`` para dibujar.
        bands: Percentiles por paso (índice = paso, columnas = cuantiles).
        final_values: Valor final de todas las trayectorias.
        initial_value: Valor de partida.
        var_quantile: Cuantil del valor final marcado como VaR (p. ej. el percentil 5).
        var_level: Valor final en ese cuantil.
        title: Título del conjunto de gráficos.
    """

    sample_paths: np.ndarray
    bands: pd.DataFrame
    final_values: np.ndarray
    initial_value: float
    var_quantile: float
    var_level: float
    title: str


@runtime_checkable
class PlotRenderer(Protocol):
    """Dibuja los datos de gráficos del dominio. Devuelve lo que use su librería
    (p. ej. una ``matplotlib.figure.Figure``)."""

    def render_portfolio(self, data: PortfolioPlotData) -> Any:
        """Dibuja el informe visual de una cartera."""
        ...

    def render_simulation(self, data: SimulationPlotData) -> Any:
        """Dibuja trayectorias y distribución final de una simulación."""
        ...


_default_renderer: PlotRenderer | None = None


def set_default_renderer(renderer: PlotRenderer | None) -> None:
    """Registra el renderer que se usa cuando no se pasa ninguno (``None`` lo borra).

    Raises:
        ConfigurationError: Si ``renderer`` no cumple ``PlotRenderer``.
    """
    global _default_renderer
    if renderer is not None and not isinstance(renderer, PlotRenderer):
        raise ConfigurationError(f"{type(renderer).__name__} no cumple el protocolo PlotRenderer")
    _default_renderer = renderer


def get_default_renderer() -> PlotRenderer | None:
    """Renderer registrado como predeterminado, o ``None``."""
    return _default_renderer


def resolve_renderer(renderer: PlotRenderer | None) -> PlotRenderer:
    """Devuelve ``renderer`` o, si es ``None``, el predeterminado.

    Raises:
        ConfigurationError: Si no hay ninguno o no cumple ``PlotRenderer``.
    """
    chosen = renderer if renderer is not None else _default_renderer
    if chosen is None:
        raise ConfigurationError(
            "No hay renderer de gráficos: pasa renderer=build_plot_renderer() o llama "
            "antes a toolkit.bootstrap.configure_plotting()"
        )
    if not isinstance(chosen, PlotRenderer):
        raise ConfigurationError(f"{type(chosen).__name__} no cumple el protocolo PlotRenderer")
    return chosen
