"""Tests del cliente HTTP compartido por los adaptadores REST (HTTP mockeado, sin red)."""

from __future__ import annotations

import pytest
import requests
import responses

from toolkit.adapters.outbound._http import HttpClient, parse_retry_after
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError

URL = "https://api.example.com/data"
SECRET = "super-secret-key"


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def sleeper() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def client(sleeper: SleepRecorder) -> HttpClient:
    return HttpClient("demo", sleep=sleeper, secrets=[SECRET, None])


@responses.activate
def test_get_json_returns_payload(client: HttpClient) -> None:
    responses.get(URL, json={"ok": True})
    assert client.get_json(URL, {"q": 1}) == {"ok": True}
    assert "q=1" in responses.calls[0].request.url


@responses.activate
def test_get_text_returns_body(client: HttpClient) -> None:
    responses.get(URL, body="a,b\n1,2\n")
    assert client.get_text(URL) == "a,b\n1,2\n"


@responses.activate
def test_get_text_defaults_to_utf8_and_strips_bom(client: HttpClient) -> None:
    body = "﻿título,€\n".encode()
    responses.get(URL, body=body, content_type="text/csv")
    assert client.get_text(URL) == "título,€\n"


@responses.activate
def test_retries_with_backoff_then_succeeds(client: HttpClient, sleeper: SleepRecorder) -> None:
    responses.get(URL, status=429)
    responses.get(URL, status=503)
    responses.get(URL, json=[1])
    assert client.get_json(URL) == [1]
    assert sleeper.delays == [0.5, 1.0]


@responses.activate
def test_retry_after_header_is_respected(client: HttpClient, sleeper: SleepRecorder) -> None:
    responses.get(URL, status=429, headers={"Retry-After": "7"})
    responses.get(URL, json=[1])
    client.get_json(URL)
    assert sleeper.delays == [7.0]


@responses.activate
def test_gives_up_after_max_retries(client: HttpClient, sleeper: SleepRecorder) -> None:
    responses.get(URL, status=500)
    with pytest.raises(ProviderError, match="reintentos"):
        client.get_json(URL, identifier="X")
    assert len(responses.calls) == 4
    assert sleeper.delays == [0.5, 1.0, 2.0]


@responses.activate
def test_network_errors_are_retried_and_redacted(client: HttpClient) -> None:
    responses.get(URL, body=requests.ConnectionError(f"boom {SECRET}"))
    with pytest.raises(ProviderError) as excinfo:
        client.get_json(URL)
    assert SECRET not in str(excinfo.value)


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, ConfigurationError), (403, ConfigurationError), (404, SeriesNotFoundError)],
)
@responses.activate
def test_status_mapping(client: HttpClient, status: int, error: type[Exception]) -> None:
    responses.get(URL, status=status)
    with pytest.raises(error):
        client.get_json(URL, identifier="X")
    assert len(responses.calls) == 1  # sin reintentos


@responses.activate
def test_custom_not_found_status() -> None:
    client = HttpClient("demo", not_found_status=(404, 412))
    responses.get(URL, status=412)
    with pytest.raises(SeriesNotFoundError, match="412"):
        client.get_json(URL)


@responses.activate
def test_other_errors_do_not_leak_secrets(client: HttpClient) -> None:
    responses.get(URL, status=400, body=f"invalid key {SECRET}")
    with pytest.raises(ProviderError) as excinfo:
        client.get_json(URL)
    assert SECRET not in str(excinfo.value)
    assert not isinstance(excinfo.value, SeriesNotFoundError)


@responses.activate
def test_non_json_body_raises_provider_error(client: HttpClient) -> None:
    responses.get(URL, body="<html>")
    with pytest.raises(ProviderError, match="JSON"):
        client.get_json(URL)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, None), ("abc", None), ("3", 3.0), ("-1", 0.0), ("999", 60.0)]
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    assert parse_retry_after(value) == expected
