"""De extremo a extremo: el comando ``toolkit`` y el flujo del notebook, sin red.

Todo es real (``bootstrap.main``, CLI, servicios, adaptadores, ``Portfolio``, ficheros)
salvo las respuestas de las APIs, que son las grabadas en ``tests/resources``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.integration.replay import Cassette
from toolkit import bootstrap
from toolkit.bootstrap import build_download_service, build_storage_service
from toolkit.domain.models import DownloadRequest
from toolkit.domain.portfolio import Portfolio

Replay = Callable[[str, str], Cassette]


def toolkit(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    """Ejecuta ``toolkit <argv>`` como el entry point real."""
    code = bootstrap.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_prices_with_partial_failure_saves_csv(
    replay: Replay, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cassette = replay("yahoo", "aapl_daily")
    replay("yahoo", "unknown_ticker")
    code, out, _ = toolkit(
        [
            "prices",
            "AAPL",
            "NOEXISTE123",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-31",
            "--out",
            str(tmp_path),
        ],
        capsys,
    )

    assert code == 0  # al menos una serie OK
    assert "1 OK, 1 fallidas" in out
    assert "NOEXISTE123: yahoo: sin datos" in out
    assert [p.name for p in tmp_path.iterdir()] == ["AAPL.csv"]
    saved = pd.read_csv(tmp_path / "AAPL.csv", index_col="date", parse_dates=True)
    np.testing.assert_allclose(saved["close"], cassette.yahoo_frame("AAPL")["Close"])


def test_macro_vintage_saved_as_parquet(
    replay: Replay, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("pyarrow")
    cassette = replay("fred", "cpi_vintage")
    code, out, _ = toolkit(
        [
            "macro",
            "CPIAUCSL",
            "--source",
            "fred",
            "--start",
            "2014-01-01",
            "--end",
            "2015-06-30",
            "--as-of",
            "2015-06-30",
            "--out",
            str(tmp_path),
            "--format",
            "parquet",
        ],
        capsys,
    )

    assert code == 0 and "2015-06-30" in out
    frame = pd.read_parquet(tmp_path / "CPIAUCSL_asof_2015-06-30.parquet")
    observations = cassette.json(1)["observations"]
    np.testing.assert_allclose(frame["value"], [float(o["value"]) for o in observations])


def test_all_series_failing_exits_with_1(
    replay: Replay, capsys: pytest.CaptureFixture[str]
) -> None:
    replay("ecb", "unknown_series")
    code, out, _ = toolkit(
        [
            "macro",
            "EXR/D.XXX.EUR.SP00.A",
            "--source",
            "ecb",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-31",
        ],
        capsys,
    )
    assert code == 1
    assert "0 OK, 1 fallidas" in out


def test_missing_key_is_a_configuration_error_before_any_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sin clave no se hace ninguna petición (el bloqueo de red lo garantiza)."""
    monkeypatch.delenv("FRED_API_KEY")
    code, _, err = toolkit(["macro", "CPIAUCSL", "--source", "fred"], capsys)
    assert code == 2
    assert "FRED_API_KEY" in err


def test_docs_command_lists_esma_files(replay: Replay, capsys: pytest.CaptureFixture[str]) -> None:
    cassette = replay("esma", "dltins")
    code, out, _ = toolkit(
        ["docs", "--source", "esma", "--query", "DLTINS", "--start", "2026-11-01", "--limit", "5"],
        capsys,
    )
    assert code == 0
    assert "Documentos: 5" in out
    for doc in cassette.json()["response"]["docs"]:
        assert doc["file_name"] in out


def test_notebook_flow_download_portfolio_store_reload(replay: Replay, tmp_path: Path) -> None:
    """El recorrido del notebook: descargar → cartera y Monte Carlo → guardar → releer."""
    replay("yahoo", "aapl_daily")
    replay("yahoo", "msft_daily")
    prices = build_download_service("yahoo", None).download_prices(
        DownloadRequest(tickers=["AAPL", "MSFT"], start=date(2024, 1, 2), end=date(2024, 1, 31))
    )
    assert prices.ok, prices.errors

    portfolio = Portfolio(series=list(prices.series.values()), weights={"AAPL": 0.5, "MSFT": 0.5})
    assert len(portfolio.returns) == 20  # 21 sesiones → 20 retornos comunes
    expected = (prices.series["AAPL"].returns + prices.series["MSFT"].returns).dropna() / 2
    np.testing.assert_allclose(portfolio.portfolio_returns, expected)
    sim = portfolio.monte_carlo(n_steps=21, n_simulations=500, seed=1)
    assert sim.paths.shape == (22, 500) and 0.0 <= sim.prob_loss <= 1.0

    locations = build_storage_service(tmp_path, "csv").store(prices.series)
    assert [Path(p).name for p in locations] == ["AAPL.csv", "MSFT.csv"]
    reloaded = pd.read_csv(locations[1], index_col="date", parse_dates=True)
    pd.testing.assert_frame_equal(
        reloaded, prices.series["MSFT"].data, check_freq=False, check_index_type=False
    )
