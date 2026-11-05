"""Modelos del dominio: el contrato compartido por todas las capas del toolkit.

Cualquier proveedor (Yahoo, FRED, Alpha Vantage...) debe entregar sus datos en estas
estructuras normalizadas. El resto del sistema (servicios, cartera, Monte Carlo,
reportes) trabaja exclusivamente con ellas, sin conocer el origen de los datos.

Este módulo solo depende de la stdlib, ``pandas`` y ``numpy``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Generic, TypeVar

import numpy as np
import pandas as pd

from toolkit.domain.errors import InvalidRequestError, InvalidSeriesError

#: Columnas estándar de una serie de precios, en orden canónico.
PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "adj_close", "volume")

#: Columnas obligatorias. ``adj_close`` es opcional porque no todas las fuentes la ofrecen.
REQUIRED_PRICE_COLUMNS: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"})


class AssetType(str, Enum):
    """Tipo de activo de una serie de precios."""

    EQUITY = "equity"
    INDEX = "index"
    CRYPTO = "crypto"  # cotiza 24/7: su calendario difiere del bursátil


class Frequency(str, Enum):
    """Frecuencia de muestreo de una serie temporal."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


def _validate_index(index: pd.Index, label: str) -> None:
    """Comprueba que el índice sea un ``DatetimeIndex`` ordenado, único y sin zona horaria.

    Args:
        index: Índice a validar.
        label: Identificador de la serie, usado en los mensajes de error.

    Raises:
        InvalidSeriesError: Si el índice no cumple alguna de las condiciones.
    """
    if not isinstance(index, pd.DatetimeIndex):
        kind = type(index).__name__
        raise InvalidSeriesError(f"{label}: el índice debe ser DatetimeIndex, no {kind}")
    if index.tz is not None:
        raise InvalidSeriesError(f"{label}: el índice debe ser tz-naive (tiene tz={index.tz})")
    if index.has_duplicates:
        raise InvalidSeriesError(f"{label}: el índice contiene fechas duplicadas")
    if not index.is_monotonic_increasing:
        raise InvalidSeriesError(f"{label}: el índice no está ordenado de forma creciente")


def _safe_stat(value: float) -> float:
    """Convierte un estadístico a ``float`` de Python, devolviendo ``nan`` si no es finito."""
    value = float(value)
    return value if math.isfinite(value) else math.nan


