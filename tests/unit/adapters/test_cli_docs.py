"""Tests del subcomando ``docs`` de la CLI con un proveedor de documentos fake."""

from __future__ import annotations

import io
from datetime import date, datetime

import pytest

from tests.unit.adapters.test_cli import Factory
from toolkit.adapters.inbound.cli import EXIT_ALL_FAILED, EXIT_OK, EXIT_USAGE, run
from toolkit.domain.documents import RegulatoryDocument
from toolkit.domain.errors import ConfigurationError, ProviderError
from toolkit.ports.outbound import DocumentProvider
from toolkit.services.document_service import DocumentService

DOC = RegulatoryDocument(
    source="fake",
    identifier="43480",
    title="IZERTIS, S.A.: Programas de recompra",
    url="https://www.cnmv.es/x?nreg=43480",
    published_at=datetime(2026, 11, 3, 18, 44),
)


class FakeDocumentProvider:
    name = "fake"

    def __init__(self, documents: list[RegulatoryDocument], fail: Exception | None = None) -> None:
        self.documents = documents
        self.fail = fail
        self.calls: list[tuple[object, ...]] = []

    def fetch_documents(
        self, query: str | None, start: date | None, end: date | None, limit: int
    ) -> list[RegulatoryDocument]:
        self.calls.append((query, start, end, limit))
        if self.fail:
            raise self.fail
        return self.documents[:limit]


def invoke(argv: list[str], provider: FakeDocumentProvider) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        argv,
        service_factory=Factory(),
        price_sources=["fake"],
        macro_sources=["fake"],
        stdout=out,
        stderr=err,
        document_factory=lambda name: DocumentService(provider),
        document_sources=["fake"],
    )
    return code, out.getvalue(), err.getvalue()


def test_fake_satisfies_port() -> None:
    assert isinstance(FakeDocumentProvider([]), DocumentProvider)


def test_lists_documents_and_forwards_filters() -> None:
    provider = FakeDocumentProvider([DOC])
    code, out, _ = invoke(
        ["docs", "--source", "fake", "--query", "izertis", "--start", "2026-11-01", "--limit", "5"],
        provider,
    )
    assert code == EXIT_OK
    assert provider.calls == [("izertis", date(2026, 11, 1), None, 5)]
    assert "Documentos: 1" in out
    assert "2026-11-03 18:44  43480" in out
    assert DOC.url in out


def test_no_documents_exits_with_all_failed() -> None:
    assert invoke(["docs", "--source", "fake"], FakeDocumentProvider([]))[0] == EXIT_ALL_FAILED


def test_inverted_range_is_a_usage_error() -> None:
    argv = ["docs", "--source", "fake", "--start", "2026-11-03", "--end", "2026-11-01"]
    code, _, err = invoke(argv, FakeDocumentProvider([DOC]))
    assert code == EXIT_USAGE
    assert "start" in err


def test_non_positive_limit_is_rejected_by_argparse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        invoke(["docs", "--source", "fake", "--limit", "0"], FakeDocumentProvider([DOC]))
    assert ">= 1" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ProviderError("fake: caído"), EXIT_ALL_FAILED),
        (ConfigurationError("sin clave"), EXIT_USAGE),
    ],
)
def test_source_errors_are_reported(error: Exception, expected: int) -> None:
    code, _, err = invoke(["docs", "--source", "fake"], FakeDocumentProvider([], fail=error))
    assert code == expected
    assert str(error) in err


def test_docs_subcommand_hidden_without_factory(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        run(["docs", "--source", "fake"], service_factory=Factory())
    assert "invalid choice" in capsys.readouterr().err
