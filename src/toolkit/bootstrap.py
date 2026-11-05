"""Composition root: el único módulo que conoce los adaptadores concretos.

Aquí se carga la configuración (``.env``), se eligen los proveedores por nombre y se
inyectan en el ``DownloadService``. Añadir una fuente nueva es registrar una fábrica
en ``PRICE_PROVIDERS`` o ``MACRO_PROVIDERS``::

    PRICE_PROVIDERS["alphavantage"] = lambda: AlphaVantagePriceProvider(
        api_key=os.getenv("ALPHAVANTAGE_API_KEY")
    )

Uso desde Python::

    from toolkit.bootstrap import build_download_service
    service = build_download_service()                 # yahoo + fred
    service = build_download_service("yahoo", None)    # solo precios
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
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
from toolkit.adapters.outbound.specialized.coingecko import CoinGeckoPriceProvider
from toolkit.adapters.outbound.specialized.eia import EiaMacroProvider
from toolkit.domain.errors import ConfigurationError
from toolkit.ports.outbound import MacroProvider, PriceProvider
from toolkit.services.download_service import DownloadService

P = TypeVar("P")

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
}


def load_settings() -> None:
    """Carga variables de entorno desde ``.env`` (buscando desde el directorio actual).

    Las variables ya definidas en el entorno tienen prioridad sobre el fichero.
    """
    load_dotenv(find_dotenv(usecwd=True), override=False)


def build_download_service(
    price_source: str = "yahoo",
    macro_source: str | None = "fred",
    max_workers: int = 8,
) -> DownloadService:
    """Construye un ``DownloadService`` con los proveedores indicados.

    Args:
        price_source: Nombre de la fuente de precios (ver ``PRICE_PROVIDERS``).
        macro_source: Nombre de la fuente macro (ver ``MACRO_PROVIDERS``) o ``None``.
        max_workers: Descargas simultáneas.

    Raises:
        ConfigurationError: Si alguna fuente no está registrada.
    """
    load_settings()
    price_factory = _lookup(PRICE_PROVIDERS, price_source, "precios")
    macro_provider = (
        _lookup(MACRO_PROVIDERS, macro_source, "macro")() if macro_source is not None else None
    )
    return DownloadService(
        price_provider=price_factory(),
        macro_provider=macro_provider,
        max_workers=max_workers,
    )


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
    """Punto de entrada del comando ``toolkit``: inyecta la fábrica del servicio en la CLI."""
    return cli.run(
        argv,
        service_factory=build_download_service,
        price_sources=sorted(PRICE_PROVIDERS),
        macro_sources=sorted(MACRO_PROVIDERS),
    )


if __name__ == "__main__":
    raise SystemExit(main())