@dataclass(frozen=True, eq=False)
class PriceSeries:
    """Serie OHLCV normalizada de un activo (acción o índice).

    El ``DataFrame`` ``data`` se considera inmutable por convención: no lo modifiques
    in-place; crea una nueva ``PriceSeries`` si necesitas transformarlo.

    Esquema de ``data``:
        * Índice ``DatetimeIndex`` ordenado, sin duplicados y tz-naive.
        * Columnas en minúsculas: ``open, high, low, close, volume`` (obligatorias)
          y ``adj_close`` (opcional). No se admiten columnas adicionales.
        * Todas las columnas numéricas; al menos una observación.

    Atributos calculados en ``__post_init__``:
        mean_return: Media de los retornos simples por periodo (sin anualizar).
        std_return: Desviación típica muestral (ddof=1) de esos retornos.

    Los retornos se calculan sobre ``adj_close`` si existe y, si no, sobre ``close``.
    Con menos de dos observaciones ambos estadísticos valen ``nan``.
    """

    ticker: str
    name: str | None
    asset_type: AssetType
    source: str
    currency: str | None
    frequency: Frequency
    data: pd.DataFrame
    mean_return: float = field(init=False)
    std_return: float = field(init=False)

    def __post_init__(self) -> None:
        """Valida el esquema de ``data`` y calcula los estadísticos de retorno."""
        self._validate()
        returns = self.returns
        object.__setattr__(self, "mean_return", _safe_stat(returns.mean()))
        object.__setattr__(self, "std_return", _safe_stat(returns.std(ddof=1)))

    def _validate(self) -> None:
        """Comprueba el esquema de la serie.

        Raises:
            InvalidSeriesError: Si ``data`` no cumple el esquema estándar.
        """
        label = self.ticker or "<sin ticker>"
        if not self.ticker:
            raise InvalidSeriesError("PriceSeries: el ticker no puede estar vacío")
        if not isinstance(self.data, pd.DataFrame):
            raise InvalidSeriesError(f"{label}: data debe ser un pandas.DataFrame")
        if self.data.empty:
            raise InvalidSeriesError(f"{label}: la serie no tiene observaciones")
        columns = set(self.data.columns)
        missing = REQUIRED_PRICE_COLUMNS - columns
        if missing:
            raise InvalidSeriesError(f"{label}: faltan columnas obligatorias {sorted(missing)}")
        unknown = columns - set(PRICE_COLUMNS)
        if unknown:
            raise InvalidSeriesError(f"{label}: columnas no estándar {sorted(unknown)}")
        non_numeric = [
            c for c in self.data.columns if not pd.api.types.is_numeric_dtype(self.data[c])
        ]
        if non_numeric:
            raise InvalidSeriesError(f"{label}: columnas no numéricas {non_numeric}")
        _validate_index(self.data.index, label)

    @property
    def price_column(self) -> str:
        """Columna usada para calcular retornos: ``adj_close`` si existe, si no ``close``."""
        return "adj_close" if "adj_close" in self.data.columns else "close"

    @property
    def prices(self) -> pd.Series:
        """Serie de precios usada para los retornos (``adj_close`` o ``close``)."""
        return self.data[self.price_column]

    @property
    def returns(self) -> pd.Series:
        """Retornos simples por periodo: ``P_t / P_{t-1} - 1`` (sin el primer NaN)."""
        return self.prices.pct_change(fill_method=None).dropna().rename("returns")

    @property
    def log_returns(self) -> pd.Series:
        """Retornos logarítmicos por periodo: ``ln(P_t / P_{t-1})`` (sin el primer NaN)."""
        return np.log(self.prices).diff().dropna().rename("log_returns")

    @property
    def start(self) -> date:
        """Fecha de la primera observación."""
        return self.data.index[0].date()

    @property
    def end(self) -> date:
        """Fecha de la última observación."""
        return self.data.index[-1].date()

    @property
    def n_obs(self) -> int:
        """Número de observaciones (filas) de la serie."""
        return len(self.data)

    def __repr__(self) -> str:
        return (
            f"PriceSeries(ticker={self.ticker!r}, source={self.source!r}, "
            f"asset_type={self.asset_type.value}, frequency={self.frequency.value}, "
            f"n_obs={self.n_obs}, start={self.start}, end={self.end}, "
            f"mean_return={self.mean_return:.6f}, std_return={self.std_return:.6f})"
        )


@dataclass(frozen=True, eq=False)
class MacroSeries:
    """Serie macroeconómica univariante (p. ej. CPI, tipo a 10 años).

    ``data`` es una ``pd.Series`` de valores float (se admiten ``NaN`` para huecos)
    con índice ``DatetimeIndex`` ordenado, único y tz-naive. Se trata como inmutable.

    Si ``vintage`` está informado, la serie refleja los datos tal como se publicaron
    en esa fecha (modo ALFRED), lo que evita el sesgo de anticipación (look-ahead bias).

    Atributos calculados en ``__post_init__``:
        mean: Media de los valores (ignorando ``NaN``).
        std: Desviación típica muestral (ddof=1) de los valores (ignorando ``NaN``).
    """

    series_id: str
    name: str | None
    source: str
    units: str | None
    frequency: Frequency
    data: pd.Series
    vintage: date | None = None
    mean: float = field(init=False)
    std: float = field(init=False)

    def __post_init__(self) -> None:
        """Valida la serie y calcula media y desviación típica."""
        self._validate()
        object.__setattr__(self, "mean", _safe_stat(self.data.mean()))
        object.__setattr__(self, "std", _safe_stat(self.data.std(ddof=1)))

    def _validate(self) -> None:
        """Comprueba el esquema de la serie.

        Raises:
            InvalidSeriesError: Si ``data`` no cumple el esquema estándar.
        """
        label = self.series_id or "<sin id>"
        if not self.series_id:
            raise InvalidSeriesError("MacroSeries: el series_id no puede estar vacío")
        if not isinstance(self.data, pd.Series):
            raise InvalidSeriesError(f"{label}: data debe ser una pandas.Series")
        if self.data.empty:
            raise InvalidSeriesError(f"{label}: la serie no tiene observaciones")
        if not pd.api.types.is_float_dtype(self.data):
            raise InvalidSeriesError(f"{label}: los valores deben ser float, no {self.data.dtype}")
        _validate_index(self.data.index, label)

    @property
    def start(self) -> date:
        """Fecha de la primera observación."""
        return self.data.index[0].date()

    @property
    def end(self) -> date:
        """Fecha de la última observación."""
        return self.data.index[-1].date()

    @property
    def n_obs(self) -> int:
        """Número de observaciones (incluidas las que son ``NaN``)."""
        return len(self.data)

    def __repr__(self) -> str:
        return (
            f"MacroSeries(series_id={self.series_id!r}, source={self.source!r}, "
            f"frequency={self.frequency.value}, n_obs={self.n_obs}, start={self.start}, "
            f"end={self.end}, vintage={self.vintage}, mean={self.mean:.6f}, std={self.std:.6f})"
        )


