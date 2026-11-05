"""Composition root: el único módulo que conoce los adaptadores concretos.

Aquí se carga la configuración (``.env``), se eligen los proveedores por nombre y se
inyectan en los servicios (``DownloadService``, ``DocumentService``, ``StorageService``).
Añadir una fuente
nueva es registrar una fábrica en ``PRICE_PROVIDERS``, ``MACRO_PROVIDERS`` o
``DOCUMENT_PROVIDERS``::

    PRICE_PROVIDERS["alpha_vantage"] = lambda: AlphaVantagePriceProvider(
        api_key=os.getenv("ALPHA_VANTAGE_API_KEY")
    )

Uso desde Python::

    from toolkit.bootstrap import build_download_service
    service = build_download_service()                 # yahoo + fred
    service = build_download_service("yahoo", None)    # solo precios
    service = build_download_service(None, "ecb")      # solo macro
    docs = build_document_service("cnmv")
    storage = build_storage_service("data/", "csv")    # StoreSeries sobre ficheros
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TypeVar

from dotenv import find_dotenv, load_dotenv

from toolkit.adapters.inbound import cli
from toolkit.adapters.outbound.fiscal.us_treasury import UsTreasuryMacroProvider
from toolkit.adapters.outbound.macro.banco_espana import BancoEspanaMacroProvider
from toolkit.adapters.outbound.macro.bis import BisMacroProvider
from toolkit.adapters.outbound.macro.ecb import EcbMacroProvider
from toolkit.adapters.outbound.macro.eurostat import EurostatMacroProvider
from toolkit.adapters.outbound.macro.fred import FredMacroProvider
from toolkit.adapters.outbound.macro.world_bank import WorldBankMacroProvider
from toolkit.adapters.outbound.market.alpha_vantage import AlphaVantagePriceProvider
from toolkit.adapters.outbound.market.twelve_data import TwelveDataPriceProvider
from toolkit.adapters.outbound.market.yahoo import YahooPriceProvider
from toolkit.adapters.outbound.regulatory.cnmv import CnmvDocumentProvider
from toolkit.adapters.outbound.regulatory.esma import EsmaDocumentProvider
from toolkit.adapters.outbound.regulatory.sec_edgar import SecEdgarMacroProvider
from toolkit.adapters.outbound.specialized.coingecko import CoinGeckoPriceProvider
from toolkit.adapters.outbound.specialized.eia import EiaMacroProvider
from toolkit.adapters.outbound.storage.files import FileSeriesRepository
from toolkit.domain.errors import ConfigurationError
from toolkit.ports.outbound import DocumentProvider, MacroProvider, PriceProvider
from toolkit.services.document_service import DocumentService
from toolkit.services.download_service import DownloadService
from toolkit.services.storage_service import StorageService

P = TypeVar("P")

#: Fuentes usadas cuando no se indica ninguna (sin clave, salvo FRED).
DEFAULT_PRICE_SOURCE = "yahoo"
DEFAULT_MACRO_SOURCE = "fred"

#: Fábricas de proveedores de precios por nombre de fuente.
PRICE_PROVIDERS: dict[str, Callable[[], PriceProvider]] = {
    "yahoo": YahooPriceProvider,
    "alpha_vantage": lambda: AlphaVantagePriceProvider(api_key=os.getenv("ALPHA_VANTAGE_API_KEY")),
    "twelve_data": lambda: TwelveDataPriceProvider(api_key=os.getenv("TWELVE_DATA_API_KEY")),
    "coingecko": lambda: CoinGeckoPriceProvider(
        api_key=os.getenv("COINGECKO_API_KEY"), plan=os.getenv("COINGECKO_API_PLAN", "demo")
    ),
}

#: Fábricas de proveedores macro por nombre de fuente.
MACRO_PROVIDERS: dict[str, Callable[[], MacroProvider]] = {
    "fred": lambda: FredMacroProvider(api_key=os.getenv("FRED_API_KEY")),
    "ecb": EcbMacroProvider,
    "eurostat": EurostatMacroProvider,
    "bis": BisMacroProvider,
    "world_bank": WorldBankMacroProvider,
    "banco_espana": BancoEspanaMacroProvider,
    "us_treasury": UsTreasuryMacroProvider,  # fiscal: mismo puerto que las series macro
    "eia": lambda: EiaMacroProvider(api_key=os.getenv("EIA_API_KEY")),
    # regulatory: fundamentales como series univariantes, con as_of = fecha de presentación
    "sec_edgar": lambda: SecEdgarMacroProvider(user_agent=os.getenv("SEC_USER_AGENT")),
}

#: Fábricas de proveedores de documentos regulatorios por nombre de fuente.
DOCUMENT_PROVIDERS: dict[str, Callable[[], DocumentProvider]] = {
    "cnmv": CnmvDocumentProvider,
    "esma": EsmaDocumentProvider,
}


@functools.cache
def load_settings() -> None:
    """Carga variables de entorno desde ``.env`` (buscando desde el directorio actual).

    Se ejecuta una sola vez por proceso, aunque se construyan varios servicios. Las
    variables ya definidas en el entorno tienen prioridad sobre el fichero; si cambias
    ``.env`` en un notebook, reinicia el kernel (o llama a ``load_settings.cache_clear()``).
    """
    load_dotenv(find_dotenv(usecwd=True), override=False)


def build_download_service(
    price_source: str | None = DEFAULT_PRICE_SOURCE,
    macro_source: str | None = DEFAULT_MACRO_SOURCE,
    max_workers: int = 8,
) -> DownloadService:
    """Construye un ``DownloadService`` con los proveedores indicados.

    Args:
        price_source: Nombre de la fuente de precios (ver ``PRICE_PROVIDERS``) o ``None``.
        macro_source: Nombre de la fuente macro (ver ``MACRO_PROVIDERS``) o ``None``.
        max_workers: Descargas simultáneas.

    Raises:
        ConfigurationError: Si alguna fuente no está registrada.
    """
    load_settings()
    price_provider = _build(PRICE_PROVIDERS, price_source, "precios")
    macro_provider = _build(MACRO_PROVIDERS, macro_source, "macro")
    return DownloadService(
        price_provider=price_provider,
        macro_provider=macro_provider,
        max_workers=max_workers,
    )


def build_document_service(source: str = "cnmv") -> DocumentService:
    """Construye el caso de uso ``ListDocuments`` sobre la fuente ``source``.

    Raises:
        ConfigurationError: Si la fuente no está registrada.
    """
    load_settings()
    return DocumentService(_lookup(DOCUMENT_PROVIDERS, source, "documentos")())


def build_storage_service(directory: str | Path, fmt: str = "csv") -> StorageService:
    """Construye el caso de uso ``StoreSeries`` sobre ficheros en ``directory``.

    Raises:
        InvalidRequestError: Si el formato no está admitido.
        ConfigurationError: Si se pide Parquet sin ``pyarrow``.
    """
    return StorageService(FileSeriesRepository(directory, fmt))


def _build(registry: Mapping[str, Callable[[], P]], name: str | None, kind: str) -> P | None:
    """Instancia la fuente ``name`` del registro, o ``None`` si no se pide ninguna."""
    return _lookup(registry, name, kind)() if name is not None else None


def _lookup(registry: Mapping[str, Callable[[], P]], name: str, kind: str) -> Callable[[], P]:
    """Busca una fábrica en el registro (sin distinguir mayúsculas)."""
    key = name.strip().lower()
    if key not in registry:
        available = ", ".join(sorted(registry))
        raise ConfigurationError(
            f"Fuente de {kind} desconocida: {name!r}. Disponibles: {available}"
        )
    return registry[key]


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada del comando ``toolkit``: inyecta fábricas y fuentes en la CLI."""
    return cli.run(
        argv,
        service_factory=build_download_service,
        price_sources=sorted(PRICE_PROVIDERS),
        macro_sources=sorted(MACRO_PROVIDERS),
        document_factory=build_document_service,
        document_sources=sorted(DOCUMENT_PROVIDERS),
        storage_factory=build_storage_service,
        default_price_source=DEFAULT_PRICE_SOURCE,
        default_macro_source=DEFAULT_MACRO_SOURCE,
        quiet_loggers=("yfinance",),  # librería de terceros con avisos ruidosos
    )


if __name__ == "__main__":
    raise SystemExit(main())
