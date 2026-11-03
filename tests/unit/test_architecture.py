"""Test de arquitectura: verifica la regla de dependencias del hexágono con ``ast``.

Reglas:
    * ``domain``   → solo stdlib, ``pandas``, ``numpy`` y ``toolkit.domain``.
    * ``ports``    → además puede importar ``toolkit.domain``. Sin librerías de I/O.
    * ``services`` → ``toolkit.domain`` y ``toolkit.ports``. Sin librerías de I/O.
    * ``adapters`` → ``toolkit.domain`` y ``toolkit.ports``; nunca otro adaptador,
      ni ``services`` ni ``bootstrap``.
    * ``bootstrap`` (composition root) puede importar cualquier cosa.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE = "toolkit"

#: Librerías de terceros permitidas en las capas internas (sin I/O de red).
PURE_THIRD_PARTY = {"pandas", "numpy"}

#: Capas de ``toolkit`` que puede importar cada capa.
ALLOWED_INTERNAL: dict[str, set[str]] = {
    "domain": {"domain"},
    "ports": {"domain"},
    "services": {"domain", "ports"},
    "adapters": {"domain", "ports"},
}


@dataclass(frozen=True)
class Violation:
    module: str
    imported: str
    reason: str

    def __str__(self) -> str:
        return f"{self.module} importa {self.imported}: {self.reason}"


def module_name(path: Path, root: Path = SRC) -> str:
    """Convierte la ruta de un fichero en su nombre de módulo con puntos."""
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imported_modules(source: str, module: str, is_package: bool) -> set[str]:
    """Devuelve los módulos importados por ``source``, resolviendo imports relativos."""
    tree = ast.parse(source)
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            found.add(prefix)
            # ``from toolkit import adapters`` también debe detectarse
            found.update(f"{prefix}.{alias.name}" for alias in node.names)
    return found


def check_module(module: str, imports: set[str]) -> list[Violation]:
    """Aplica la regla de dependencias a un módulo y devuelve las violaciones."""
    parts = module.split(".")
    if len(parts) < 2 or parts[1] not in ALLOWED_INTERNAL:
        return []  # toolkit/__init__, bootstrap, __main__: sin restricciones
    layer = parts[1]
    violations: list[Violation] = []
    for imported in imports:
        top = imported.split(".")[0]
        if top == PACKAGE:
            imp_parts = imported.split(".")
            if len(imp_parts) < 2:
                continue
            target = imp_parts[1]
            if target not in ALLOWED_INTERNAL[layer]:
                if target == layer and layer != "adapters":
                    continue
                if layer == "adapters" and target == "adapters":
                    own = ".".join(parts[:4])  # toolkit.adapters.<dir>.<module>
                    if len(imp_parts) <= 3 or ".".join(imp_parts[:4]) == own:
                        continue  # import de paquetes contenedores o de sí mismo
                    violations.append(Violation(module, imported, "un adaptador importa otro"))
                    continue
                violations.append(
                    Violation(module, imported, f"{layer} no puede depender de {target}")
                )
        elif layer != "adapters" and top not in sys.stdlib_module_names:
            if top not in PURE_THIRD_PARTY and top != "__future__":
                violations.append(
                    Violation(module, imported, f"librería de terceros no permitida en {layer}")
                )
    return violations


def iter_modules() -> list[tuple[str, Path]]:
    return sorted((module_name(path), path) for path in (SRC / PACKAGE).rglob("*.py"))


def test_source_tree_is_found() -> None:
    names = [name for name, _ in iter_modules()]
    assert "toolkit.domain.models" in names


@pytest.mark.parametrize(("module", "path"), iter_modules(), ids=lambda v: str(v))
def test_dependency_rule(module: str, path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    imports = imported_modules(source, module, is_package=path.name == "__init__.py")
    violations = check_module(module, imports)
    assert not violations, "\n".join(map(str, violations))


# --- Autotests del verificador: deben detectar violaciones sintéticas ---------------


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("toolkit.domain.models", "import requests"),
        ("toolkit.domain.models", "import yfinance as yf"),
        ("toolkit.domain.models", "from toolkit.ports.outbound import PriceProvider"),
        ("toolkit.domain.models", "from ..adapters.outbound import yahoo"),
        ("toolkit.ports.outbound", "from toolkit.services import download_service"),
        ("toolkit.services.download_service", "from toolkit.adapters.outbound.yahoo import X"),
        ("toolkit.services.download_service", "from toolkit import bootstrap"),
        ("toolkit.adapters.outbound.yahoo", "from toolkit.adapters.outbound.fred import X"),
        ("toolkit.adapters.outbound.yahoo", "from .fred import FredMacroProvider"),
        ("toolkit.adapters.inbound.cli", "from toolkit.bootstrap import build_download_service"),
        ("toolkit.adapters.inbound.cli", "from toolkit.services.download_service import X"),
    ],
)
def test_checker_detects_violations(module: str, source: str) -> None:
    imports = imported_modules(source, module, is_package=False)
    assert check_module(module, imports), f"no se detectó la violación: {source}"


@pytest.mark.parametrize(
    ("module", "source"),
    [
        (
            "toolkit.domain.models",
            "import pandas as pd\nimport numpy as np\nfrom datetime import date",
        ),
        ("toolkit.domain.portfolio", "from toolkit.domain.models import PriceSeries"),
        ("toolkit.ports.outbound", "from toolkit.domain.models import PriceSeries"),
        ("toolkit.services.download_service", "from toolkit.ports.outbound import PriceProvider"),
        (
            "toolkit.adapters.outbound.yahoo",
            "import yfinance as yf\nfrom toolkit.domain import models",
        ),
        ("toolkit.bootstrap", "from toolkit.adapters.outbound.yahoo import YahooPriceProvider"),
    ],
)
def test_checker_accepts_valid_imports(module: str, source: str) -> None:
    imports = imported_modules(source, module, is_package=False)
    assert not check_module(module, imports)


# --- src solo contiene código de producción -----------------------------------------

#: Librerías que solo deben usarse en tests.
TEST_ONLY_LIBRARIES = {"pytest", "responses", "unittest", "_pytest"}

#: Nombres de módulo reservados a código de test.
TEST_MODULE_NAMES = {"conftest", "fake", "fakes", "mocks", "stubs", "fixtures"}


def test_src_contains_no_test_code() -> None:
    offenders: list[str] = []
    for module, path in iter_modules():
        stem = path.stem
        if stem.startswith("test_") or stem.endswith("_test") or stem in TEST_MODULE_NAMES:
            offenders.append(f"{module}: el nombre del fichero corresponde a código de test")
        imports = imported_modules(
            path.read_text(encoding="utf-8"), module, is_package=path.name == "__init__.py"
        )
        for imported in sorted(imports):
            if imported.split(".")[0] in TEST_ONLY_LIBRARIES:
                offenders.append(f"{module}: importa la librería de test {imported}")
    assert not offenders, "\n".join(offenders)
