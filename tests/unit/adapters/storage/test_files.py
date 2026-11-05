"""Tests del repositorio de ficheros (CSV/Parquet) con series fake."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit.adapters.outbound.storage.files import FileSeriesRepository, safe_filename
from toolkit.domain.errors import ConfigurationError, InvalidRequestError, ProviderError
from toolkit.domain.models import AssetType, Frequency, MacroSeries, PriceSeries
from toolkit.ports.outbound import SeriesRepository

START, END = date(2023, 1, 1), date(2023, 3, 31)


def prices(ticker: str) -> PriceSeries:
    return FakePriceProvider().fetch_prices(ticker, START, END, Frequency.DAILY, AssetType.EQUITY)


def macro(series_id: str, as_of: date | None = None) -> MacroSeries:
    return FakeMacroProvider().fetch_series(series_id, date(2010, 1, 1), None, as_of)


def test_satisfies_outbound_port(tmp_path: Path) -> None:
    assert isinstance(FileSeriesRepository(tmp_path), SeriesRepository)


def test_writes_one_csv_per_price_series(tmp_path: Path) -> None:
    out = tmp_path / "nuevo"  # se crea al guardar
    repo = FileSeriesRepository(out)
    locations = repo.save({"AAPL": prices("AAPL"), "^GSPC": prices("^GSPC")})
    assert locations == [str(out / "AAPL.csv"), str(out / "_GSPC.csv")]
    frame = pd.read_csv(out / "_GSPC.csv", index_col="date", parse_dates=True)
    assert list(frame.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    pd.testing.assert_series_equal(
        frame["close"], prices("^GSPC").data["close"], check_freq=False, check_index_type=False
    )


def test_macro_vintage_gets_suffix_and_value_column(tmp_path: Path) -> None:
    repo = FileSeriesRepository(tmp_path)
    [latest, vintage] = repo.save(
        {"CPIAUCSL": macro("CPIAUCSL"), "EXR/D.USD": macro("EXR/D.USD", date(2015, 6, 30))}
    )
    assert Path(latest).name == "CPIAUCSL.csv"
    assert Path(vintage).name == "EXR_D.USD_asof_2015-06-30.csv"
    frame = pd.read_csv(vintage, index_col="date", parse_dates=True)
    assert list(frame.columns) == ["value"]
    assert frame.index.max() <= pd.Timestamp("2015-06-30")


def test_parquet_round_trip(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    [path] = FileSeriesRepository(tmp_path, "PARQUET").save({"AAPL": prices("AAPL")})
    assert Path(path).suffix == ".parquet"
    pd.testing.assert_frame_equal(pd.read_parquet(path), prices("AAPL").data, check_freq=False)


def test_parquet_without_pyarrow_fails_on_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "toolkit.adapters.outbound.storage.files.importlib.util.find_spec", lambda _: None
    )
    with pytest.raises(ConfigurationError, match="pyarrow"):
        FileSeriesRepository(tmp_path, "parquet")


def test_unknown_format_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError, match="xlsx"):
        FileSeriesRepository(tmp_path, "xlsx")


def test_unwritable_directory_raises_provider_error(tmp_path: Path) -> None:
    blocker = tmp_path / "fichero"
    blocker.write_text("no soy un directorio")
    with pytest.raises(ProviderError, match="no se puede crear"):
        FileSeriesRepository(blocker / "sub").save({"AAPL": prices("AAPL")})


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [("^GSPC", "_GSPC"), ("EXR/D.USD.EUR.SP00.A", "EXR_D.USD.EUR.SP00.A"), ("BTC-USD", "BTC-USD")],
)
def test_safe_filename(identifier: str, expected: str) -> None:
    assert safe_filename(identifier) == expected
