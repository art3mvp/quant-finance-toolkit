"""Tests de la CLI con un servicio construido sobre proveedores fake (sin red)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit.adapters.inbound.cli import EXIT_ALL_FAILED, EXIT_OK, EXIT_USAGE, run
from toolkit.ports.inbound import DownloadData
from toolkit.services.download_service import DownloadService


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


def invoke(argv: list[str], factory: Factory) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        argv,
        service_factory=factory,
        price_sources=["fake", "yahoo"],
        macro_sources=["fake", "fred"],
        stdout=out,
        stderr=err,
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


def test_prices_out_writes_csv(tmp_path: Path) -> None:
    code, out, _ = invoke(
        ["prices", "AAPL", "^GSPC", "--source", "fake", "--out", str(tmp_path)], Factory()
    )
    assert code == EXIT_OK
    assert (tmp_path / "AAPL.csv").exists()
    frame = pd.read_csv(tmp_path / "_GSPC.csv", index_col="date", parse_dates=True)
    assert list(frame.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    assert "guardado" in out


def test_macro_with_as_of_and_parquet(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    factory = Factory()
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
    )
    assert code == EXIT_OK
    assert "2015-06-30" in out
    assert factory.calls[0][:2] == (None, "fake")  # macro no construye fuente de precios
    frame = pd.read_parquet(tmp_path / "CPIAUCSL_asof_2015-06-30.parquet")
    assert list(frame.columns) == ["value"]
    assert frame.index.max() <= pd.Timestamp("2015-06-30")


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


def test_parquet_without_pyarrow_fails_before_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("toolkit.adapters.inbound.cli.importlib.util.find_spec", lambda _: None)
    factory = Factory()
    code, _, err = invoke(
        ["prices", "AAPL", "--source", "fake", "--out", str(tmp_path), "--format", "parquet"],
        factory,
    )
    assert code == EXIT_USAGE
    assert "pyarrow" in err
    assert factory.price.calls == []
