"""Cartera de activos. **STUB**: lo implementa la Persona B en la siguiente fase.

Contrato acordado
-----------------
Constructor esperado::

    Portfolio(series: list[PriceSeries], weights: dict[str, float])

* ``series``: series de precios normalizadas (ver ``toolkit.domain.models.PriceSeries``),
  obtenidas a través de ``DownloadService``.
* ``weights``: peso de cada activo, indexado por ``PriceSeries.ticker``.

Funcionalidad prevista (fuera del alcance de la Fase 0/1):
    * Validación de pesos y alineación temporal de las series.
    * Retorno y volatilidad de la cartera, matriz de covarianzas.
    * Simulación Monte Carlo de la evolución de la cartera.
    * ``.report()`` (informe en markdown) y ``.plots_report()`` (gráficos con matplotlib).

Debe permanecer en la capa de dominio: solo puede depender de la stdlib, ``pandas``,
``numpy`` y del resto de ``toolkit.domain``.
"""

from __future__ import annotations

from toolkit.domain.models import PriceSeries


class Portfolio:
    """Cartera de activos (pendiente de implementación por la Persona B)."""

    def __init__(self, series: list[PriceSeries], weights: dict[str, float]) -> None:
        """Crea la cartera a partir de series de precios y pesos por ticker.

        Raises:
            NotImplementedError: Siempre, hasta que se implemente en la siguiente fase.
        """
        raise NotImplementedError("Portfolio se implementará en la fase de modelado (Persona B)")
