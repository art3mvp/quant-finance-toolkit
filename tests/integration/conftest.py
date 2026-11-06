"""Fixtures de los tests de integración: toolkit real, exterior grabado.

Todo lo de ``src`` es real (``bootstrap``, servicios, adaptadores, ``HttpClient``,
dominio, ficheros). Lo único simulado es lo que está fuera del proceso:

- HTTP, con ``responses`` y las respuestas grabadas en ``tests/resources``.
- ``yfinance``, con ``YahooReplay`` (no usa ``requests``).
- El entorno: credenciales falsas y sin leer el ``.env`` local.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
import responses

from tests.integration.replay import FAKE_SECRETS, Cassette, YahooReplay, load, register_http
from toolkit import bootstrap


@pytest.fixture(autouse=True)
def offline_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Credenciales falsas; el ``.env`` local nunca se lee."""
    monkeypatch.setattr(bootstrap, "load_settings", lambda: None)
    for name, value in FAKE_SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COINGECKO_API_PLAN", "demo")


@pytest.fixture
def http() -> Iterator[responses.RequestsMock]:
    """HTTP simulado y estricto: toda respuesta registrada debe consumirse."""
    with responses.RequestsMock(assert_all_requests_are_fired=True) as mock:
        yield mock


@pytest.fixture
def yahoo(monkeypatch: pytest.MonkeyPatch) -> YahooReplay:
    replay = YahooReplay()
    monkeypatch.setattr("toolkit.adapters.outbound.market.yahoo.yf.Ticker", replay)
    return replay


@pytest.fixture
def replay(http: responses.RequestsMock, yahoo: YahooReplay) -> Callable[[str, str], Cassette]:
    """``replay("fred", "cpi_latest")`` registra esa grabación y la devuelve."""

    def _replay(source: str, case: str) -> Cassette:
        cassette = load(source, case)
        register_http(http, cassette)
        yahoo.add(cassette)
        return cassette

    return _replay
