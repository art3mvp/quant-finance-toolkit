"""Servicio de aplicación: listado de documentos regulatorios.

Implementa el puerto inbound ``ListDocuments`` sobre un ``DocumentProvider`` inyectado.
Garantiza el contrato con independencia de la fuente: como mucho ``limit`` documentos,
ordenados del más reciente al más antiguo.
"""

from __future__ import annotations

import logging

from toolkit.domain.documents import DocumentRequest, RegulatoryDocument
from toolkit.ports.outbound import DocumentProvider

logger = logging.getLogger(__name__)


class DocumentService:
    """Lista documentos de una fuente regulatoria.

    Args:
        provider: Adaptador que cumple ``DocumentProvider``.

    Raises:
        TypeError: Si ``provider`` no cumple el puerto.
    """

    def __init__(self, provider: DocumentProvider) -> None:
        if not isinstance(provider, DocumentProvider):
            raise TypeError(f"{provider!r} no cumple el puerto DocumentProvider")
        self.provider = provider

    def list_documents(self, request: DocumentRequest) -> list[RegulatoryDocument]:
        """Pide los documentos a la fuente y aplica orden y límite.

        Raises:
            ConfigurationError, ProviderError: Los de la fuente, sin traducir.
        """
        logger.info("Listando documentos de %s (%s)", self.provider.name, request)
        documents = self.provider.fetch_documents(
            request.query, request.start, request.end, request.limit
        )
        ordered = sorted(documents, key=lambda d: d.published_at, reverse=True)
        return ordered[: request.limit]
