"""Integración de las fuentes especializadas (cripto y energía) sin red."""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import pytest
import responses

from tests.integration.contract import assert_series_contract
from tests.integration.replay import FAKE_SECRETS, Cassette
from toolkit import bootstrap
from toolkit.adapters.outbound.specialized.coingecko import CoinGeckoPriceProvider
from toolkit.bootstrap import build_download_service
from toolkit.domain.models import AssetType, DownloadRequest, Frequency, MacroRequest

Replay = Callable[[str, str], Cassette]
OCT = {"start": date(2026, 10, 1), "end": date(2026, 10, 31)}


@pytest.fixture
def coingecko_clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[date], None]:
    """CoinGecko calcula ``days`` desde hoy: se fija la fecha de la grabación."""

    def freeze(today: date) -> None:
        monkeypatch.setitem(
            bootstrap.PRICE_PROVIDERS,
            "coingecko",
            lambda: CoinGeckoPriceProvider(
                api_key=os.getenv("COINGECKO_API_KEY"),
                plan=os.getenv("COINGECKO_API_PLAN", "demo"),
                today=lambda: today,
            ),
        )

    return freeze


def test_coingecko_daily_closes_without_inventing_candles(
    replay: Replay, http: responses.RequestsMock, coingecko_clock: Callable[[date], None]
) -> None:
    cassette = replay("coingecko", "bitcoin_daily")
    coingecko_clock(cassette.recorded_on)
    result = build_download_service("coingecko", None).download_prices(
        DownloadRequest(tickers=["bitcoin"], asset_type=AssetType.CRYPTO, **OCT)
    )
    assert result.ok, result.errors
    btc = result.series["bitcoin"]

    assert_series_contract(btc, source="coingecko", frequency=Frequency.DAILY, **OCT)
    assert btc.asset_type is AssetType.CRYPTO
    # cotiza 24/7: los 31 días de octubre, fines de semana incluidos
    assert list(btc.data.index) == list(pd.date_range("2026-10-01", "2026-10-31"))
    raw = {pd.Timestamp(ms, unit="ms"): price for ms, price in cassette.json()["prices"]}
    np.testing.assert_allclose(btc.data["close"], [raw[d] for d in btc.data.index])
    # el plan gratuito no da OHLC diario: open/high/low quedan a NaN, no se inventan
    assert btc.data[["open", "high", "low"]].isna().all().all()
    assert not math.isnan(btc.data["volume"].iloc[0])
    assert http.calls[0].request.headers["x-cg-demo-api-key"] == FAKE_SECRETS["COINGECKO_API_KEY"]


def test_coingecko_unknown_coin(replay: Replay, coingecko_clock: Callable[[date], None]) -> None:
    cassette = replay("coingecko", "unknown_coin")
    coingecko_clock(cassette.recorded_on)
    result = build_download_service("coingecko", None).download_prices(
        DownloadRequest(tickers=["noexiste-123"], asset_type=AssetType.CRYPTO, **OCT)
    )
    assert result.all_failed
    assert "no encontrado" in result.errors["noexiste-123"]


def test_eia_daily_wti_is_sorted_and_clipped(replay: Replay) -> None:
    cassette = replay("eia", "wti_daily")
    request = {"start": date(2024, 1, 1), "end": date(2024, 1, 31)}
    wti = (
        build_download_service(None, "eia")
        .download_macro(MacroRequest(series_ids=["PET.RWTC.D"], **request))
        .series["PET.RWTC.D"]
    )

    assert_series_contract(wti, source="eia", frequency=Frequency.DAILY, **request)
    rows = cassette.json()["response"]["data"]
    january = sorted(
        (r for r in rows if r["period"].startswith("2024-01")), key=lambda r: r["period"]
    )
    assert len(rows) > len(january)  # la API ignora el rango: se filtra en local
    assert wti.units == rows[0]["units"] and wti.name == rows[0]["series-description"]
    assert list(wti.data.index) == list(pd.to_datetime([r["period"] for r in january]))
    np.testing.assert_allclose(wti.data, [r["value"] for r in january])
