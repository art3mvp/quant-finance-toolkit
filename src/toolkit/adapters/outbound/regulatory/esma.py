"""Adaptador outbound de ESMA: ficheros publicados de FIRDS (datos de referencia MiFIR).

Endpoint Solr: ``esma_registers_firds_files/select``. Cada documento es un fichero ZIP
diario con datos de referencia de instrumentos (``FULINS`` completo, ``DLTINS`` deltas,
``FULCAN`` cancelaciones...).

* ``query``: tipo de fichero (``DLTINS``, ``FULINS_E``...). Se valida con una expresión
  estricta antes de llevarlo a la consulta Solr, para evitar inyección de sintaxis.
* ``start``/``end`` se filtran en el servidor sobre ``publication_date``.
* Se excluye el registro técnico ``lastModification``, que no tiene ``download_link``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from toolkit.adapters.outbound._http import HttpClient
from toolkit.domain.documents import RegulatoryDocument
from toolkit.domain.errors import InvalidDocumentError, InvalidRequestError, ProviderError

DEFAULT_URL = "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select"
_FILE_TYPE = re.compile(r"^[A-Za-z_]{3,20}$")


class EsmaDocumentProvider:
    """Ficheros FIRDS publicados por ESMA (sin clave).

    Args:
        url: URL del endpoint Solr ``select``.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "esma"

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
        """Lista ficheros FIRDS, del más reciente al más antiguo.

        Raises:
            InvalidRequestError: Si ``query`` no es un tipo de fichero válido.
            ProviderError: Ante errores HTTP o de formato.
        """
        filters = ["download_link:*", _date_filter(start, end)]
        if query:
            if not _FILE_TYPE.match(query):
                raise InvalidRequestError(
                    f"esma: tipo de fichero inválido {query!r} (p. ej. DLTINS)"
                )
            filters.append(f"file_type:{query.upper()}")
        payload = self._http.get_json(
            self.url,
            {
                "q": "*:*",
                "fq": [f for f in filters if f],
                "sort": "publication_date desc",
                "rows": max(limit, 0),
                "wt": "json",
            },
            identifier=query or "firds",
        )
        return parse_response(payload)


def parse_response(payload: Any) -> list[RegulatoryDocument]:
    """Convierte la respuesta Solr en documentos.

    Raises:
        ProviderError: Si falta ``response.docs`` o un documento no es válido.
    """
    docs = (payload.get("response") or {}).get("docs") if isinstance(payload, dict) else None
    if not isinstance(docs, list):
        raise ProviderError("esma: respuesta sin 'response.docs'")
    try:
        return [_document(d) for d in docs if d.get("download_link")]
    except (KeyError, ValueError, TypeError, AttributeError, InvalidDocumentError) as exc:
        raise ProviderError(f"esma: documento inválido: {exc}") from exc


def _document(doc: dict[str, Any]) -> RegulatoryDocument:
    published = datetime.fromisoformat(str(doc["publication_date"]).replace("Z", "+00:00"))
    return RegulatoryDocument(
        source="esma",
        identifier=str(doc["id"]),
        title=str(doc["file_name"]),
        url=str(doc["download_link"]),
        published_at=published.astimezone(timezone.utc).replace(tzinfo=None),
        category=doc.get("file_type") or None,
    )


def _date_filter(start: date | None, end: date | None) -> str:
    """Filtro Solr de rango sobre ``publication_date`` (``end`` incluido)."""
    if start is None and end is None:
        return ""
    low = f"{start.isoformat()}T00:00:00Z" if start else "*"
    high = f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z" if end else "*"
    return f"publication_date:[{low} TO {high}}}"  # '}' = extremo superior excluido
