"""Tests de integración contra servicios reales. Excluidos por defecto.

Ejecutar con::

    pytest -m network
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from toolkit.bootstrap import build_download_service, load_settings
from toolkit.domain.models import AssetType, DownloadRequest, MacroRequest

pytestmark = pytest.mark.network


def test_yahoo_downloads_aapl_and_gspc() -> None:
    service = build_download_service("yahoo", None)
    for ticker, asset_type in [("AAPL", AssetType.EQUITY), ("^GSPC", AssetType.INDEX)]:
        result = service.download_prices(
            DownloadRequest(
                tickers=[ticker],
                start=date(2024, 1, 1),
                end=date(2024, 3, 31),
                asset_type=asset_type,
            )
        )
        assert result.ok, result.errors
        series = result.series[ticker]
        assert series.n_obs > 50
        assert series.start >= date(2024, 1, 1)
        assert series.end <= date(2024, 3, 31)
        assert series.data.index.tz is None
        assert series.currency == "USD"


def test_fred_downloads_cpi_with_vintage() -> None:
    load_settings()
    if not os.getenv("FRED_API_KEY"):
        pytest.skip("FRED_API_KEY no configurada")
    service = build_download_service("yahoo", "fred")
    result = service.download_macro(
        MacroRequest(
            series_ids=["CPIAUCSL"],
            start=date(2010, 1, 1),
            end=date(2015, 12, 31),
            as_of=date(2015, 6, 30),
        )
    )
    assert result.ok, result.errors
    series = result.series["CPIAUCSL"]
    assert series.vintage == date(2015, 6, 30)
    assert series.end <= date(2015, 6, 30)
