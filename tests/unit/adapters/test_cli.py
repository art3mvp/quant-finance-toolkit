"""Tests de la CLI con un servicio construido sobre proveedores fake (sin red)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider, FakeSeriesRepository
from toolkit.adapters.inbound.cli import EXIT_ALL_FAILED, EXIT_OK, EXIT_USAGE, run
from toolkit.domain.errors import ConfigurationError
from toolkit.domain.models import MacroSeries, PriceSeries
from toolkit.ports.inbound import DownloadData, StoreSeries
from toolkit.services.download_service import DownloadService
from toolkit.services.storage_service import StorageService


class Factory:
    """Fábrica de servicio que registra los argumentos recibidos."""

    def __init__(self, **fake_kwargs: object) -> None:
        self.calls: list[tuple[str | None, str | None, int]] = []
        self.price = FakePriceProvider(**fake_kwargs)  # type: ignore[arg-type]
        self.macro = FakeMacroProvider(**fake_kwargs)  # type: ignore[arg-type]

    def __call__(
        self, price_source: str | None, macro_source: str | None, workers: int
    ) -> DownloadData:
        self.calls.append((price_source, macro_source, workers))
        macro = self.macro if macro_source else None
        return DownloadService(self.price, macro, max_workers=workers)


class StorageFactory:
    """Fábrica de almacenamiento en memoria que registra ``(directorio, formato)``."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[Path, str]] = []
        self.repository = FakeSeriesRepository()
        self.error = error

    def __call__(self, out_dir: Path, fmt: str) -> StoreSeries:
        self.calls.append((out_dir, fmt))
        if self.error is not None:
            raise self.error
        return StorageService(self.repository)


def invoke(
    argv: list[str], factory: Factory, storage: StorageFactory | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        argv,
        service_factory=factory,
        price_sources=["fake", "yahoo"],
        macro_sources=["fake", "fred"],
        stdout=out,
        stderr=err,
        storage_factory=storage,
    )
    return code, out.getvalue(), err.getvalue()


def test_prices_summary_and_partial_failure() -> None:
    factory = Factory(not_found={"NOPE"})
    code, out, _ = invoke(
        [
            "prices",
            "AAPL",
            "NOPE",
            "^GSPC",
            "--start",
            "2023-01-01",
            "--end",
            "2023-03-31",
            "--type",
            "index",
            "--source",
            "fake",
            "--workers",
            "3",
        ],
        factory,
    )
    assert code == EXIT_OK
    assert "2 OK, 1 fallidas" in out
    assert "AAPL" in out and "^GSPC" in out
    assert "NOPE:" in out
    assert factory.calls == [("fake", None, 3)]
    tickers_called = {call[0] for call in factory.price.calls}
    assert tickers_called == {"AAPL", "NOPE", "^GSPC"}
    assert all(call[4].value == "index" for call in factory.price.calls)


def test_all_failed_returns_non_zero() -> None:
    code, out, _ = invoke(["prices", "X", "Y", "--source", "fake"], Factory(fail_on={"X", "Y"}))
    assert code == EXIT_ALL_FAILED
    assert "0 OK, 2 fallidas" in out


def test_out_stores_series_through_the_use_case(tmp_path: Path) -> None:
    storage = StorageFactory()
    code, out, _ = invoke(
        ["prices", "AAPL", "^GSPC", "--source", "fake", "--out", str(tmp_path)],
        Factory(),
        storage,
    )
    assert code == EXIT_OK
    assert storage.calls == [(tmp_path, "csv")]
    assert list(storage.repository.saved) == ["AAPL", "^GSPC"]
    assert all(isinstance(s, PriceSeries) for s in storage.repository.saved.values())
    assert "guardado: memory://AAPL" in out


def test_macro_with_as_of_passes_format_and_vintage(tmp_path: Path) -> None:
    factory, storage = Factory(), StorageFactory()
    code, out, _ = invoke(
        [
            "macro",
            "CPIAUCSL",
            "DGS10",
            "--start",
            "2010-01-01",
            "--as-of",
            "2015-06-30",
            "--source",
            "fake",
            "--out",
            str(tmp_path),
            "--format",
            "parquet",
        ],
        factory,
        storage,
    )
    assert code == EXIT_OK
    assert "2015-06-30" in out
    assert factory.calls[0][:2] == (None, "fake")  # macro no construye fuente de precios
    assert storage.calls == [(tmp_path, "parquet")]
    cpi = storage.repository.saved["CPIAUCSL"]
    assert isinstance(cpi, MacroSeries)
    assert cpi.vintage is not None and cpi.vintage.isoformat() == "2015-06-30"


def test_without_out_nothing_is_stored() -> None:
    storage = StorageFactory()
    code, out, _ = invoke(["prices", "AAPL", "--source", "fake"], Factory(), storage)
    assert code == EXIT_OK
    assert storage.calls == []
    assert "guardado" not in out


def test_nothing_is_stored_when_all_fail(tmp_path: Path) -> None:
    storage = StorageFactory()
    code, out, _ = invoke(
        ["prices", "X", "--source", "fake", "--out", str(tmp_path)], Factory(fail_on={"X"}), storage
    )
    assert code == EXIT_ALL_FAILED
    assert storage.repository.saved == {}
    assert "guardado" not in out


def test_invalid_request_returns_usage_code() -> None:
    code, _, err = invoke(
        ["prices", "AAPL", "--start", "2024-02-01", "--end", "2024-01-01", "--source", "fake"],
        Factory(),
    )
    assert code == EXIT_USAGE
    assert "start" in err


def test_invalid_date_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as excinfo:
        invoke(["prices", "AAPL", "--start", "01/02/2024"], Factory())
    assert excinfo.value.code == 2


def test_storage_error_fails_before_downloading(tmp_path: Path) -> None:
    factory = Factory()
    storage = StorageFactory(error=ConfigurationError("Parquet requiere pyarrow"))
    code, _, err = invoke(
        ["prices", "AAPL", "--source", "fake", "--out", str(tmp_path), "--format", "parquet"],
        factory,
        storage,
    )
    assert code == EXIT_USAGE
    assert "pyarrow" in err
    assert factory.price.calls == []


def test_out_without_storage_configured_is_a_usage_error(tmp_path: Path) -> None:
    factory = Factory()
    code, _, err = invoke(["prices", "AAPL", "--source", "fake", "--out", str(tmp_path)], factory)
    assert code == EXIT_USAGE
    assert "almacenamiento" in err
    assert factory.price.calls == []
