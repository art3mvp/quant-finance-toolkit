"""Tests del modelo de documentos regulatorios."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from toolkit.domain.documents import RegulatoryDocument
from toolkit.domain.errors import InvalidDocumentError, ToolkitError

VALID = {
    "source": "cnmv",
    "identifier": "43480",
    "title": "IZERTIS, S.A.",
    "url": "https://www.cnmv.es/x?nreg=43480",
    "published_at": datetime(2026, 11, 3, 18, 44, 49),
}


def test_valid_document() -> None:
    doc = RegulatoryDocument(**VALID, issuer="IZERTIS, S.A.")
    assert doc.issuer == "IZERTIS, S.A."
    assert doc.category is None


@pytest.mark.parametrize(
    "override",
    [
        {"title": " "},
        {"identifier": ""},
        {"url": "ftp://x"},
        {"published_at": "2026-11-03"},
        {"published_at": datetime(2026, 11, 3, tzinfo=timezone.utc)},
    ],
)
def test_invalid_documents(override: dict[str, object]) -> None:
    with pytest.raises(InvalidDocumentError):
        RegulatoryDocument(**{**VALID, **override})


def test_error_is_a_toolkit_error() -> None:
    assert issubclass(InvalidDocumentError, ToolkitError)
