"""Integración de las fuentes de mercado con respuestas reales grabadas (sin red).

Cada test recorre el camino completo: ``bootstrap`` → ``DownloadService`` → adaptador
real → (``HttpClient`` →) respuesta grabada → ``PriceSeries``. Los valores esperados se
leen del cuerpo grabado, no del adaptador.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd

from tests.integration.contract import assert_series_contract
from tests.integration.replay import Cassette
from toolkit.bootstrap import build_download_service
from toolkit.domain.models import AssetType, DownloadRequest, Frequency, PriceSeries

Replay = Callable[[str, str], Cassette]
JAN = {"start": date(2024, 1, 2), "end": date(2024, 1, 31)}


def download(source: str, tickers: list[str], **kwargs: object) -> dict[str, PriceSeries]:
    result = build_download_service(source, None).download_prices(
        DownloadRequest(tickers=tickers, **kwargs)  # type: ignore[arg-type]
    )
    assert result.ok, result.errors
    return result.series


# ---------------------------------------------------------------------- Yahoo


def test_yahoo_daily_matches_yfinance_history(replay: Replay) -> None:
    cassette = replay("yahoo", "aapl_daily")
    aapl = download("yahoo", ["AAPL"], **JAN)["AAPL"]

    raw = cassette.yahoo_frame("AAPL")
    assert_series_contract(aapl, source="yahoo", frequency=Frequency.DAILY, **JAN)
    assert aapl.name == "Apple Inc." and aapl.currency == "USD"
    assert list(aapl.data.columns) == ["open", "high", "low", "close", "adj_close", "volume"]
    # la sesión se conserva: la fecha local del mercado, sin zona horaria
    assert list(aapl.data.index) == list(raw.index.tz_localize(None).normalize())
    np.testing.assert_allclose(aapl.data["close"], raw["Close"])
    np.testing.assert_allclose(aapl.data["adj_close"], raw["Adj Close"])
    # los retornos usan adj_close (dividendos), no close
    assert aapl.mean_return == np.mean(raw["Adj Close"].pct_change().dropna())


def test_yahoo_monthly_index_is_dated_at_month_start(replay: Replay) -> None:
    replay("yahoo", "gspc_monthly")
    gspc = download(
        "yahoo",
        ["^GSPC"],
        start=date(2023, 1, 1),
        end=date(2023, 12, 31),
        interval=Frequency.MONTHLY,
        asset_type=AssetType.INDEX,
    )["^GSPC"]

    assert_series_contract(gspc, source="yahoo", frequency=Frequency.MONTHLY)
    assert gspc.asset_type is AssetType.INDEX and gspc.name == "S&P 500"
    assert list(gspc.data.index) == list(pd.date_range("2023-01-01", periods=12, freq="MS"))


# ---------------------------------------------------------------------- Alpha Vantage


def test_alpha_vantage_weekly_bars_are_redated_to_monday(replay: Replay) -> None:
    cassette = replay("alpha_vantage", "ibm_weekly")
    request = {"start": date(2024, 1, 1), "end": date(2024, 3, 31)}
    ibm = download("alpha_vantage", ["IBM"], interval=Frequency.WEEKLY, **request)["IBM"]

    assert_series_contract(ibm, source="alpha_vantage", frequency=Frequency.WEEKLY, **request)
    # Alpha Vantage fecha cada barra en la última sesión de la semana (viernes)
    bars = cassette.json()["Weekly Time Series"]
    expected = {
        (pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).weekday())): float(b["4. close"])
        for day, b in bars.items()
    }
    expected = {
        k: v for k, v in sorted(expected.items()) if request["start"] <= k.date() <= request["end"]
    }
    assert list(ibm.data.index) == list(expected)
    np.testing.assert_allclose(ibm.data["close"], list(expected.values()))
    assert "adj_close" not in ibm.data.columns  # el plan gratuito no la ofrece


# ---------------------------------------------------------------------- Twelve Data


def test_twelve_data_daily_matches_api_values(replay: Replay) -> None:
    cassette = replay("twelve_data", "aapl_daily")
    aapl = download("twelve_data", ["AAPL"], **JAN)["AAPL"]

    assert_series_contract(aapl, source="twelve_data", frequency=Frequency.DAILY, **JAN)
    values = cassette.json()["values"]
    assert list(aapl.data.index) == list(pd.to_datetime([v["datetime"] for v in values]))
    np.testing.assert_allclose(aapl.data["close"], [float(v["close"]) for v in values])
    assert aapl.currency == cassette.json()["meta"]["currency"]


def test_same_request_gives_same_contract_across_sources(replay: Replay) -> None:
    """Cambiar de fuente no cambia el contrato: mismas sesiones y mismos cierres."""
    replay("yahoo", "aapl_daily")
    replay("twelve_data", "aapl_daily")
    yahoo = download("yahoo", ["AAPL"], **JAN)["AAPL"]
    twelve = download("twelve_data", ["AAPL"], **JAN)["AAPL"]

    assert list(yahoo.data.index) == list(twelve.data.index)
    np.testing.assert_allclose(yahoo.data["close"], twelve.data["close"], rtol=1e-6)
    common = ["open", "high", "low", "close", "volume"]
    assert set(common) <= set(yahoo.data.columns) and set(common) <= set(twelve.data.columns)
