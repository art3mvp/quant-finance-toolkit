"""Adaptador inbound de línea de comandos (argparse).

Traduce argumentos de consola a peticiones del dominio (``DownloadRequest``,
``MacroRequest``, ``DocumentRequest``), invoca los puertos inbound ``DownloadData``,
``ListDocuments`` y ``StoreSeries`` y presenta el resultado.

No conoce adaptadores, servicios, nombres de fuentes ni cómo se escriben los ficheros: las
fábricas, las fuentes disponibles y las de por defecto llegan desde el composition root
(``toolkit.bootstrap.main``). Solo parsea argumentos e imprime.

Ejemplos::

    toolkit prices AAPL MSFT ^GSPC --start 2020-01-01 --end 2024-12-31 --type equity --out data/
    toolkit macro CPIAUCSL DGS10 --start 2000-01-01 --as-of 2015-06-30
    toolkit docs --source cnmv --query indra

Códigos de salida: 0 si se obtiene al menos una serie o documento; 1 si fallan todas
o la fuente falla; 2 ante errores de uso o configuración.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

from toolkit.domain.documents import DocumentRequest, RegulatoryDocument
from toolkit.domain.errors import ConfigurationError, ProviderError, ToolkitError
from toolkit.domain.models import (
    AssetType,
    DownloadRequest,
    DownloadResult,
    Frequency,
    MacroRequest,
    MacroSeries,
    PriceSeries,
)
from toolkit.ports.inbound import DownloadData, ListDocuments, StoreSeries

#: Fábrica inyectada: (fuente de precios | None, fuente macro | None, workers) -> caso de uso.
ServiceFactory = Callable[[str | None, str | None, int], DownloadData]
#: Fábrica inyectada: nombre de la fuente de documentos -> caso de uso.
DocumentFactory = Callable[[str], ListDocuments]
#: Fábrica inyectada: (directorio de ``--out``, formato) -> caso de uso de persistencia.
StorageFactory = Callable[[Path, str], StoreSeries]

EXIT_OK = 0
EXIT_ALL_FAILED = 1
EXIT_USAGE = 2


def _iso_date(value: str) -> date:
    """Tipo de argparse para fechas ``YYYY-MM-DD``."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida {value!r}; usa YYYY-MM-DD") from None


def _positive_int(value: str) -> int:
    """Tipo de argparse para enteros ``>= 1`` (``--workers``, ``--limit``)."""
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"debe ser un entero >= 1, no {value!r}")
    return number


def build_parser(
    price_sources: Sequence[str],
    macro_sources: Sequence[str],
    document_sources: Sequence[str] = (),
    default_price_source: str | None = None,
    default_macro_source: str | None = None,
) -> argparse.ArgumentParser:
    """Construye el parser; sin default explícito, ``--source`` usa la primera fuente."""
    parser = argparse.ArgumentParser(
        prog="toolkit",
        description="Toolkit financiero: descarga y estandarización de series de mercado y macro.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="logging detallado (INFO)")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--start", type=_iso_date, help="fecha inicial YYYY-MM-DD")
    common.add_argument("--end", type=_iso_date, help="fecha final YYYY-MM-DD (incluida)")
    common.add_argument("--out", type=Path, help="directorio donde guardar las series")
    common.add_argument(
        "--format", choices=["csv", "parquet"], default="csv", help="formato de salida (--out)"
    )
    common.add_argument("--workers", type=_positive_int, default=8, help="descargas simultáneas")

    prices = sub.add_parser("prices", parents=[common], help="descarga series de precios OHLCV")
    prices.add_argument("tickers", nargs="+", help="tickers, p. ej. AAPL MSFT ^GSPC")
    prices.add_argument(
        "--type",
        dest="asset_type",
        choices=[a.value for a in AssetType],
        default=AssetType.EQUITY.value,
        help="tipo de activo",
    )
    prices.add_argument(
        "--interval",
        choices=[f.value for f in Frequency],
        default=Frequency.DAILY.value,
        help="frecuencia de las observaciones",
    )
    prices.add_argument(
        "--source", choices=list(price_sources), default=default_price_source or price_sources[0]
    )

    macro = sub.add_parser("macro", parents=[common], help="descarga series macroeconómicas")
    macro.add_argument("series_ids", nargs="+", help="ids de serie, p. ej. CPIAUCSL DGS10")
    macro.add_argument(
        "--as-of",
        type=_iso_date,
        help="vintage: datos tal como se publicaron ese día (si la fuente lo admite)",
    )
    macro.add_argument(
        "--source", choices=list(macro_sources), default=default_macro_source or macro_sources[0]
    )

    if document_sources:
        docs = sub.add_parser("docs", help="lista documentos regulatorios")
        docs.add_argument("--source", choices=list(document_sources), required=True)
        docs.add_argument("--query", help="filtro propio de la fuente (emisor, tipo...)")
        docs.add_argument("--start", type=_iso_date, help="publicados desde YYYY-MM-DD")
        docs.add_argument("--end", type=_iso_date, help="publicados hasta YYYY-MM-DD (incluida)")
        docs.add_argument("--limit", type=_positive_int, default=20, help="máximo de documentos")
    return parser


