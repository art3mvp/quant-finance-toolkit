"""Tests del DownloadService usando los proveedores fake (sin red)."""

from __future__ import annotations

import time
from datetime import date

import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit.domain.errors import ConfigurationError, InvalidRequestError
from toolkit.domain.models import (
    AssetType,
    DownloadRequest,
    Frequency,
    MacroRequest,
    MacroSeries,
    PriceSeries,
)
from toolkit.ports.inbound import DownloadData
from toolkit.services.download_service import DownloadService

START, END = date(2023, 1, 1), date(2023, 6, 30)


class SlowFirstProvider(FakePriceProvider):
    """Retrasa los primeros tickers para que terminen después que los últimos."""

    def __init__(self, delays: dict[str, float], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.delays = delays

    def fetch_prices(self, ticker, start, end, interval, asset_type):  # type: ignore[no-untyped-def]
        time.sleep(self.delays.get(ticker, 0.0))
        return super().fetch_prices(ticker, start, end, interval, asset_type)


class ExplodingProvider(FakePriceProvider):
    def fetch_prices(self, ticker, start, end, interval, asset_type):  # type: ignore[no-untyped-def]
        if ticker == "BUG":
            raise RuntimeError("bug inesperado")
        return super().fetch_prices(ticker, start, end, interval, asset_type)


class MisconfiguredMacro(FakeMacroProvider):
    def fetch_series(self, series_id, start, end, as_of):  # type: ignore[no-untyped-def]
        raise ConfigurationError("falta FRED_API_KEY")


def test_service_implements_inbound_port() -> None:
    assert isinstance(DownloadService(FakePriceProvider()), DownloadData)


def test_batch_with_partial_failures_preserves_order() -> None:
    tickers = ["AAPL", "BAD1", "MSFT", "BAD2", "^GSPC"]
    provider = SlowFirstProvider(
        delays={"AAPL": 0.15, "MSFT": 0.05}, not_found={"BAD1"}, fail_on={"BAD2"}
    )
    service = DownloadService(provider, max_workers=5)

    result = service.download_prices(DownloadRequest(tickers=tickers, start=START, end=END))

    assert result.n_success == 3
    assert result.n_failed == 2
    assert not result.ok
    assert list(result.series) == ["AAPL", "MSFT", "^GSPC"]
    assert list(result.errors) == ["BAD1", "BAD2"]
    assert all(isinstance(s, PriceSeries) for s in result.series.values())


def test_downloads_run_in_parallel() -> None:
    tickers = [f"T{i}" for i in range(4)]
    provider = SlowFirstProvider(delays=dict.fromkeys(tickers, 0.2))
    service = DownloadService(provider, max_workers=4)
    t0 = time.perf_counter()
    service.download_prices(DownloadRequest(tickers=tickers, start=START, end=END))
    assert time.perf_counter() - t0 < 0.6  # en serie serían >= 0.8 s


def test_unexpected_exception_does_not_break_batch() -> None:
    service = DownloadService(ExplodingProvider())
    result = service.download_prices(DownloadRequest(tickers=["AAPL", "BUG"], start=START, end=END))
    assert list(result.series) == ["AAPL"]
    assert "RuntimeError" in result.errors["BUG"]


def test_tickers_are_normalized_and_deduplicated() -> None:
    provider = FakePriceProvider()
    service = DownloadService(provider)
    result = service.download_prices(
        DownloadRequest(tickers=[" aapl", "AAPL", "msft "], start=START, end=END)
    )
    assert list(result.series) == ["AAPL", "MSFT"]
    assert sorted(call[0] for call in provider.calls) == ["AAPL", "MSFT"]


def test_request_parameters_are_forwarded() -> None:
    provider = FakePriceProvider()
    DownloadService(provider).download_prices(
        DownloadRequest(
            tickers=["^IBEX"],
            start=START,
            end=END,
            interval=Frequency.WEEKLY,
            asset_type=AssetType.INDEX,
        )
    )
    assert provider.calls == [("^IBEX", START, END, Frequency.WEEKLY, AssetType.INDEX)]


@pytest.mark.parametrize(
    "request_",
    [
        DownloadRequest(tickers=[]),
        DownloadRequest(tickers=["  "]),
        DownloadRequest(tickers="AAPL"),  # type: ignore[arg-type]
        DownloadRequest(tickers=["AAPL"], start=date(2024, 1, 2), end=date(2024, 1, 1)),
    ],
)
def test_invalid_price_requests(request_: DownloadRequest) -> None:
    with pytest.raises(InvalidRequestError):
        DownloadService(FakePriceProvider()).download_prices(request_)


def test_invalid_request_error_is_value_error() -> None:
    with pytest.raises(ValueError):
        DownloadService(FakePriceProvider()).download_prices(DownloadRequest(tickers=[]))


def test_rejects_objects_that_do_not_satisfy_ports() -> None:
    with pytest.raises(TypeError):
        DownloadService(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        DownloadService(FakePriceProvider(), macro_provider=object())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DownloadService(FakePriceProvider(), max_workers=0)


class TestMacro:
    def test_batch_with_failure_and_vintage(self) -> None:
        service = DownloadService(FakePriceProvider(), FakeMacroProvider(not_found={"NOPE"}))
        result = service.download_macro(
            MacroRequest(
                series_ids=["cpiaucsl", "NOPE", "DGS10"],
                start=date(2010, 1, 1),
                end=date(2020, 1, 1),
                as_of=date(2015, 6, 30),
            )
        )
        assert list(result.series) == ["CPIAUCSL", "DGS10"]
        assert list(result.errors) == ["NOPE"]
        assert all(isinstance(s, MacroSeries) for s in result.series.values())
        assert all(s.vintage == date(2015, 6, 30) for s in result.series.values())

    def test_without_macro_provider_raises_configuration_error(self) -> None:
        service = DownloadService(FakePriceProvider())
        with pytest.raises(ConfigurationError):
            service.download_macro(MacroRequest(series_ids=["CPIAUCSL"]))

    def test_configuration_error_aborts_whole_batch(self) -> None:
        service = DownloadService(FakePriceProvider(), MisconfiguredMacro())
        with pytest.raises(ConfigurationError, match="FRED_API_KEY"):
            service.download_macro(MacroRequest(series_ids=["A", "B"]))

    def test_invalid_macro_request(self) -> None:
        service = DownloadService(FakePriceProvider(), FakeMacroProvider())
        with pytest.raises(InvalidRequestError):
            service.download_macro(MacroRequest(series_ids=[]))
