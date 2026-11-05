"""Repositorio de series en ficheros locales (CSV o Parquet).

Implementa el puerto ``SeriesRepository``: un fichero por serie en ``directory``.

- ``PriceSeries``: las columnas OHLCV tal cual, con índice ``date``.
- ``MacroSeries``: una columna ``value``. Si es un vintage, el nombre lleva el sufijo
  ``_asof_<fecha>`` para no pisar la última revisión.

Los identificadores se convierten en nombres de fichero seguros (``^GSPC`` →
``_GSPC``, ``EXR/D.USD.EUR.SP00.A`` → ``EXR_D.USD.EUR.SP00.A``).
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from toolkit.domain.errors import ConfigurationError, InvalidRequestError, ProviderError
from toolkit.domain.models import MacroSeries, PriceSeries

#: Formatos admitidos.
FORMATS: tuple[str, ...] = ("csv", "parquet")

PARQUET_HINT = 'Parquet requiere pyarrow: pip install -e ".[parquet]" (o usa --format csv)'


def safe_filename(identifier: str) -> str:
    """Convierte un identificador (p. ej. ``^GSPC``) en un nombre de fichero seguro."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", identifier)


class FileSeriesRepository:
    """Guarda cada serie en ``directory`` como ``<id>.<fmt>``.

    Args:
        directory: Directorio de salida; se crea al guardar si no existe.
        fmt: ``"csv"`` o ``"parquet"``.

    Raises:
        InvalidRequestError: Si el formato no está admitido.
        ConfigurationError: Si se pide Parquet sin ``pyarrow`` instalado. Se comprueba
            al construir el repositorio, para fallar antes de descargar nada.
    """

    def __init__(self, directory: str | Path, fmt: str = "csv") -> None:
        fmt = fmt.strip().lower()
        if fmt not in FORMATS:
            raise InvalidRequestError(f"formato {fmt!r} no admitido; usa {', '.join(FORMATS)}")
        if fmt == "parquet" and importlib.util.find_spec("pyarrow") is None:
            raise ConfigurationError(PARQUET_HINT)
        self.directory = Path(directory)
        self.fmt = fmt

    def __repr__(self) -> str:
        return f"FileSeriesRepository({str(self.directory)!r}, fmt={self.fmt!r})"

    def save(self, series: Mapping[str, PriceSeries | MacroSeries]) -> list[str]:
        """Escribe un fichero por serie y devuelve sus rutas.

        Raises:
            ProviderError: Si no se puede crear el directorio o escribir un fichero.
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProviderError(f"no se puede crear {self.directory}: {exc}") from exc
        return [str(self._save_one(identifier, s)) for identifier, s in series.items()]

    def path_for(self, identifier: str, series: PriceSeries | MacroSeries) -> Path:
        """Ruta donde se guarda (o se guardaría) ``series``."""
        stem = safe_filename(identifier)
        if isinstance(series, MacroSeries) and series.vintage is not None:
            stem += f"_asof_{series.vintage.isoformat()}"
        return self.directory / f"{stem}.{self.fmt}"

    def _save_one(self, identifier: str, series: PriceSeries | MacroSeries) -> Path:
        frame = series.data if isinstance(series, PriceSeries) else series.data.to_frame("value")
        path = self.path_for(identifier, series)
        try:
            self._write(frame, path)
        except OSError as exc:
            raise ProviderError(f"no se puede escribir {path}: {exc}") from exc
        return path

    def _write(self, frame: pd.DataFrame, path: Path) -> None:
        if self.fmt == "csv":
            frame.to_csv(path, index_label="date")
            return
        try:
            frame.to_parquet(path)
        except ImportError as exc:
            raise ConfigurationError(PARQUET_HINT) from exc
