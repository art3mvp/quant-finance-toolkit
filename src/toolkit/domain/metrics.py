"""Métricas de riesgo y retorno sobre series de retornos simples por periodo.

Funciones puras (sin estado) que usan ``Portfolio`` y el informe Markdown. Convenciones:

* Los retornos son **simples** y **por periodo** (no anualizados).
* ``ppy`` = periodos por año (252 sesiones, 52 semanas, 12 meses...).
* El VaR y el CVaR son **históricos** y se expresan como **pérdida positiva**
  (``0.02`` = perder un 2 % en un periodo).
* El drawdown es negativo o cero (``-0.25`` = 25 % por debajo del máximo previo).

Este módulo solo depende de ``pandas`` y ``numpy``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

from toolkit.domain.errors import InvalidRequestError
from toolkit.domain.models import AssetType, Frequency

#: Periodos por año de cada frecuencia (calendario bursátil).
PERIODS_PER_YEAR: dict[Frequency, int] = {
    Frequency.DAILY: 252,
    Frequency.WEEKLY: 52,
    Frequency.MONTHLY: 12,
    Frequency.QUARTERLY: 4,
    Frequency.ANNUAL: 1,
}

#: Días por año de los criptoactivos, que cotizan todos los días.
CRYPTO_DAYS_PER_YEAR = 365


def check_periods_per_year(ppy: int) -> int:
    if isinstance(ppy, bool) or not isinstance(ppy, (int, np.integer)) or ppy < 1:
        raise InvalidRequestError(f"periods_per_year debe ser un entero >= 1, recibido {ppy!r}")
    return int(ppy)


def check_confidence(confidence: float) -> float:
    if not isinstance(confidence, (int, float, np.floating)) or not 0.0 < confidence < 1.0:
        raise InvalidRequestError(f"confidence debe estar en (0, 1), recibido {confidence!r}")
    return float(confidence)


def periods_per_year(frequency: Frequency, asset_types: Iterable[AssetType] = ()) -> int:
    """Periodos por año para anualizar, deducidos solo de la frecuencia y los tipos.

    Con frecuencia diaria y **todos** los activos cripto se usan 365 días; en otro caso,
    252 sesiones. Es una heurística: si el calendario real de los datos se conoce (p. ej.
    una cartera alineada con ``ffill`` que conserva fines de semana), usa
    ``Portfolio.periods_per_year``, que lo mira en las fechas.
    """
    types = set(asset_types)
    if frequency is Frequency.DAILY and types and types == {AssetType.CRYPTO}:
        return CRYPTO_DAYS_PER_YEAR
    return PERIODS_PER_YEAR[frequency]


def annualized_return(returns: pd.Series, ppy: int) -> float:
    """Retorno anualizado geométrico (CAGR): ``(Π(1 + r))^(ppy / n) - 1``."""
    ppy = check_periods_per_year(ppy)
    r = returns.dropna()
    if r.empty:
        return math.nan
    growth = float((1.0 + r).prod())
    if growth <= 0:
        return -1.0
    return growth ** (ppy / len(r)) - 1.0


def annualized_volatility(returns: pd.Series, ppy: int) -> float:
    """Volatilidad anualizada: desviación típica muestral × ``√ppy``."""
    ppy = check_periods_per_year(ppy)
    return float(returns.dropna().std(ddof=1) * math.sqrt(ppy))


def sharpe_ratio(returns: pd.Series, ppy: int, risk_free: float = 0.0) -> float:
    """Ratio de Sharpe anualizado.

    Args:
        returns: Retornos por periodo.
        ppy: Periodos por año.
        risk_free: Tipo libre de riesgo **anual** (p. ej. ``0.03``); se convierte a
            tipo por periodo como ``(1 + rf)^(1/ppy) - 1``.

    Returns:
        ``mean(r - rf) / std(r) × √ppy``; ``nan`` si la volatilidad es 0.
    """
    ppy = check_periods_per_year(ppy)
    if not math.isfinite(risk_free) or risk_free <= -1:
        raise InvalidRequestError(f"risk_free debe ser finito y > -1, recibido {risk_free!r}")
    r = returns.dropna()
    rf_period = (1.0 + risk_free) ** (1.0 / ppy) - 1.0
    std = float(r.std(ddof=1))
    if not std or not math.isfinite(std):
        return math.nan
    return float((r.mean() - rf_period) / std * math.sqrt(ppy))


def wealth_index(returns: pd.Series, base: float = 100.0) -> pd.Series:
    """Valor de ``base`` invertido al inicio, tras cada periodo.

    El índice coincide con el de ``returns``: el primer valor ya incluye el primer
    retorno (el punto de partida, ``base``, es anterior y no se incluye).
    """
    return base * (1.0 + returns.fillna(0.0)).cumprod()


def drawdown(returns: pd.Series) -> pd.Series:
    """Caída desde el máximo previo de la riqueza acumulada (valores ``<= 0``)."""
    wealth = wealth_index(returns, base=1.0)
    peak = np.maximum(wealth.cummax(), 1.0)  # el capital inicial cuenta como máximo
    return (wealth / peak - 1.0).rename("drawdown")


def max_drawdown(returns: pd.Series) -> float:
    """Peor drawdown del periodo (negativo, o 0 si nunca cae)."""
    dd = drawdown(returns)
    return float(dd.min()) if not dd.empty else math.nan


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """VaR histórico por periodo, como pérdida positiva: ``-quantile(1 - confidence)``."""
    confidence = check_confidence(confidence)
    r = returns.dropna()
    return float(-r.quantile(1.0 - confidence)) if not r.empty else math.nan


def historical_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """CVaR (Expected Shortfall) histórico: pérdida media en la cola más allá del VaR."""
    confidence = check_confidence(confidence)
    r = returns.dropna()
    if r.empty:
        return math.nan
    tail = r[r <= r.quantile(1.0 - confidence)]
    return float(-tail.mean())
