"""Integración de las fuentes regulatorias con respuestas reales grabadas (sin red).

SEC EDGAR entra por ``DownloadData`` (fundamentales como ``MacroSeries``); CNMV y ESMA
por ``ListDocuments`` (``RegulatoryDocument``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime

import pandas as pd
import responses

from tests.integration.contract import assert_series_contract
from tests.integration.replay import FAKE_SECRETS, Cassette
from toolkit.bootstrap import build_document_service, build_download_service
from toolkit.domain.documents import DocumentRequest
from toolkit.domain.models import Frequency, MacroRequest

Replay = Callable[[str, str], Cassette]


def _facts(cassette: Cassette, concept: str) -> list[dict]:
    return cassette.json(1)["facts"]["us-gaap"][concept]["units"]["USD"]


# ---------------------------------------------------------------------- SEC EDGAR


def test_sec_edgar_fundamentals_share_one_companyfacts_request(
    replay: Replay, http: responses.RequestsMock
) -> None:
    cassette = replay("sec_edgar", "aapl_fundamentals")
    request = {"start": date(2018, 1, 1), "end": date(2023, 12, 31)}
    result = build_download_service(None, "sec_edgar").download_macro(
        MacroRequest(series_ids=["AAPL/us-gaap/Assets", "AAPL/NetIncomeLoss:FY"], **request)
    )
    assert result.ok, result.errors

    # ticker → CIK y una sola descarga de companyfacts para las dos series
    assert [c.request.url.split("?")[0] for c in http.calls] == [
        i["url"] for i in cassette.interactions
    ]
    # la SEC exige identificarse con User-Agent
    assert all(
        c.request.headers["User-Agent"] == FAKE_SECRETS["SEC_USER_AGENT"] for c in http.calls
    )

    assets = result.series["AAPL/us-gaap/Assets"]
    income = result.series["AAPL/NetIncomeLoss:FY"]
    # los fundamentales se fechan al cierre del periodo fiscal, no al inicio
    assert_series_contract(
        assets, source="sec_edgar", frequency=assets.frequency, period_start=False, **request
    )
    assert_series_contract(
        income, source="sec_edgar", frequency=Frequency.ANNUAL, period_start=False, **request
    )
    raw_assets = {pd.Timestamp(f["end"]): f["val"] for f in _facts(cassette, "Assets")}
    for day, value in assets.data.items():
        assert raw_assets[day] == value
    annual_ends = {
        pd.Timestamp(f["end"]) for f in _facts(cassette, "NetIncomeLoss") if f["fp"] == "FY"
    }
    assert set(income.data.index) <= annual_ends


def test_sec_edgar_as_of_only_uses_facts_filed_by_then(replay: Replay) -> None:
    """*Point-in-time*: nada presentado después de ``as_of`` entra en la serie."""
    cassette = replay("sec_edgar", "aapl_point_in_time")
    as_of = date(2020, 6, 30)
    income = (
        build_download_service(None, "sec_edgar")
        .download_macro(
            MacroRequest(series_ids=["AAPL/NetIncomeLoss:FY"], start=date(2015, 1, 1), as_of=as_of)
        )
        .series["AAPL/NetIncomeLoss:FY"]
    )

    assert income.vintage == as_of
    filed_by_then = [
        f for f in _facts(cassette, "NetIncomeLoss") if date.fromisoformat(f["filed"]) <= as_of
    ]
    for day, value in income.data.items():
        candidates = [f["val"] for f in filed_by_then if pd.Timestamp(f["end"]) == day]
        assert value in candidates, f"{day.date()}: {value} no estaba presentado a {as_of}"
    # el ejercicio fiscal 2020 (cierre 26/09/2020) aún no se conocía
    assert income.end < date(2020, 6, 30)
    later = [f for f in _facts(cassette, "NetIncomeLoss") if f["end"] >= "2020-09-01"]
    assert later, "la grabación debe contener ejercicios posteriores para que el test valga"


# ---------------------------------------------------------------------- CNMV


def test_cnmv_rss_becomes_documents_newest_first(replay: Replay) -> None:
    cassette = replay("cnmv", "latest")
    docs = build_document_service("cnmv").list_documents(DocumentRequest(limit=5))

    items = re.findall(r"<item>.*?</item>", cassette.text(), flags=re.S)
    assert len(docs) == min(len(items), 5) > 0
    assert [d.published_at for d in docs] == sorted((d.published_at for d in docs), reverse=True)
    for doc in docs:
        assert doc.source == "cnmv"
        assert doc.url.startswith("https://www.cnmv.es/")
        assert doc.identifier in doc.url  # nreg=<identifier>
        assert doc.issuer and doc.title.startswith(doc.issuer)
        assert isinstance(doc.published_at, datetime) and doc.published_at.tzinfo is None


def test_cnmv_limit_is_enforced_even_if_feed_has_more(replay: Replay) -> None:
    replay("cnmv", "latest")
    docs = build_document_service("cnmv").list_documents(DocumentRequest(limit=2))
    assert len(docs) == 2


# ---------------------------------------------------------------------- ESMA


def test_esma_firds_files_match_solr_docs(replay: Replay) -> None:
    cassette = replay("esma", "dltins")
    docs = build_document_service("esma").list_documents(
        DocumentRequest("DLTINS", start=date(2026, 11, 1), limit=5)
    )

    raw = cassette.json()["response"]["docs"]
    assert [d.title for d in docs] == [r["file_name"] for r in raw]
    assert [d.url for d in docs] == [r["download_link"] for r in raw]
    assert all(d.category == "DLTINS" and d.source == "esma" for d in docs)
    assert all(d.published_at >= datetime(2026, 11, 1) for d in docs)
    # el filtro de fecha viaja a la API (el mock exige los tres fq grabados)
    assert any("publication_date" in fq for fq in cassette.interactions[0]["query"]["fq"])
