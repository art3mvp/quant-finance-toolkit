"""Integración de las fuentes macro y fiscal con respuestas reales grabadas (sin red).

``bootstrap`` → ``DownloadService`` → adaptador real → ``HttpClient`` → respuesta
grabada → ``MacroSeries``. Los valores esperados se leen del cuerpo grabado.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd

from tests.integration.contract import assert_series_contract
from tests.integration.replay import Cassette
from toolkit.bootstrap import build_download_service
from toolkit.domain.models import Frequency, MacroRequest, MacroSeries

Replay = Callable[[str, str], Cassette]


def download(source: str, series_id: str, **kwargs: object) -> MacroSeries:
    result = build_download_service(None, source).download_macro(
        MacroRequest(series_ids=[series_id], **kwargs)  # type: ignore[arg-type]
    )
    assert result.ok, result.errors
    return result.series[series_id]


def month_starts(periods: list[str]) -> list[pd.Timestamp]:
    return [pd.Period(p, freq="M").start_time for p in periods]


# ---------------------------------------------------------------------- FRED / ALFRED

CPI = {"start": date(2014, 1, 1), "end": date(2015, 6, 30)}


def test_fred_latest_revision_matches_observations(replay: Replay) -> None:
    cassette = replay("fred", "cpi_latest")
    cpi = download("fred", "CPIAUCSL", **CPI)

    assert_series_contract(cpi, source="fred", frequency=Frequency.MONTHLY, **CPI)
    meta = cassette.json(0)["seriess"][0]
    assert cpi.name == meta["title"] and cpi.units == meta["units"]
    assert cpi.vintage is None
    observations = cassette.json(1)["observations"]
    assert list(cpi.data.index) == list(pd.to_datetime([o["date"] for o in observations]))
    np.testing.assert_allclose(cpi.data, [float(o["value"]) for o in observations])


def test_fred_vintage_returns_data_as_published_that_day(replay: Replay) -> None:
    """ALFRED: con ``as_of`` se ve el dato publicado entonces, no la revisión actual."""
    replay("fred", "cpi_latest")
    replay("fred", "cpi_vintage")
    latest = download("fred", "CPIAUCSL", **CPI)
    vintage = download("fred", "CPIAUCSL", as_of=date(2015, 6, 30), **CPI)

    assert_series_contract(vintage, source="fred", frequency=Frequency.MONTHLY, **CPI)
    assert vintage.vintage == date(2015, 6, 30)
    # el 30/06/2015 aún no se había publicado el IPC de junio
    assert vintage.end == date(2015, 5, 1) and latest.end == date(2015, 6, 1)
    common = vintage.data.index.intersection(latest.data.index)
    revisions = (latest.data[common] - vintage.data[common]).abs()
    assert (revisions > 1e-9).sum() > 0, "la serie actual debe incluir revisiones"


# ---------------------------------------------------------------------- SDMX (BCE, Eurostat, BIS)


def test_ecb_daily_exchange_rate(replay: Replay) -> None:
    cassette = replay("ecb", "eurusd_daily")
    request = {"start": date(2024, 1, 1), "end": date(2024, 1, 31)}
    eurusd = download("ecb", "EXR/D.USD.EUR.SP00.A", **request)

    assert_series_contract(eurusd, source="ecb", frequency=Frequency.DAILY, **request)
    raw = cassette.csv()
    assert eurusd.name == raw["TITLE"].iloc[0] and eurusd.units == raw["UNIT"].iloc[0]
    assert list(eurusd.data.index) == list(pd.to_datetime(raw["TIME_PERIOD"]))
    np.testing.assert_allclose(eurusd.data, raw["OBS_VALUE"].astype(float))


def test_eurostat_monthly_inflation_is_dated_at_month_start(replay: Replay) -> None:
    cassette = replay("eurostat", "hicp_spain")
    request = {"start": date(2023, 1, 1), "end": date(2023, 12, 31)}
    hicp = download("eurostat", "prc_hicp_manr/M.RCH_A.CP00.ES", **request)

    assert_series_contract(hicp, source="eurostat", frequency=Frequency.MONTHLY, **request)
    raw = cassette.csv()
    assert list(hicp.data.index) == month_starts(list(raw["TIME_PERIOD"]))  # "2023-01"
    np.testing.assert_allclose(hicp.data, raw["OBS_VALUE"].astype(float))


def test_bis_policy_rate(replay: Replay) -> None:
    cassette = replay("bis", "policy_rate_us")
    request = {"start": date(2023, 1, 1), "end": date(2023, 12, 31)}
    rate = download("bis", "WS_CBPOL/M.US", **request)

    assert_series_contract(rate, source="bis", frequency=Frequency.MONTHLY, **request)
    raw = cassette.csv()
    assert list(rate.data.index) == month_starts(list(raw["TIME_PERIOD"]))
    np.testing.assert_allclose(rate.data, raw["OBS_VALUE"].astype(float))


# ---------------------------------------------------------------------- Banco Mundial


def test_world_bank_annual_gdp_is_sorted_and_dated_at_year_start(replay: Replay) -> None:
    cassette = replay("world_bank", "gdp_spain")
    request = {"start": date(2015, 1, 1), "end": date(2023, 12, 31)}
    gdp = download("world_bank", "ESP/NY.GDP.MKTP.CD", **request)

    assert_series_contract(gdp, source="world_bank", frequency=Frequency.ANNUAL, **request)
    rows = sorted(cassette.json()[1], key=lambda r: r["date"])  # la API los da descendentes
    assert gdp.name == rows[0]["indicator"]["value"]
    assert list(gdp.data.index) == [pd.Timestamp(f"{r['date']}-01-01") for r in rows]
    np.testing.assert_allclose(gdp.data, [r["value"] for r in rows])


# ---------------------------------------------------------------------- Banco de España


def test_banco_espana_clips_full_history_to_requested_range(replay: Replay) -> None:
    cassette = replay("banco_espana", "euribor_1y")
    request = {"start": date(2023, 1, 1), "end": date(2023, 12, 31)}
    euribor = download("banco_espana", "D_1NBAF472", **request)

    assert_series_contract(euribor, source="banco_espana", frequency=Frequency.MONTHLY, **request)
    raw = cassette.json()[0]
    assert euribor.name == raw["descripcion"] and euribor.units == raw["simbolo"]
    # la API devuelve todo el histórico (rango=MAX); el adaptador recorta en local
    full = pd.Series(raw["valores"], index=month_starts([f[:7] for f in raw["fechas"]]))
    expected = full.sort_index()["2023-01-01":"2023-12-01"]
    assert len(full) > len(expected) == euribor.n_obs == 12
    np.testing.assert_allclose(euribor.data, expected)


# ---------------------------------------------------------------------- Tesoro de EE. UU.


def test_us_treasury_filters_rows_and_redates_month_end(replay: Replay) -> None:
    cassette = replay("us_treasury", "bills_avg_rate")
    series_id = (
        "v2/accounting/od/avg_interest_rates:avg_interest_rate_amt:security_desc=Treasury Bills"
    )
    request = {"start": date(2024, 1, 1), "end": date(2024, 6, 30)}
    bills = download("us_treasury", series_id, **request)

    assert_series_contract(bills, source="us_treasury", frequency=Frequency.MONTHLY, **request)
    rows = [r for r in cassette.json()["data"] if r["security_desc"] == "Treasury Bills"]
    assert len(cassette.json()["data"]) > len(rows)  # el endpoint mezcla tipos de valor
    # record_date es fin de mes (2024-01-31) y se refecha al inicio (2024-01-01)
    assert list(bills.data.index) == month_starts([r["record_date"][:7] for r in rows])
    np.testing.assert_allclose(bills.data, [float(r["avg_interest_rate_amt"]) for r in rows])