def run(
    argv: Sequence[str] | None,
    service_factory: ServiceFactory,
    price_sources: Sequence[str] = ("yahoo",),
    macro_sources: Sequence[str] = ("fred",),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    document_factory: DocumentFactory | None = None,
    document_sources: Sequence[str] = (),
    default_price_source: str | None = None,
    default_macro_source: str | None = None,
    quiet_loggers: Sequence[str] = (),
    storage_factory: StorageFactory | None = None,
) -> int:
    """Ejecuta la CLI y devuelve el código de salida.

    Args:
        argv: Argumentos (sin el nombre del programa). ``None`` usa ``sys.argv[1:]``.
        service_factory: Fábrica del caso de uso, inyectada por el composition root.
        price_sources: Fuentes de precios disponibles (para ``--source``).
        macro_sources: Fuentes macro disponibles (para ``--source``).
        stdout: Flujo de salida (por defecto ``sys.stdout``).
        stderr: Flujo de errores (por defecto ``sys.stderr``).
        document_factory: Fábrica del caso de uso ``ListDocuments`` (activa ``docs``).
        document_sources: Fuentes de documentos disponibles (para ``docs --source``).
        default_price_source: ``--source`` por defecto de ``prices``.
        default_macro_source: ``--source`` por defecto de ``macro``.
        quiet_loggers: Loggers de librerías de terceros a silenciar sin ``-v``.
        storage_factory: Fábrica del caso de uso ``StoreSeries`` (activa ``--out``).
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    sources = document_sources if document_factory is not None else ()
    parser = build_parser(
        price_sources, macro_sources, sources, default_price_source, default_macro_source
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, quiet_loggers)
    if args.command == "docs" and document_factory is not None:
        return _run_docs(args, document_factory, out, err)

    result: DownloadResult[Any]
    try:
        storage = _build_storage(storage_factory, args.out, args.format)  # antes de descargar
        if args.command == "prices":
            service = service_factory(args.source, None, args.workers)
            result = service.download_prices(
                DownloadRequest(
                    tickers=args.tickers,
                    start=args.start,
                    end=args.end,
                    interval=Frequency(args.interval),
                    asset_type=AssetType(args.asset_type),
                )
            )
            _print_prices(result, out)
        else:
            service = service_factory(None, args.source, args.workers)
            result = service.download_macro(
                MacroRequest(
                    series_ids=args.series_ids,
                    start=args.start,
                    end=args.end,
                    as_of=args.as_of,
                )
            )
            _print_macro(result, out)
        _print_errors(result, out)
        if storage is not None:
            for location in storage.store(result.series):
                print(f"  guardado: {location}", file=out)
    except ToolkitError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE

    return EXIT_ALL_FAILED if result.n_success == 0 else EXIT_OK


def _build_storage(
    factory: StorageFactory | None, out_dir: Path | None, fmt: str
) -> StoreSeries | None:
    """Construye el caso de uso de persistencia si se pidió ``--out``.

    Raises:
        ConfigurationError: Si se pidió ``--out`` sin almacenamiento configurado, o si el
            destino no es válido (p. ej. Parquet sin ``pyarrow``).
    """
    if out_dir is None:
        return None
    if factory is None:
        raise ConfigurationError("--out no está disponible: no hay almacenamiento configurado")
    return factory(out_dir, fmt)


def _run_docs(args: argparse.Namespace, factory: DocumentFactory, out: TextIO, err: TextIO) -> int:
    """Subcomando ``docs``: 1 si no hay documentos o la fuente falla; 2 si es de uso."""
    try:
        request = DocumentRequest(args.query, args.start, args.end, args.limit)
        documents = factory(args.source).list_documents(request)
    except (ProviderError, ConfigurationError) as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE if isinstance(exc, ConfigurationError) else EXIT_ALL_FAILED
    except ToolkitError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE
    _print_documents(documents, out)
    return EXIT_OK if documents else EXIT_ALL_FAILED


# ---------------------------------------------------------------------- presentación


def _print_documents(documents: Sequence[RegulatoryDocument], out: TextIO) -> None:
    print(f"Documentos: {len(documents)}", file=out)
    for doc in documents:
        print(f"{doc.published_at:%Y-%m-%d %H:%M}  {doc.identifier:<12}  {doc.title}", file=out)
        print(f"{'':18}{doc.url}", file=out)


def _print_prices(result: DownloadResult[PriceSeries], out: TextIO) -> None:
    print(f"Descargadas: {result.n_success} OK, {result.n_failed} fallidas", file=out)
    if not result.series:
        return
    # 14 caracteres: cabe el nombre de fuente más largo previsto (p. ej. "alpha_vantage")
    header = f"{'ticker':<12}{'fuente':<14}{'divisa':<7}{'n_obs':>7}  {'inicio':<11}{'fin':<11}"
    print(header + f"{'media_ret':>12}{'std_ret':>11}", file=out)
    for ticker, s in result.series.items():
        print(
            f"{ticker:<12}{s.source:<14}{s.currency or '-':<7}{s.n_obs:>7}  "
            f"{s.start!s:<11}{s.end!s:<11}{s.mean_return:>12.6f}{s.std_return:>11.6f}",
            file=out,
        )


def _print_macro(result: DownloadResult[MacroSeries], out: TextIO) -> None:
    print(f"Descargadas: {result.n_success} OK, {result.n_failed} fallidas", file=out)
    if not result.series:
        return
    # ancho adaptable: los ids SDMX (p. ej. EXR/D.USD.EUR.SP00.A) superan los 14 caracteres
    width = max(14, *(len(sid) + 2 for sid in result.series))
    header = f"{'serie':<{width}}{'frec':<10}{'n_obs':>7}  {'inicio':<11}{'fin':<11}"
    print(header + f"{'media':>14}{'std':>12}  vintage", file=out)
    for sid, s in result.series.items():
        print(
            f"{sid:<{width}}{s.frequency.value:<10}{s.n_obs:>7}  {s.start!s:<11}{s.end!s:<11}"
            f"{s.mean:>14.6g}{s.std:>12.6g}  {s.vintage or '-'}",  # g: magnitudes de 1e-3 a 1e13
            file=out,
        )


def _print_errors(result: DownloadResult[object], out: TextIO) -> None:
    if result.errors:
        print("Errores:", file=out)
        for identifier, message in result.errors.items():
            print(f"  {identifier}: {message}", file=out)


# ---------------------------------------------------------------------- logging


def _configure_logging(verbose: bool, quiet_loggers: Sequence[str] = ()) -> None:
    """Configura logging: INFO con ``-v``; si no, solo errores y sin ruido de terceros."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        for name in quiet_loggers:
            logging.getLogger(name).setLevel(logging.CRITICAL)
            warnings.filterwarnings("ignore", module=name)
