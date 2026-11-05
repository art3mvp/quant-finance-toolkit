"""Test de arquitectura: verifica la regla de dependencias del hexágono con ``ast``.

Reglas (las dependencias solo apuntan hacia dentro):
    * ``domain``            → stdlib, ``pandas``, ``numpy`` y ``toolkit.domain``.
    * ``ports``             → además ``toolkit.domain``. Sin librerías de I/O.
    * ``services``          → ``toolkit.domain`` y ``toolkit.ports``. Sin librerías de I/O.
    * ``adapters.inbound``  → ``toolkit.domain`` y ``toolkit.ports.inbound``: entra por
      los casos de uso, nunca por los puertos outbound ni por otro adaptador.
    * ``adapters.outbound`` → ``toolkit.domain``, ``toolkit.ports.outbound`` y los helpers
      privados ``adapters/outbound/_*``; nunca otro adaptador.
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

#: Librerías de terceros permitidas en las capas internas: cálculo puro, sin I/O.
PURE_THIRD_PARTY = {"pandas", "numpy"}

#: Prefijos de ``toolkit`` que puede importar cada capa.
LAYER_RULES: dict[str, tuple[str, ...]] = {
    "toolkit.domain": ("toolkit.domain",),
    "toolkit.ports": ("toolkit.domain", "toolkit.ports"),
    "toolkit.services": ("toolkit.domain", "toolkit.ports", "toolkit.services"),
    "toolkit.adapters": ("toolkit.domain",),  # solo los __init__ de los paquetes
    "toolkit.adapters.inbound": ("toolkit.domain", "toolkit.ports.inbound"),
    "toolkit.adapters.outbound": ("toolkit.domain", "toolkit.ports.outbound"),
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


def _within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _layer_label(name: str) -> str:
    """``toolkit.adapters.outbound.market.yahoo`` → ``adapters.outbound``."""
    parts = name.split(".")[1:]
    return ".".join(parts[:2] if parts[:1] == ["adapters"] else parts[:1])


def layer_of(module: str) -> str | None:
    """Capa más específica a la que pertenece ``module`` (``None`` si no tiene reglas)."""
    matches = [layer for layer in LAYER_RULES if _within(module, layer)]
    return max(matches, key=len) if matches else None


def _is_allowed(layer: str, imported: str) -> bool:
    """``imported`` está permitido o es un paquete contenedor de algo permitido."""
    return any(
        _within(imported, prefix) or prefix.startswith(imported + ".")
        for prefix in LAYER_RULES[layer]
    )


def _is_allowed_adapter_import(module: str, layer: str, imported: str) -> bool:
    """Un adaptador solo importa sus paquetes contenedores, a sí mismo o helpers privados.

    Los adaptadores viven en ``toolkit.adapters.<inbound|outbound>[.<tipo>].<modulo>``.
    Los módulos con prefijo ``_`` (p. ej. ``_http``) son infraestructura compartida, no
    adaptadores, pero solo dentro del mismo lado: la CLI no puede usar ``_http``.
    """
    if layer.startswith(imported + "."):
        return True  # paquete contenedor (``toolkit.adapters``)
    if not _within(imported, layer):
        return False  # cruza de inbound a outbound o al revés
    return (
        module == imported
        or module.startswith(imported + ".")  # paquete contenedor
        or imported.startswith(module + ".")  # submódulo propio (p. ej. un __init__)
        or any(part.startswith("_") for part in imported.split(".")[3:])
    )


def check_module(module: str, imports: set[str]) -> list[Violation]:
    """Aplica la regla de dependencias a un módulo y devuelve las violaciones."""
    layer = layer_of(module)
    if layer is None:
        return []  # toolkit/__init__, bootstrap, __main__: sin restricciones
    is_adapter = _within(layer, "toolkit.adapters")
    label = _layer_label(layer)
    violations: list[Violation] = []
    for imported in imports:
        top = imported.split(".")[0]
        if top == PACKAGE:
            if imported == PACKAGE or _is_allowed(layer, imported):
                continue
            if is_adapter and _within(imported, "toolkit.adapters"):
                if _is_allowed_adapter_import(module, layer, imported):
                    continue
                if _within(imported, layer):
                    reason = "un adaptador importa otro"
                else:
                    reason = f"{label} no puede depender de {_layer_label(imported)}"
                violations.append(Violation(module, imported, reason))
                continue
            target = ".".join(imported.split(".")[1:3])
            violations.append(Violation(module, imported, f"{label} no puede depender de {target}"))
        elif not is_adapter and top not in sys.stdlib_module_names:
            if top not in PURE_THIRD_PARTY and top != "__future__":
                violations.append(
                    Violation(module, imported, f"librería de terceros no permitida en {label}")
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
        # Mismo tipo o tipos distintos: sigue siendo un adaptador importando otro.
        ("toolkit.adapters.outbound.market.yahoo", "from .other import X"),
        ("toolkit.adapters.outbound.market.yahoo", "from ..macro.fred import X"),
        ("toolkit.adapters.outbound.market.yahoo", "from toolkit.adapters.outbound import macro"),
        ("toolkit.adapters.inbound.cli", "from toolkit.bootstrap import build_download_service"),
        ("toolkit.adapters.inbound.cli", "from toolkit.services.download_service import X"),
        # La CLI entra por los casos de uso, no por los puertos outbound ni sus helpers.
        ("toolkit.adapters.inbound.cli", "from toolkit.ports.outbound import PriceProvider"),
        ("toolkit.adapters.inbound.cli", "from toolkit.ports import outbound"),
        ("toolkit.adapters.inbound.cli", "from toolkit.adapters.outbound._http import X"),
        ("toolkit.adapters.inbound.cli", "from toolkit.adapters.outbound.storage import files"),
        ("toolkit.adapters.outbound.market.yahoo", "from toolkit.ports.inbound import X"),
        ("toolkit.adapters.outbound.market.yahoo", "from toolkit.adapters.inbound import cli"),
        # El núcleo no dibuja ni escribe ficheros: eso es de los adaptadores.
        ("toolkit.domain.portfolio", "import matplotlib.pyplot as plt"),
        ("toolkit.services.storage_service", "import pyarrow"),
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
            "toolkit.adapters.outbound.market.yahoo",
            "import yfinance as yf\nfrom toolkit.domain import models",
        ),
        (
            "toolkit.bootstrap",
            "from toolkit.adapters.outbound.market.yahoo import YahooPriceProvider",
        ),
        # Los helpers privados compartidos no cuentan como adaptadores.
        ("toolkit.adapters.outbound.market.yahoo", "from .._http import HttpClient"),
        ("toolkit.adapters.outbound.macro.fred", "from toolkit.adapters.outbound._http import X"),
        ("toolkit.adapters.inbound.cli", "from toolkit.ports.inbound import StoreSeries"),
        ("toolkit.adapters.inbound.cli", "from toolkit.ports import inbound"),
        (
            "toolkit.adapters.outbound.storage.files",
            "import pandas as pd\nfrom toolkit.ports.outbound import SeriesRepository",
        ),
        ("toolkit.services.storage_service", "from toolkit.ports.outbound import X"),
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
