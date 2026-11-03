"""Adaptador outbound de la CNMV: "Otra información relevante" (RSS).

Feed: ``RSS.asmx/GetNoticiasCNMV``. Cada ``<item>`` es una comunicación de un emisor:
    * ``<Title>`` (con mayúscula en el feed real) → emisor.
    * ``<description>`` (HTML) → ``hora fecha`` + categoría + ``<BR/>`` + resumen.
    * ``<link>`` → ficha; su ``nreg`` es el número de registro (identificador).

Limitación de la fuente: el feed solo contiene lo publicado desde el cierre de la sesión
anterior; no hay histórico. ``start``/``end`` y ``query`` (texto contenido en el emisor,
sin distinguir mayúsculas) se aplican en local.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from toolkit.adapters.outbound._http import HttpClient
from toolkit.domain.documents import RegulatoryDocument
from toolkit.domain.errors import InvalidDocumentError, ProviderError

DEFAULT_URL = "https://www.cnmv.es/portal/Otra-Informacion-Relevante/RSS.asmx/GetNoticiasCNMV"
_TAGS = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
_STAMP = re.compile(r"^\s*\d{1,2}:\d{2}\s+\d{2}/\d{2}/\d{4}\s*")  # "19:44  03/11/2026"


class CnmvDocumentProvider:
    """Comunicaciones de "Otra información relevante" de emisores españoles (sin clave).

    Args:
        url: URL del feed RSS.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "cnmv"

    def __init__(self, url: str = DEFAULT_URL, **http_options: Any) -> None:
        self.url = url
        self._http = HttpClient(self.name, **http_options)

    def fetch_documents(
        self,
        query: str | None,
        start: date | None,
        end: date | None,
        limit: int,
    ) -> list[RegulatoryDocument]:
        """Descarga el feed y filtra por emisor y fechas (más reciente primero).

        Raises:
            ProviderError: Si el XML es ilegible o un elemento no es válido.
        """
        documents = parse_feed(self._http.get_text(self.url, identifier="rss"))
        needle = (query or "").casefold()
        selected = [
            d
            for d in documents
            if needle in (d.issuer or "").casefold()
            and (start is None or d.published_at.date() >= start)
            and (end is None or d.published_at.date() <= end)
        ]
        selected.sort(key=lambda d: d.published_at, reverse=True)
        return selected[: max(limit, 0)]


def parse_feed(text: str) -> list[RegulatoryDocument]:
    """Convierte el RSS en documentos.

    Raises:
        ProviderError: Si el XML es ilegible o algún ``<item>`` no es válido.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ProviderError(f"cnmv: RSS ilegible: {exc}") from exc
    try:
        return [_document(item) for item in root.iter("item")]
    except (KeyError, ValueError, TypeError, InvalidDocumentError) as exc:
        raise ProviderError(f"cnmv: elemento RSS inválido: {exc}") from exc


def _document(item: ET.Element) -> RegulatoryDocument:
    fields = {child.tag.lower(): (child.text or "").strip() for child in item}
    url = fields["link"]
    published = parsedate_to_datetime(fields["pubdate"]).astimezone(timezone.utc)
    category, summary = _split_description(fields.get("description", ""))
    issuer = fields.get("title") or None
    return RegulatoryDocument(
        source="cnmv",
        identifier=_registry_number(url) or fields.get("guid") or url,
        title=f"{issuer}: {category}" if issuer and category else issuer or category or url,
        url=url,
        published_at=published.replace(tzinfo=None),
        issuer=issuer,
        category=category,
        summary=summary,
    )


def _split_description(raw: str) -> tuple[str | None, str | None]:
    """``<p><b>19:44 03/11/2026</b> Categoría<BR/><BR/>Resumen</p>`` → (categoría, resumen)."""
    head, *rest = _BREAK.split(raw, maxsplit=1)
    category = _STAMP.sub("", _plain(head)) or None
    summary = _plain(rest[0]) if rest else ""
    return category, summary or None


def _plain(fragment: str) -> str:
    """Quita etiquetas HTML, decodifica entidades y compacta espacios."""
    return " ".join(html.unescape(_TAGS.sub(" ", fragment)).split())


def _registry_number(url: str) -> str | None:
    """Extrae ``nreg`` de la URL de la ficha, si existe."""
    values = parse_qs(urlparse(url).query).get("nreg")
    return values[0] if values else None
