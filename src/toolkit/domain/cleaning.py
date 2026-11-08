"""Limpieza y alineación temporal de series de precios.

Activos con calendarios distintos (una cripto cotiza 24/7, la bolsa de EE. UU. y la
española tienen festivos diferentes) no comparten todas las fechas. Para combinarlos en
una cartera hay que **alinear los precios antes de calcular retornos**: si se calculan
los retornos de cada serie por separado y luego se cruzan por fecha, el retorno de un
mismo día abarca intervalos distintos en cada activo (el lunes de AAPL es viernes→lunes;
el de BTC, domingo→lunes) y los movimientos de los días descartados se pierden.

Métodos de alineación:

* ``"inner"`` (por defecto): solo las fechas en las que **todos** los activos tienen
  precio. Cada retorno resultante cubre el mismo intervalo en todos los activos.
* ``"ffill"``: calendario unión, rellenando hacia delante como mucho ``ffill_limit``
  periodos seguidos. Conserva más fechas, pero cada relleno introduce un retorno 0
  artificial que **sesga a la baja** la volatilidad y la correlación. Nunca rellena
  hacia atrás (sería *look-ahead*) ni fuera del rango común de las series.

Los precios no finitos (``NaN``, ``inf``) se descartan y se contabilizan; un precio
``<= 0`` se rechaza porque produciría retornos infinitos.

Este módulo solo depende de ``pandas`` y ``numpy``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from toolkit.domain.errors import InvalidRequestError, InvalidSeriesError

AlignMethod = Literal["inner", "ffill"]

#: Métodos de alineación admitidos.
ALIGN_METHODS: tuple[str, ...] = ("inner", "ffill")


@dataclass(frozen=True, eq=False)
class AlignmentReport:
    """Diagnóstico de una alineación: qué se ha descartado o rellenado y por qué.

    Attributes:
        method: Método usado (``"inner"`` o ``"ffill"``).
        ffill_limit: Máximo de periodos seguidos rellenados (solo ``"ffill"``).
        n_union: Fechas en la unión de todos los calendarios (tras limpiar NaNs).
        n_kept: Fechas conservadas tras alinear.
        dropped_dates: Fechas de la unión que no se han conservado.
        missing_by_ticker: Fechas de la unión en las que cada activo no tenía precio.
        nan_dropped_by_ticker: Precios no finitos eliminados de cada activo.
        filled_by_ticker: Precios rellenados hacia delante en cada activo.
    """

    method: str
    ffill_limit: int | None
    n_union: int
    n_kept: int
    dropped_dates: pd.DatetimeIndex
    missing_by_ticker: dict[str, int]
    nan_dropped_by_ticker: dict[str, int]
    filled_by_ticker: dict[str, int]

    @property
    def n_dropped(self) -> int:
        """Número de fechas de la unión descartadas."""
        return len(self.dropped_dates)

    @property
    def dropped_ratio(self) -> float:
        """Proporción de fechas de la unión descartadas (0 si la unión está vacía)."""
        return self.n_dropped / self.n_union if self.n_union else 0.0


@dataclass(frozen=True, eq=False)
class AlignedPrices:
    """Precios alineados en un calendario común y su diagnóstico.

    Attributes:
        prices: ``DataFrame`` con una columna por activo, sin ``NaN``.
        report: Qué se ha descartado o rellenado al alinear.
    """

    prices: pd.DataFrame
    report: AlignmentReport

    @property
    def returns(self) -> pd.DataFrame:
        """Retornos simples sobre los precios ya alineados (sin la primera fila)."""
        return self.prices.pct_change(fill_method=None).iloc[1:]


def _validate_args(prices: Mapping[str, pd.Series], method: str, ffill_limit: int | None) -> None:
    if not prices:
        raise InvalidRequestError("align_prices: se necesita al menos una serie")
    if method not in ALIGN_METHODS:
        raise InvalidRequestError(f"align_prices: método {method!r} no válido; usa {ALIGN_METHODS}")
    if ffill_limit is not None and (
        isinstance(ffill_limit, bool)
        or not isinstance(ffill_limit, (int, np.integer))
        or ffill_limit < 1
    ):
        raise InvalidRequestError(
            f"align_prices: ffill_limit debe ser None o >= 1: {ffill_limit!r}"
        )


def _clean_series(ticker: str, series: pd.Series) -> tuple[pd.Series, int]:
    """Valida una serie de precios y elimina sus valores no finitos."""
    if not isinstance(series, pd.Series):
        raise InvalidSeriesError(f"{ticker}: los precios deben ser una pandas.Series")
    if not isinstance(series.index, pd.DatetimeIndex):
        raise InvalidSeriesError(f"{ticker}: el índice debe ser DatetimeIndex")
    if not pd.api.types.is_numeric_dtype(series):
        raise InvalidSeriesError(f"{ticker}: los precios deben ser numéricos")
    values = series.astype(float)
    finite = np.isfinite(values.to_numpy())
    clean = values[finite]
    if (clean <= 0).any():
        raise InvalidSeriesError(f"{ticker}: hay precios <= 0, que darían retornos infinitos")
    return clean, int((~finite).sum())


def align_prices(
    prices: Mapping[str, pd.Series],
    method: AlignMethod = "inner",
    ffill_limit: int | None = 5,
) -> AlignedPrices:
    """Limpia y alinea varias series de precios en un calendario común.

    Args:
        prices: Precios por ticker (p. ej. ``{s.ticker: s.prices for s in series}``).
        method: ``"inner"`` (fechas comunes) o ``"ffill"`` (unión con relleno limitado).
        ffill_limit: Máximo de periodos seguidos a rellenar con ``"ffill"``; ``None``
            sin límite. Se ignora con ``"inner"``.

    Returns:
        ``AlignedPrices`` con los precios alineados (puede quedar vacío si no hay
        fechas comunes; quien lo use decide cuántas necesita) y su diagnóstico.

    Raises:
        InvalidRequestError: Si los argumentos no son válidos.
        InvalidSeriesError: Si una serie no es numérica, no tiene índice temporal o
            contiene precios ``<= 0``.
    """
    _validate_args(prices, method, ffill_limit)

    cleaned: dict[str, pd.Series] = {}
    nan_dropped: dict[str, int] = {}
    for ticker, series in prices.items():
        cleaned[ticker], nan_dropped[ticker] = _clean_series(ticker, series)

    union = pd.concat(cleaned, axis=1, join="outer", sort=True)
    missing = {t: int(union[t].isna().sum()) for t in union.columns}
    filled = dict.fromkeys(union.columns, 0)

    if method == "inner":
        aligned = union.dropna(how="any")
    else:
        # Solo el tramo en el que todas las series tienen historia: ni back-fill ni
        # extrapolación más allá del último precio de cada una.
        if any(s.empty for s in cleaned.values()):
            window = union.iloc[0:0]
        else:
            start = max(s.index.min() for s in cleaned.values())
            end = min(s.index.max() for s in cleaned.values())
            window = union.loc[start:end]
        limit = None if ffill_limit is None else int(ffill_limit)
        filled_window = window.ffill(limit=limit)
        filled = {
            t: int((window[t].isna() & filled_window[t].notna()).sum()) for t in union.columns
        }
        aligned = filled_window.dropna(how="any")

    report = AlignmentReport(
        method=method,
        ffill_limit=ffill_limit if method == "ffill" else None,
        n_union=len(union),
        n_kept=len(aligned),
        dropped_dates=pd.DatetimeIndex(union.index.difference(aligned.index)),
        missing_by_ticker=missing,
        nan_dropped_by_ticker=nan_dropped,
        filled_by_ticker=filled,
    )
    return AlignedPrices(prices=aligned, report=report)
