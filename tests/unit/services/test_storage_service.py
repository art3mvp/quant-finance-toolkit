"""Tests del caso de uso ``StoreSeries`` sobre un repositorio en memoria."""

from __future__ import annotations

from datetime import date

import pytest

from tests.fakes import FakePriceProvider, FakeSeriesRepository
from toolkit.domain.models import AssetType, Frequency
from toolkit.ports.inbound import StoreSeries
from toolkit.ports.outbound import SeriesRepository
from toolkit.services.storage_service import StorageService


def test_fake_repository_satisfies_port() -> None:
    assert isinstance(FakeSeriesRepository(), SeriesRepository)


def test_satisfies_inbound_port() -> None:
    assert isinstance(StorageService(FakeSeriesRepository()), StoreSeries)


def test_rejects_objects_that_do_not_satisfy_port() -> None:
    with pytest.raises(TypeError):
        StorageService(object())  # type: ignore[arg-type]


def test_delegates_to_repository_in_order() -> None:
    repo = FakeSeriesRepository()
    provider = FakePriceProvider()
    series = {
        t: provider.fetch_prices(
            t, date(2023, 1, 1), date(2023, 2, 1), Frequency.DAILY, AssetType.EQUITY
        )
        for t in ("MSFT", "AAPL")
    }
    assert StorageService(repo).store(series) == ["memory://MSFT", "memory://AAPL"]
    assert repo.saved == series


def test_empty_input_does_not_touch_repository() -> None:
    class Exploding(FakeSeriesRepository):
        def save(self, series):  # type: ignore[no-untyped-def]
            raise AssertionError("no debería llamarse")

    assert StorageService(Exploding()).store({}) == []
