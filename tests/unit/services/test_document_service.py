"""Tests del caso de uso ``ListDocuments`` y de ``DocumentRequest``."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from tests.unit.adapters.test_cli_docs import DOC, FakeDocumentProvider
from toolkit.domain.documents import DocumentRequest
from toolkit.domain.errors import InvalidRequestError
from toolkit.ports.inbound import ListDocuments
from toolkit.services.document_service import DocumentService

OLDER = DOC.__class__(**{**DOC.__dict__, "identifier": "1", "published_at": datetime(2026, 1, 1)})


def test_satisfies_inbound_port() -> None:
    assert isinstance(DocumentService(FakeDocumentProvider([])), ListDocuments)


def test_rejects_objects_that_do_not_satisfy_port() -> None:
    with pytest.raises(TypeError):
        DocumentService(object())  # type: ignore[arg-type]


def test_orders_newest_first_and_enforces_limit() -> None:
    # una fuente que ignora el orden y el límite no rompe el contrato
    provider = FakeDocumentProvider([OLDER, DOC])
    provider.fetch_documents = lambda *args: [OLDER, DOC]  # type: ignore[method-assign]
    service = DocumentService(provider)
    assert service.list_documents(DocumentRequest(limit=5)) == [DOC, OLDER]
    assert service.list_documents(DocumentRequest(limit=1)) == [DOC]


def test_request_is_forwarded() -> None:
    provider = FakeDocumentProvider([DOC])
    DocumentService(provider).list_documents(DocumentRequest(" indra ", date(2026, 1, 1)))
    assert provider.calls == [("indra", date(2026, 1, 1), None, 20)]


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": 0}, {"start": date(2026, 2, 1), "end": date(2026, 1, 1)}],
)
def test_invalid_requests_fail_at_construction(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidRequestError):
        DocumentRequest(**kwargs)  # type: ignore[arg-type]


def test_blank_query_means_no_filter() -> None:
    assert DocumentRequest("  ").query is None
