"""Configuración común de pytest: ningún test puede salir a la red.

Los tests unitarios usan fakes y los de integración reproducen respuestas reales
grabadas (``tests/resources``). Si algún test intenta abrir una conexión, por ejemplo
porque falta un mock o una librería usa su propio cliente HTTP, falla con un mensaje
claro en lugar de llamar a la API real.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest


class NetworkAccessError(RuntimeError):
    """Un test ha intentado acceder a la red."""


def _blocked(*args: Any, **kwargs: Any) -> Any:
    target = args[1] if len(args) > 1 else args[0] if args else kwargs
    raise NetworkAccessError(
        f"Acceso a la red bloqueado en los tests (destino: {target!r}). "
        "Mockea la llamada: fakes en tests/fakes.py o respuestas en tests/resources/."
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
