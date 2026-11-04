"""Normalización OHLCV común a los adaptadores de precios basados en REST.

No es un adaptador: deja un ``DataFrame`` con el esquema de ``PriceSeries`` (índice
tz-naive ordenado y único, columnas ``open, high, low, close, volume`` en float y
``adj_close`` si la fuente la ofrece).
"""

from __future__ import annotations

import math

import pandas as pd

from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import PRICE_COLUMNS, REQUIRED_PRICE_COLUMNS


def normalize_ohlcv(frame: pd.DataFrame, source: str, identifier: str) -> pd.DataFrame:
    """Convierte ``frame`` (índice de fechas, columnas OHLCV) al esquema estándar.

    * Columnas obligatorias ausentes (p. ej. ``volume`` en índices) se crean a ``NaN``;
      ``adj_close`` se conserva solo si viene en ``frame``.
    * Valores no numéricos → ``ProviderError``; filas sin ``close`` se descartan.
    * Índice tz-naive normalizado a medianoche, ordenado y sin duplicados (último gana).

    Raises:
        ProviderError: Si los valores o fechas no son interpretables.
        SeriesNotFoundError: Si no queda ninguna fila válida.
    """
    columns = [c for c in PRICE_COLUMNS if c in REQUIRED_PRICE_COLUMNS or c in frame]
    try:
        data = pd.DataFrame(
            {
                c: pd.to_numeric(frame[c], errors="raise") if c in frame else math.nan
                for c in columns
            },
            index=frame.index,
        ).astype(float)
        index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    except (ValueError, TypeError) as exc:
        raise ProviderError(f"{source}: {identifier}: formato de precios inválido: {exc}") from exc
    if index.tz is not None:
        index = index.tz_localize(None)
    data.index = index.normalize().rename("date")
    data = data.sort_index()
    data = data[~data.index.duplicated(keep="last")].dropna(subset=["close"])
    if data.empty:
        raise SeriesNotFoundError(f"{source}: {identifier}: sin precios válidos")
    return data
