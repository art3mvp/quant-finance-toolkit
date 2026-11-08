"""Renderer de gráficos con matplotlib: implementa el puerto ``PlotRenderer``.

Construye las figuras con la API orientada a objetos (``matplotlib.figure.Figure``), sin
el estado global de ``pyplot``:

* En Jupyter, la ``Figure`` devuelta se muestra una sola vez como resultado de la celda.
* En un script, guárdala con ``fig.savefig("informe.png")``.
* No abre ventanas ni bloquea, así que funciona igual en tests y servidores.
"""

from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure

from toolkit.domain.plotting import PortfolioPlotData, SimulationPlotData

#: Color de la cartera en los gráficos comparativos.
PORTFOLIO_COLOR = "black"


class MatplotlibPlotRenderer:
    """Dibuja los informes visuales del dominio con matplotlib.

    Args:
        portfolio_figsize: Tamaño (pulgadas) de la figura de la cartera.
        simulation_figsize: Tamaño (pulgadas) de la figura de la simulación.
        cmap: Mapa de color de la matriz de correlación (divergente, de -1 a 1).
    """

    name = "matplotlib"

    def __init__(
        self,
        portfolio_figsize: tuple[float, float] = (16, 9),
        simulation_figsize: tuple[float, float] = (14, 4.5),
        cmap: str = "RdBu_r",
    ) -> None:
        self.portfolio_figsize = portfolio_figsize
        self.simulation_figsize = simulation_figsize
        self.cmap = cmap

    # --- Cartera ------------------------------------------------------------------

    def render_portfolio(self, data: PortfolioPlotData) -> Figure:
        """Figura 2×3: rendimiento comparado, valor, drawdown, correlación, pesos y
        riesgo/retorno."""
        fig = Figure(figsize=self.portfolio_figsize, layout="constrained")
        axes = fig.subplots(2, 3)
        fig.suptitle(data.title, fontsize=14, fontweight="bold")
        self._performance(axes[0, 0], data)
        self._value(axes[0, 1], data)
        self._drawdown(axes[0, 2], data)
        self._correlation(fig, axes[1, 0], data)
        self._weights(axes[1, 1], data)
        self._risk_return(axes[1, 2], data)
        return fig

    @staticmethod
    def _performance(ax, data: PortfolioPlotData) -> None:
        for column in data.performance.columns:
            is_portfolio = column == "cartera"
            ax.plot(
                data.performance.index,
                data.performance[column],
                label=column,
                linewidth=2.2 if is_portfolio else 1.0,
                color=PORTFOLIO_COLOR if is_portfolio else None,
                alpha=1.0 if is_portfolio else 0.8,
            )
        ax.axhline(100, color="grey", linewidth=0.8, linestyle=":")
        ax.set(title="Rendimiento comparado (base 100)", ylabel="valor")
        ax.legend(fontsize=8)
        ax.tick_params(axis="x", labelrotation=30)

    @staticmethod
    def _value(ax, data: PortfolioPlotData) -> None:
        ax.plot(data.value.index, data.value, color=PORTFOLIO_COLOR, linewidth=1.5)
        ax.fill_between(data.value.index, data.value, data.value.iloc[0], alpha=0.15)
        ax.set(title="Evolución del valor de la cartera", ylabel="valor")
        ax.tick_params(axis="x", labelrotation=30)

    @staticmethod
    def _drawdown(ax, data: PortfolioPlotData) -> None:
        dd = data.drawdown * 100
        ax.fill_between(dd.index, dd, 0, color="tab:red", alpha=0.4)
        ax.plot(dd.index, dd, color="tab:red", linewidth=0.8)
        ax.set(title=f"Drawdown (máximo {dd.min():.1f} %)", ylabel="%")
        ax.tick_params(axis="x", labelrotation=30)

    def _correlation(self, fig: Figure, ax, data: PortfolioPlotData) -> None:
        corr = data.correlation
        image = ax.imshow(corr.to_numpy(), cmap=self.cmap, vmin=-1, vmax=1)
        labels = list(corr.columns)
        ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
        ax.set_yticks(range(len(labels)), labels)
        for i in range(len(labels)):
            for j in range(len(labels)):
                value = corr.iloc[i, j]
                ax.text(
                    j,
                    i,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white" if abs(value) > 0.6 else "black",
                )
        ax.set_title("Matriz de correlación")
        fig.colorbar(image, ax=ax, shrink=0.8)

    @staticmethod
    def _weights(ax, data: PortfolioPlotData) -> None:
        weights = data.weights.sort_values()
        ax.barh(weights.index, weights * 100, color="tab:blue")
        for y, value in enumerate(weights * 100):
            ax.text(value, y, f" {value:.1f} %", va="center", fontsize=8)
        ax.set(title="Pesos", xlabel="%")
        ax.set_xlim(0, max(100.0, float(weights.max() * 100) * 1.15))

    @staticmethod
    def _risk_return(ax, data: PortfolioPlotData) -> None:
        rr = data.risk_return * 100
        for name, row in rr.iterrows():
            is_portfolio = name == "cartera"
            ax.scatter(
                row["volatilidad"],
                row["retorno"],
                s=120 if is_portfolio else 50,
                color=PORTFOLIO_COLOR if is_portfolio else "tab:blue",
                marker="*" if is_portfolio else "o",
                zorder=3,
            )
            ax.annotate(
                str(name),
                (row["volatilidad"], row["retorno"]),
                textcoords="offset points",
                xytext=(5, 5),
                fontsize=8,
            )
        ax.axhline(0, color="grey", linewidth=0.8, linestyle=":")
        ax.set(title="Riesgo / retorno anualizados", xlabel="volatilidad (%)", ylabel="retorno (%)")

    # --- Simulación ---------------------------------------------------------------

    def render_simulation(self, data: SimulationPlotData) -> Figure:
        """Figura 1×2: trayectorias con bandas de percentiles y distribución final."""
        fig = Figure(figsize=self.simulation_figsize, layout="constrained")
        ax_paths, ax_hist = fig.subplots(1, 2)
        fig.suptitle(data.title, fontsize=13, fontweight="bold")

        steps = np.asarray(data.bands.index)
        ax_paths.plot(steps, data.sample_paths, color="grey", alpha=0.15, linewidth=0.7)
        qs = sorted(data.bands.columns)
        if len(qs) >= 2:
            lo, hi = qs[0], qs[-1]
            ax_paths.fill_between(
                steps,
                data.bands[lo],
                data.bands[hi],
                alpha=0.2,
                label=f"P{lo:.0%}–P{hi:.0%}".replace("%", ""),
            )
        if len(qs) >= 4:
            lo, hi = qs[1], qs[-2]
            ax_paths.fill_between(
                steps,
                data.bands[lo],
                data.bands[hi],
                alpha=0.35,
                label=f"P{lo:.0%}–P{hi:.0%}".replace("%", ""),
            )
        median = min(qs, key=lambda q: abs(q - 0.5))
        ax_paths.plot(steps, data.bands[median], linewidth=2, label="mediana")
        ax_paths.axhline(data.initial_value, color="black", linestyle="--", linewidth=0.8)
        ax_paths.set(title="Trayectorias simuladas", xlabel="periodos", ylabel="valor")
        ax_paths.legend(fontsize=8)

        ax_hist.hist(data.final_values, bins=60, color="tab:blue", alpha=0.8)
        ax_hist.axvline(data.initial_value, color="black", linestyle="--", label="valor inicial")
        ax_hist.axvline(
            data.var_level,
            color="tab:red",
            label=f"P{data.var_quantile * 100:.0f} = {data.var_level:.1f}",
        )
        ax_hist.set(title="Distribución del valor final", xlabel="valor", ylabel="frecuencia")
        ax_hist.legend(fontsize=8)
        return fig
