"""Servicio de aplicación: descarga en lote de N series en paralelo.

Implementa el puerto inbound ``DownloadData`` y depende únicamente de los puertos
outbound ``PriceProvider`` y ``MacroProvider``, que recibe por inyección. No sabe
nada de Yahoo, FRED ni de HTTP.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date
from typing import TypeVar

from toolkit.domain.errors import ConfigurationError, InvalidRequestError, ToolkitError
from toolkit.domain.models import (
    DownloadRequest,
    DownloadResult,
    MacroRequest,
    MacroSeries,
    PriceSeries,
)
from toolkit.ports.outbound import MacroProvider, PriceProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DownloadService:
    """Orquesta descargas en lote tolerantes a fallos individuales.

    Args:
        price_provider: Adaptador que cumple ``PriceProvider``.
        macro_provider: Adaptador que cumple ``MacroProvider`` (opcional).
        max_workers: Número máximo de descargas simultáneas.

    Raises:
        TypeError: Si algún proveedor no cumple su puerto.
        ValueError: Si ``max_workers < 1``.
    """

    def __init__(
        self,
        price_provider: PriceProvider,
        macro_provider: MacroProvider | None = None,
        max_workers: int = 8,
    ) -> None:
        if not isinstance(price_provider, PriceProvider):
            raise TypeError(f"{price_provider!r} no cumple el puerto PriceProvider")
        if macro_provider is not None and not isinstance(macro_provider, MacroProvider):
            raise TypeError(f"{macro_provider!r} no cumple el puerto MacroProvider")
        if max_workers < 1:
            raise ValueError("max_workers debe ser >= 1")
        self.price_provider = price_provider
        self.macro_provider = macro_provider
        self.max_workers = max_workers

    # ------------------------------------------------------------------ casos de uso

    def download_prices(self, request: DownloadRequest) -> DownloadResult[PriceSeries]:
        """Descarga en paralelo las series de precios de la petición.

        Los tickers se normalizan (``strip`` + mayúsculas) y se deduplican conservando el
        orden. Un fallo individual se registra en ``errors`` sin abortar el lote.

        Raises:
            InvalidRequestError: Si la petición es inválida.
            ConfigurationError: Si el proveedor no está bien configurado.
        """
        tickers = _normalize_ids(request.tickers, "tickers")
        _validate_range(request.start, request.end)
        provider = self.price_provider
        logger.info(
            "Descargando %d series de precios de %s (%s, %s)",
            len(tickers),
            provider.name,
            request.interval.value,
            request.asset_type.value,
        )
        return self._run_batch(
            tickers,
            lambda t: provider.fetch_prices(
                t, request.start, request.end, request.interval, request.asset_type
            ),
        )

    def download_macro(self, request: MacroRequest) -> DownloadResult[MacroSeries]:
        """Descarga en paralelo las series macroeconómicas de la petición.

        Si ``request.as_of`` está informado, se piden los datos tal como se publicaron
        ese día (vintage, modo ALFRED).

        Raises:
            InvalidRequestError: Si la petición es inválida.
            ConfigurationError: Si no hay proveedor macro o falta su configuración.
        """
        if self.macro_provider is None:
            raise ConfigurationError("No hay ningún proveedor macro configurado")
        series_ids = _normalize_ids(request.series_ids, "series_ids")
        _validate_range(request.start, request.end)
        provider = self.macro_provider
        logger.info(
            "Descargando %d series macro de %s (as_of=%s)",
            len(series_ids),
            provider.name,
            request.as_of,
        )
        return self._run_batch(
            series_ids,
            lambda s: provider.fetch_series(s, request.start, request.end, request.as_of),
        )

    # ------------------------------------------------------------------ internos

    def _run_batch(self, ids: list[str], fetch: Callable[[str], T]) -> DownloadResult[T]:
        """Ejecuta ``fetch`` para cada id en paralelo y agrupa resultados y errores.

        Los ``ConfigurationError`` se propagan (afectan a todo el lote, no a una serie);
        cualquier otra excepción se registra como error de ese id.
        """
        result: DownloadResult[T] = DownloadResult()
        workers = min(self.max_workers, len(ids))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="download") as pool:
            futures: dict[str, Future[T]] = {i: pool.submit(fetch, i) for i in ids}
            for identifier in ids:  # recorrer en el orden de entrada preserva el orden
                try:
                    result.series[identifier] = futures[identifier].result()
                except ConfigurationError:
                    for future in futures.values():
                        future.cancel()
                    raise
                except ToolkitError as exc:
                    logger.warning("Fallo al descargar %s: %s", identifier, exc)
                    result.errors[identifier] = str(exc)
                except Exception as exc:  # error inesperado: no debe tumbar el lote
                    logger.exception("Error inesperado al descargar %s", identifier)
                    result.errors[identifier] = f"{type(exc).__name__}: {exc}"
        logger.info("Lote terminado: %d OK, %d fallidas", result.n_success, result.n_failed)
        return result


def _normalize_ids(ids: Iterable[str], field_name: str) -> list[str]:
    """Normaliza identificadores (``strip`` + mayúsculas) y elimina duplicados en orden.

    Raises:
        InvalidRequestError: Si la lista está vacía o contiene elementos no válidos.
    """
    if isinstance(ids, str):
        raise InvalidRequestError(f"{field_name} debe ser una lista, no un str")
    normalized: list[str] = []
    for raw in ids:
        if not isinstance(raw, str) or not raw.strip():
            raise InvalidRequestError(f"{field_name} contiene un identificador inválido: {raw!r}")
        value = raw.strip().upper()
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise InvalidRequestError(f"{field_name} no puede estar vacío")
    return normalized


def _validate_range(start: date | None, end: date | None) -> None:
    """Comprueba que ``start <= end`` cuando ambas fechas están informadas.

    Raises:
        InvalidRequestError: Si ``start > end``.
    """
    if start is not None and end is not None and start > end:
        raise InvalidRequestError(f"start ({start}) no puede ser posterior a end ({end})")
