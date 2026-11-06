"""Las grabaciones de ``tests/resources`` están en uso y no contienen credenciales."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.integration.replay import FAKE_SECRETS, RESOURCES

TESTS = Path(__file__).resolve().parent
CASSETTES = sorted(RESOURCES.rglob("*.json"))


def test_there_is_a_recording_for_every_source() -> None:
    from toolkit import bootstrap

    sources = {
        *bootstrap.PRICE_PROVIDERS,
        *bootstrap.MACRO_PROVIDERS,
        *bootstrap.DOCUMENT_PROVIDERS,
    }
    recorded = {path.parent.name for path in CASSETTES}
    assert sources <= recorded, f"fuentes sin grabación: {sorted(sources - recorded)}"


@pytest.mark.parametrize("path", CASSETTES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_recording_is_used_by_some_test(path: Path) -> None:
    # replay("fuente", "caso") o una fila ("fuente", "caso", ...) de una tabla parametrizada
    pattern = re.compile(rf'"{path.parent.name}",\s*"{path.stem}"')
    sources = "\n".join(p.read_text(encoding="utf-8") for p in TESTS.glob("test_*.py"))
    assert pattern.search(sources), f"{path} no lo usa ningún test: bórralo o añade uno"


@pytest.mark.parametrize("path", CASSETTES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_recording_has_no_credentials(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    cassette = json.loads(text)
    assert cassette["recorded_on"]
    # solo marcadores <NOMBRE> conocidos, nunca un valor
    assert set(re.findall(r"<([A-Z_]+_(?:KEY|AGENT))>", text)) <= set(FAKE_SECRETS)
    for interaction in cassette.get("interactions", []):
        for name, value in interaction["query"].items():
            if re.search(r"(api_?key|token|secret)", name, flags=re.I):
                assert re.fullmatch(r"<[A-Z_]+>", str(value)), f"{name} sin ocultar en {path}"
