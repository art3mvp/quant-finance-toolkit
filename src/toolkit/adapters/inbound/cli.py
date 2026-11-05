"""Adaptador inbound de línea de comandos (argparse).

Traduce argumentos de consola a peticiones del dominio (``DownloadRequest`` /
``MacroRequest``), invoca el puerto ``DownloadData`` y presenta el resultado.

No conoce adaptadores ni servicios concretos: recibe una ``service_factory`` desde el
composition root (``toolkit.bootstrap.main``).

Ejemplos::

    toolkit prices AAPL MSFT ^GSPC --start 2020-01-01 --end 2024-12-31 --type equity --out data/
    toolkit macro CPIAUCSL DGS10 --start 2000-01-01 --as-of 2015-06-30

Códigos de salida: 0 si al menos una serie se descarga; 1 si fallan todas;
2 ante errores de uso o configuración.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import re
import sys
import warnings
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any, TextIO

import pandas as pd

from toolkit.domain.errors import ToolkitError
from toolkit.domain.models import (
    AssetType,
    DownloadRequest,
    DownloadResult,
    Frequency,
    MacroRequest,
    MacroSeries,
    PriceSeries,
)
from toolkit.ports.inbound import DownloadData

#: Fábrica inyectada: (fuente de precios, fuente macro | None, max_workers) -> DownloadData.
ServiceFactory = Callable[[str, str | None, int], DownloadData]

EXIT_OK = 0
EXIT_ALL_FAILED = 1
EXIT_USAGE = 2


def _iso_date(value: str) -> date:
    """Tipo de argparse para fechas ``YYYY-MM-DD``."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida {value!r}; usa YYYY-MM-DD") from None


def build_parser(
    price_sources: Sequence[str], macro_sources: Sequence[str]
) -> argparse.ArgumentParser:
    """Construye el parser de argumentos de la CLI."""
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
    common.add_argument("--workers", type=int, default=8, help="descargas simultáneas")

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
    prices.add_argument("--source", choices=list(price_sources), default="yahoo")

    macro = sub.add_parser("macro", parents=[common], help="descarga series macroeconómicas")
    macro.add_argument("series_ids", nargs="+", help="ids de serie, p. ej. CPIAUCSL DGS10")
    macro.add_argument(
        "--as-of", type=_iso_date, help="vintage: datos tal como se publicaron ese día (ALFRED)"
    )
    macro.add_argument("--source", choices=list(macro_sources), default="fred")
    return parser


def run(
    argv: Sequence[str] | None,
    service_factory: ServiceFactory,
    price_sources: Sequence[str] = ("yahoo",),
    macro_sources: Sequence[str] = ("fred",),
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Ejecuta la CLI y devuelve el código de salida.

    Args:
        argv: Argumentos (sin el nombre del programa). ``None`` usa ``sys.argv[1:]``.
        service_factory: Fábrica del caso de uso, inyectada por el composition root.
        price_sources: Fuentes de precios disponibles (para ``--source``).
        macro_sources: Fuentes macro disponibles (para ``--source``).
        stdout: Flujo de salida (por defecto ``sys.stdout``).
        stderr: Flujo de errores (por defecto ``sys.stderr``).
    """
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = build_parser(price_sources, macro_sources).parse_args(argv)
    _configure_logging(args.verbose)

    result: DownloadResult[Any]
    try:
        if args.out is not None and args.format == "parquet":
            _require_parquet_engine()  # fallar antes de descargar, no después
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
            service = service_factory("yahoo", args.source, args.workers)
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
        if args.out is not None and result.series:
            for path in save_result(result, args.out, args.format):
                print(f"  guardado: {path}", file=out)
    except ToolkitError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE

    return EXIT_ALL_FAILED if result.n_success == 0 else EXIT_OK


# ---------------------------------------------------------------------- presentación


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
            f"{s.mean:>14.4f}{s.std:>12.4f}  {s.vintage or '-'}",
            file=out,
        )


def _print_errors(result: DownloadResult[object], out: TextIO) -> None:
    if result.errors:
        print("Errores:", file=out)
        for identifier, message in result.errors.items():
            print(f"  {identifier}: {message}", file=out)


# ---------------------------------------------------------------------- persistencia


def _safe_filename(identifier: str) -> str:
    """Convierte un identificador (p. ej. ``^GSPC``) en un nombre de fichero seguro."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", identifier)


def save_result(
    result: DownloadResult[PriceSeries] | DownloadResult[MacroSeries],
    out_dir: Path,
    fmt: str = "csv",
) -> list[Path]:
    """Guarda cada serie del resultado en ``out_dir`` como CSV o Parquet.

    Raises:
        ToolkitError: Si se pide Parquet sin tener ``pyarrow`` instalado.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for identifier, series in result.series.items():
        if isinstance(series, PriceSeries):
            frame = series.data
            stem = _safe_filename(identifier)
        else:
            frame = series.data.to_frame("value")
            suffix = f"_asof_{series.vintage.isoformat()}" if series.vintage else ""
            stem = _safe_filename(identifier) + suffix
        path = out_dir / f"{stem}.{fmt}"
        _write(frame, path, fmt)
        paths.append(path)
    return paths


def _require_parquet_engine() -> None:
    """Comprueba que ``pyarrow`` esté instalado.

    Raises:
        ToolkitError: Si no está disponible.
    """
    if importlib.util.find_spec("pyarrow") is None:
        raise ToolkitError(
            'Parquet requiere pyarrow: pip install -e ".[parquet]" (o usa --format csv)'
        )


def _write(frame: pd.DataFrame, path: Path, fmt: str) -> None:
    if fmt == "csv":
        frame.to_csv(path, index_label="date")
        return
    try:
        frame.to_parquet(path)
    except ImportError as exc:
        raise ToolkitError(
            'Parquet requiere pyarrow: pip install -e ".[parquet]" (o usa --format csv)'
        ) from exc


def _configure_logging(verbose: bool) -> None:
    """Configura logging: INFO con ``-v``; si no, solo errores y sin ruido de terceros."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.ERROR,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        warnings.filterwarnings("ignore", module="yfinance")
