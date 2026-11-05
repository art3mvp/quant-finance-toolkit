"""Tests del adaptador CNMV con un RSS real recortado (sin red)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import responses

from toolkit.adapters.outbound.regulatory.cnmv import DEFAULT_URL, CnmvDocumentProvider, parse_feed
from toolkit.domain.errors import ProviderError
from toolkit.ports.outbound import DocumentProvider

SUMMARY = "La Sociedad comunica &amp; informa"


def item(nreg: int, issuer: str, stamp: str, pub: str, category: str) -> str:
    link = f"https://www.cnmv.es/Portal/Otra-Informacion-Relevante/Resultado-OIR.aspx?nreg={nreg}"
    return f"""
    <item>
      <Title>{issuer}</Title>
      <link><![CDATA[{link}]]></link>
      <guid isPermaLink="true"><![CDATA[{link}]]></guid>
      <pubDate>{pub}</pubDate>
      <description><![CDATA[<p><b>{stamp}  </b> {category}<BR/><BR/>{SUMMARY}</p>]]></description>
    </item>"""


BUYBACK = "Programas de recompra de acciones"
RSS = f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><Channel><title>CNMV - Otra informacion relevante.</title>
{item(43479, "INDRA SISTEMAS, S.A.", "18:10  02/11/2026", "Mon, 02 Nov 2026 17:10:00 GMT", "Otros")}
{item(43480, "IZERTIS, S.A.", "19:44  03/11/2026", "Tue, 03 Nov 2026 18:44:49 GMT", BUYBACK)}
</Channel></rss>"""


@pytest.fixture
def provider() -> CnmvDocumentProvider:
    return CnmvDocumentProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(CnmvDocumentProvider(), DocumentProvider)


def test_parse_feed_normalizes_items() -> None:
    docs = parse_feed(RSS)
    izertis = docs[1]
    assert izertis.identifier == "43480"
    assert izertis.issuer == "IZERTIS, S.A."
    assert izertis.category == "Programas de recompra de acciones"
    assert izertis.summary == "La Sociedad comunica & informa"
    assert izertis.title == "IZERTIS, S.A.: Programas de recompra de acciones"
    assert izertis.published_at == datetime(2026, 11, 3, 18, 44, 49)  # UTC tz-naive


@responses.activate
def test_fetch_filters_and_sorts_newest_first(provider: CnmvDocumentProvider) -> None:
    responses.get(DEFAULT_URL, body=RSS, content_type="text/xml; charset=utf-8")
    assert [d.identifier for d in provider.fetch_documents(None, None, None, 10)] == [
        "43480",
        "43479",
    ]
    assert [d.identifier for d in provider.fetch_documents("indra", None, None, 10)] == ["43479"]
    assert provider.fetch_documents(None, date(2026, 11, 3), None, 10)[0].identifier == "43480"
    assert len(provider.fetch_documents(None, None, None, 1)) == 1


def test_invalid_xml_or_items_raise_provider_error() -> None:
    with pytest.raises(ProviderError, match="ilegible"):
        parse_feed("<rss><item>")
    with pytest.raises(ProviderError, match="inválido"):
        parse_feed("<rss><item><Title>X</Title></item></rss>")  # sin link ni fecha
