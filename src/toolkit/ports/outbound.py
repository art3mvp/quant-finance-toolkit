"""Puertos outbound (driven): lo que el core necesita del exterior.

Cada fuente de datos (Yahoo, FRED, Alpha Vantage...) es un adaptador
que satisface estructuralmente uno de estos protocolos. No es necesario heredar de
ellos: basta con exponer los mismos atributos y métodos (tipado estructural, PEP 544).

Se usa ``typing.Protocol`` con ``@runtime_checkable`` para que ``DownloadService`` pueda
comprobar con ``isinstance`` que un adaptador cumple el contrato. Ver ADR 0001.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from toolkit.domain.documents import RegulatoryDocument
from toolkit.domain.models import AssetType, Frequency, MacroSeries, PriceSeries


@runtime_checkable
class PriceProvider(Protocol):
    """Proveedor de series de precios OHLCV (acciones, índices...)."""

    #: Nombre corto de la fuente (p. ej. ``"yahoo"``); se guarda en ``PriceSeries.source``.
    name: str

    def fetch_prices(
        self,
        ticker: str,
        start: date | None,
        end: date | None,
        interval: Frequency,
        asset_type: AssetType,
    ) -> PriceSeries:
        """Descarga y normaliza la serie de precios de un ticker.

        Args:
            ticker: Símbolo en la nomenclatura del proveedor (p. ej. ``"AAPL"``, ``"^GSPC"``).
            start: Fecha inicial incluida, o ``None`` para el inicio disponible.
            end: Fecha final incluida, o ``None`` para el último dato disponible.
            interval: Frecuencia solicitada.
            asset_type: Tipo de activo que se solicita.

        Returns:
            La serie normalizada según el esquema de ``PriceSeries``.

        Raises:
            SeriesNotFoundError: Si no hay datos para ese ticker o rango.
            ProviderError: Ante cualquier otro fallo del proveedor.
        """
        ...


@runtime_checkable
class MacroProvider(Protocol):
    """Proveedor de series macroeconómicas univariantes."""

    #: Nombre corto de la fuente (p. ej. ``"fred"``); se guarda en ``MacroSeries.source``.
    name: str

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga y normaliza una serie macroeconómica.

        Args:
            series_id: Identificador de la serie en el proveedor (p. ej. ``"CPIAUCSL"``).
            start: Fecha inicial de las observaciones.
            end: Fecha final de las observaciones.
            as_of: Si se informa, devuelve los datos tal como se publicaron ese día
                (vintage). Si es ``None``, devuelve la última revisión disponible.

        Returns:
            La serie normalizada según el esquema de ``MacroSeries``.

        Raises:
            SeriesNotFoundError: Si la serie no existe o no tiene datos en el rango.
            ConfigurationError: Si falta configuración necesaria (p. ej. API key).
            ProviderError: Ante cualquier otro fallo del proveedor.
        """
        ...


@runtime_checkable
class DocumentProvider(Protocol):
    """Proveedor de documentos regulatorios (hechos relevantes, ficheros de registros)."""

    #: Nombre corto de la fuente (p. ej. ``"cnmv"``); se guarda en ``RegulatoryDocument.source``.
    name: str

    def fetch_documents(
        self,
        query: str | None,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[RegulatoryDocument]:
        """Descarga documentos, del más reciente al más antiguo.

        Args:
            query: Filtro propio de la fuente (emisor, tipo de fichero...) o ``None``.
            start: Fecha mínima de publicación (incluida).
            end: Fecha máxima de publicación (incluida).
            limit: Número máximo de documentos a devolver (>= 1).

        Returns:
            Documentos normalizados; lista vacía si ninguno cumple el filtro.

        Raises:
            ConfigurationError: Si falta configuración necesaria.
            ProviderError: Ante cualquier fallo del proveedor.
        """
        ...
