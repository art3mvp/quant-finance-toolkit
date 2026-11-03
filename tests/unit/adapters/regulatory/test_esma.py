"""Tests del adaptador ESMA FIRDS con una respuesta Solr real recortada (sin red)."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from toolkit.adapters.outbound.regulatory.esma import (
    DEFAULT_URL,
    EsmaDocumentProvider,
    parse_response,
)
from toolkit.domain.errors import InvalidRequestError, ProviderError
from toolkit.ports.outbound import DocumentProvider

PAYLOAD = {
    "response": {
        "numFound": 2,
        "docs": [
            {"id": "lastModification", "file_name": "", "publication_date": "2026-11-03T06:29:26Z"},
            {
                "id": "119576",
                "file_name": "DLTINS_20261103_01of04.zip",
                "file_type": "DLTINS",
                "publication_date": "2026-11-03T00:00:00Z",
                "download_link": "https://firds.esma.europa.eu/firds/DLTINS_20261103_01of04.zip",
            },
        ],
    }
}


@pytest.fixture
def provider() -> EsmaDocumentProvider:
    return EsmaDocumentProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(EsmaDocumentProvider(), DocumentProvider)


@responses.activate
def test_builds_solr_query_and_parses_files(provider: EsmaDocumentProvider) -> None:
    responses.get(DEFAULT_URL, json=PAYLOAD)
    docs = provider.fetch_documents("dltins", date(2026, 11, 1), date(2026, 11, 3), 5)
    params = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert params["fq"] == [
        "download_link:*",
        "publication_date:[2026-11-01T00:00:00Z TO 2026-11-04T00:00:00Z}",
        "file_type:DLTINS",
    ]
    assert params["rows"] == ["5"]
    assert len(docs) == 1  # lastModification se descarta
    assert docs[0].identifier == "119576"
    assert docs[0].category == "DLTINS"
    assert docs[0].published_at == datetime(2026, 11, 3)


def test_rejects_solr_injection(provider: EsmaDocumentProvider) -> None:
    with pytest.raises(InvalidRequestError):
        provider.fetch_documents("DLTINS OR *:*", None, None, 5)


def test_malformed_payloads() -> None:
    with pytest.raises(ProviderError):
        parse_response({"error": "x"})
    with pytest.raises(ProviderError):
        parse_response({"response": {"docs": [{"download_link": "https://x", "id": "1"}]}})
