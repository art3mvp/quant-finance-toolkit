"""El bloqueo de red de ``tests/conftest.py`` funciona para cualquier cliente."""

from __future__ import annotations

import socket
import urllib.request

import pytest
import requests

from tests.conftest import NetworkAccessError


def test_requests_cannot_reach_the_network() -> None:
    with pytest.raises(NetworkAccessError, match="bloqueado"):
        requests.get("https://example.com", timeout=1)


def test_raw_sockets_are_blocked() -> None:
    with pytest.raises(NetworkAccessError):
        socket.create_connection(("example.com", 443), timeout=1)
    with pytest.raises(NetworkAccessError):
        socket.getaddrinfo("example.com", 443)


def test_urllib_is_blocked() -> None:
    with pytest.raises(NetworkAccessError):
        urllib.request.urlopen("https://example.com", timeout=1)
