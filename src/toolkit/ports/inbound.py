"""Puertos inbound (driving): los casos de uso que el core ofrece al exterior.

Los adaptadores de entrada (CLI, notebooks, una futura API) dependen de este
protocolo, no de la implementación concreta (``DownloadService``).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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

        Un fallo individual no aborta el lote: se registra en ``DownloadResult.errors``.

        Raises:
            InvalidRequestError: Si la petición es inválida (lista vacía, ``start > end``...).
        """
        ...

    def download_macro(self, request: MacroRequest) -> DownloadResult[MacroSeries]:
        """Descarga todas las series macroeconómicas de la petición.

        Un fallo individual no aborta el lote: se registra en ``DownloadResult.errors``.

        Raises:
            InvalidRequestError: Si la petición es inválida.
            ConfigurationError: Si no hay proveedor macro configurado.
        """
        ...
