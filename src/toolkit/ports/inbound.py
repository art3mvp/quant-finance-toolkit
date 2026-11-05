"""Puertos inbound (driving): los casos de uso que el core ofrece al exterior.

Los adaptadores de entrada (CLI, notebooks, una futura API) dependen de este
protocolo, no de la implementación concreta (``DownloadService``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from toolkit.domain.documents import DocumentRequest, RegulatoryDocument
from toolkit.domain.models import (
    DownloadRequest,
    DownloadResult,
    MacroRequest,
    MacroSeries,
    PriceSeries,
)


@runtime_checkable
class DownloadData(Protocol):
    """Caso de uso: descarga en lote de series de precios y macroeconómicas."""

    def download_prices(self, request: DownloadRequest) -> DownloadResult[PriceSeries]:
        """Descarga las series de precios de todos los tickers de la petición.

        La petición ya llega validada (``DownloadRequest.__post_init__``). Un fallo
        individual no aborta el lote: se registra en ``DownloadResult.errors``.

        Raises:
            ConfigurationError: Si no hay proveedor de precios o falta su configuración.
        """
        ...

    def download_macro(self, request: MacroRequest) -> DownloadResult[MacroSeries]:
        """Descarga todas las series macroeconómicas de la petición.

        Un fallo individual no aborta el lote: se registra en ``DownloadResult.errors``.

        Raises:
            ConfigurationError: Si no hay proveedor macro configurado.
        """
        ...


@runtime_checkable
class ListDocuments(Protocol):
    """Caso de uso: listar documentos regulatorios de una fuente."""

    def list_documents(self, request: DocumentRequest) -> list[RegulatoryDocument]:
        """Devuelve como mucho ``request.limit`` documentos, del más reciente al más antiguo.

        Raises:
            ConfigurationError: Si la fuente no está bien configurada.
            ProviderError: Si la fuente falla (red, formato...).
        """
        ...
