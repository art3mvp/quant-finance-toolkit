"""Servicio de aplicación: persistencia de las series descargadas.

Implementa el puerto inbound ``StoreSeries`` sobre un ``SeriesRepository`` inyectado.
Así la CLI (o un notebook) guarda resultados sin conocer el destino: ficheros CSV,
Parquet o, en el futuro, una base de datos.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from toolkit.domain.models import MacroSeries, PriceSeries
from toolkit.ports.outbound import SeriesRepository

logger = logging.getLogger(__name__)


class StorageService:
    """Guarda series normalizadas en el repositorio inyectado.

    Args:
        repository: Adaptador que cumple ``SeriesRepository``.

    Raises:
        TypeError: Si ``repository`` no cumple el puerto.
    """

    def __init__(self, repository: SeriesRepository) -> None:
        if not isinstance(repository, SeriesRepository):
            raise TypeError(f"{repository!r} no cumple el puerto SeriesRepository")
        self.repository = repository

    def store(self, series: Mapping[str, PriceSeries | MacroSeries]) -> list[str]:
        """Guarda las series; sin series no toca el repositorio.

        Raises:
            ConfigurationError, ProviderError: Los del repositorio, sin traducir.
        """
        if not series:
            return []
        logger.info("Guardando %d series en %r", len(series), self.repository)
        return self.repository.save(series)
