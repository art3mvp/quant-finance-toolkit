"""Cada fuente traduce su respuesta de error real al error del dominio que corresponde.

Las APIs señalan "no existe" de formas muy distintas (404, 400, 412, HTTP 200 con el
error en el cuerpo...). El toolkit debe convertirlas todas en el mismo criterio
(ver ``docs/architecture.md``, *Criterio de errores*).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from tests.integration.replay import Cassette
from toolkit import bootstrap
from toolkit.bootstrap import build_download_service
from toolkit.domain.errors import InvalidRequestError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, DownloadRequest, Frequency, MacroRequest

Replay = Callable[[str, str], Cassette]
JAN = {"start": date(2024, 1, 2), "end": date(2024, 1, 31)}

#: (fuente, grabación, id, argumentos de la petición, error esperado, fragmento del mensaje)
PRICE_ERRORS: list[tuple[str, str, str, dict[str, Any], type[Exception], str]] = [
    ("yahoo", "unknown_ticker", "NOEXISTE123", JAN, SeriesNotFoundError, "sin datos"),
    (
        "alpha_vantage",
        "unknown_ticker",
        "NOEXISTE123",
        {"start": date(2024, 1, 1), "end": date(2024, 3, 31), "interval": Frequency.WEEKLY},
        SeriesNotFoundError,
        "no válido",
    ),
    (
        "alpha_vantage",
        "rate_limited",
        "NOEXISTE123",
        {"start": date(2024, 1, 1), "end": date(2024, 3, 31), "interval": Frequency.WEEKLY},
        ProviderError,
        "1 request per second",
    ),
    ("twelve_data", "unknown_ticker", "NOEXISTE123", JAN, SeriesNotFoundError, "no encontrado"),
]

MACRO_ERRORS: list[tuple[str, str, str, dict[str, Any], type[Exception], str]] = [
    (
        "fred",
        "unknown_series",
        "NOEXISTE123",
        {"start": date(2014, 1, 1), "end": date(2015, 6, 30)},
        SeriesNotFoundError,
        "does not exist",
    ),
    (
        "ecb",
        "unknown_series",
        "EXR/D.XXX.EUR.SP00.A",
        {"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        SeriesNotFoundError,
        "no encontrado",
    ),
    (
        "bis",
        "unknown_series",
        "WS_CBPOL/M.XX",
        {"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        SeriesNotFoundError,
        "no encontrado",
    ),
    (
        "eurostat",
        "unknown_series",
        "prc_hicp_manr/M.RCH_A.CP00.XX",
        {"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        SeriesNotFoundError,
        "no encontrado: GEO=XX$",  # el motivo, sin el XML de la respuesta
    ),
    (
        "eurostat",
        "no_data_in_range",
        "prc_hicp_manr/M.RCH_A.CP00.ES",
        {"start": date(1900, 1, 1), "end": date(1900, 12, 31)},
        SeriesNotFoundError,
        "no encontrado: TIME_PERIOD",
    ),
    (
        "eurostat",
        "unknown_dataset",
        "no_existe_123/M.RCH_A.CP00.ES",
        {"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        SeriesNotFoundError,
        "NO_EXISTE_123 is not available",
    ),
    (
        "eurostat",
        "malformed_key",
        "prc_hicp_manr/M.RCH_A",
        {"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        InvalidRequestError,
        "clave mal formada: INVALID_QUERY_NB_FILTERS",
    ),
    (
        "world_bank",
        "unknown_indicator",
        "ESP/NO.EXISTE.123",
        {"start": date(2015, 1, 1), "end": date(2023, 12, 31)},
        SeriesNotFoundError,
        "not valid",
    ),
    (
        "banco_espana",
        "unknown_series",
        "NOEXISTE123",
        {"start": date(2023, 1, 1), "end": date(2023, 12, 31)},
        SeriesNotFoundError,
        "no encontrado",
    ),
    (
        "us_treasury",
        "unknown_field",
        "v2/accounting/od/debt_to_penny:no_existe_amt",
        {"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        SeriesNotFoundError,
        r"no encontrado: .*Field 'no_existe_amt' does not exist\.$",
    ),
    (
        "us_treasury",
        "unknown_filter_field",
        "v2/accounting/od/avg_interest_rates:avg_interest_rate_amt:no_existe=x",
        {"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        SeriesNotFoundError,
        "Field 'no_existe' does not exist",
    ),
    (
        "us_treasury",
        "unknown_endpoint",
        "v2/accounting/od/no_existe:record_amt",
        {"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        SeriesNotFoundError,
        r"no encontrado \(HTTP 404\)",
    ),
    (
        "eia",
        "unknown_series",
        "PET.NOEXISTE.D",
        {"start": date(2024, 1, 1), "end": date(2024, 1, 31)},
        SeriesNotFoundError,
        "no encontrado",
    ),
]


def _ids(cases: list[tuple[Any, ...]]) -> list[str]:
    return [f"{source}-{case}" for source, case, *_ in cases]


@pytest.mark.parametrize(
    ("source", "case", "ticker", "request_args", "error", "message"),
    PRICE_ERRORS,
    ids=_ids(PRICE_ERRORS),
)
def test_price_source_error_is_translated(
    replay: Replay,
    source: str,
    case: str,
    ticker: str,
    request_args: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    replay(source, case)
    provider = bootstrap.PRICE_PROVIDERS[source]()
    args = {"interval": Frequency.DAILY, **request_args}
    with pytest.raises(error, match=message) as excinfo:
        provider.fetch_prices(
            ticker, args["start"], args["end"], args["interval"], AssetType.EQUITY
        )
    assert type(excinfo.value) is error  # no una subclase u otra rama de la jerarquía
    assert str(excinfo.value).startswith(f"{source}:")

    # en el servicio, el fallo queda registrado y no aborta el lote
    result = build_download_service(source, None).download_prices(
        DownloadRequest(tickers=[ticker], **request_args)
    )
    assert result.all_failed and ticker in result.errors


@pytest.mark.parametrize(
    ("source", "case", "series_id", "request_args", "error", "message"),
    MACRO_ERRORS,
    ids=_ids(MACRO_ERRORS),
)
def test_macro_source_error_is_translated(
    replay: Replay,
    source: str,
    case: str,
    series_id: str,
    request_args: dict[str, Any],
    error: type[Exception],
    message: str,
) -> None:
    replay(source, case)
    provider = bootstrap.MACRO_PROVIDERS[source]()
    with pytest.raises(error, match=message) as excinfo:
        provider.fetch_series(series_id, request_args["start"], request_args["end"], None)
    assert type(excinfo.value) is error
    assert str(excinfo.value).startswith(f"{source}:")

    result = build_download_service(None, source).download_macro(
        MacroRequest(series_ids=[series_id], **request_args)
    )
    assert result.all_failed and series_id in result.errors


def test_one_failure_does_not_abort_a_real_batch(replay: Replay) -> None:
    """Lote mixto: la serie válida llega aunque la otra no exista."""
    replay("twelve_data", "aapl_daily")
    replay("twelve_data", "unknown_ticker")
    result = build_download_service("twelve_data", None).download_prices(
        DownloadRequest(tickers=["NOEXISTE123", "AAPL"], **JAN)
    )
    assert list(result.series) == ["AAPL"]
    assert list(result.errors) == ["NOEXISTE123"]
    assert not result.all_failed