def _clean_ids(ids: Iterable[str], field_name: str) -> tuple[str, ...]:
    """Limpia identificadores (``strip``) y elimina duplicados conservando el orden.

    No cambia mayúsculas: hay APIs que las distinguen (SEC, CoinGecko...) y otras que no;
    normalizarlas es responsabilidad de cada adaptador.

    Raises:
        InvalidRequestError: Si es un ``str``, está vacía o contiene elementos no válidos.
    """
    if isinstance(ids, str):
        raise InvalidRequestError(f"{field_name} debe ser una lista, no un str")
    cleaned: list[str] = []
    for raw in ids:
        if not isinstance(raw, str) or not raw.strip():
            raise InvalidRequestError(f"{field_name} contiene un identificador inválido: {raw!r}")
        if raw.strip() not in cleaned:
            cleaned.append(raw.strip())
    if not cleaned:
        raise InvalidRequestError(f"{field_name} no puede estar vacío")
    return tuple(cleaned)


def _check_range(start: date | None, end: date | None) -> None:
    """Raises: InvalidRequestError si ``start > end``."""
    if start is not None and end is not None and start > end:
        raise InvalidRequestError(f"start ({start}) no puede ser posterior a end ({end})")


@dataclass(frozen=True)
class DownloadRequest:
    """Petición de descarga de precios para uno o varios tickers (validada al crearla).

    Attributes:
        tickers: Símbolos a descargar (p. ej. ``["AAPL", "^GSPC"]``). Se guardan como
            ``tuple`` limpia (``strip``) y sin duplicados, conservando orden y mayúsculas.
        start: Fecha inicial (incluida). ``None`` deja que el proveedor decida.
        end: Fecha final (incluida). ``None`` = hasta el último dato disponible.
        interval: Frecuencia deseada de las observaciones.
        asset_type: Tipo de activo que se solicita.

    Raises:
        InvalidRequestError: Si los tickers o el rango de fechas no son válidos.
    """

    tickers: Sequence[str]
    start: date | None = None
    end: date | None = None
    interval: Frequency = Frequency.DAILY
    asset_type: AssetType = AssetType.EQUITY

    def __post_init__(self) -> None:
        object.__setattr__(self, "tickers", _clean_ids(self.tickers, "tickers"))
        _check_range(self.start, self.end)


@dataclass(frozen=True)
class MacroRequest:
    """Petición de descarga de series macroeconómicas (validada al crearla).

    Attributes:
        series_ids: Identificadores de las series (p. ej. ``["CPIAUCSL", "DGS10"]``),
            normalizados igual que ``DownloadRequest.tickers``.
        start: Fecha inicial de las observaciones (incluida).
        end: Fecha final de las observaciones (incluida).
        as_of: Si se informa, se piden los datos tal como se conocían ese día (ALFRED).

    Raises:
        InvalidRequestError: Si los ids o el rango de fechas no son válidos.
    """

    series_ids: Sequence[str]
    start: date | None = None
    end: date | None = None
    as_of: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_ids", _clean_ids(self.series_ids, "series_ids"))
        _check_range(self.start, self.end)


T = TypeVar("T")


@dataclass
class DownloadResult(Generic[T]):
    """Resultado de una descarga en lote: series obtenidas y errores por identificador.

    Un fallo individual no invalida el lote: queda registrado en ``errors``.

    Attributes:
        series: Series descargadas, en el orden de la petición original.
        errors: Mensaje de error por identificador fallido.
    """

    series: dict[str, T] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """``True`` si no se ha producido ningún error."""
        return not self.errors

    @property
    def n_success(self) -> int:
        """Número de series descargadas correctamente."""
        return len(self.series)

    @property
    def n_failed(self) -> int:
        """Número de series que han fallado."""
        return len(self.errors)

    @property
    def all_failed(self) -> bool:
        """``True`` si hubo al menos un intento y ninguna serie se descargó."""
        return self.n_success == 0 and self.n_failed > 0
