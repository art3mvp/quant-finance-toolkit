"""Reproduce las respuestas reales grabadas en ``tests/resources`` (sin red).

Cada fichero ``tests/resources/<fuente>/<caso>.json`` guarda la respuesta de una
llamada real a la API. Aquí se registra en
``responses`` (HTTP) o en un ``yfinance.Ticker`` falso (Yahoo) para que el adaptador
real reciba exactamente lo que respondió la API.

El mock es estricto: la URL y todos los parámetros deben coincidir con los grabados, y
todas las respuestas registradas deben consumirse. Si un adaptador cambia la petición
que envía, el test falla, igual que fallaría contra la API real.
"""

from __future__ import annotations

import io
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
import responses
from responses import matchers
from yfinance import exceptions as yf_exceptions

RESOURCES = Path(__file__).resolve().parents[1] / "resources"

#: Valores falsos de las credenciales; los ficheros guardan ``<NOMBRE>`` en su lugar.
FAKE_SECRETS: dict[str, str] = {
    "FRED_API_KEY": "test-fred-key",
    "ALPHA_VANTAGE_API_KEY": "test-alpha-vantage-key",
    "TWELVE_DATA_API_KEY": "test-twelve-data-key",
    "EIA_API_KEY": "test-eia-key",
    "COINGECKO_API_KEY": "test-coingecko-key",
    "SEC_USER_AGENT": "Toolkit Tests tests@example.com",
}

_PLACEHOLDER = re.compile(r"<([A-Z_]+)>")


@dataclass(frozen=True)
class Cassette:
    """Una grabación: las peticiones HTTP (o de ``yfinance``) de un caso."""

    source: str
    case: str
    recorded_on: date
    outcome: dict[str, Any]
    interactions: list[dict[str, Any]] = field(default_factory=list)
    yahoo: list[dict[str, Any]] = field(default_factory=list)

    def json(self, index: int = 0) -> Any:
        """Cuerpo JSON de la petición ``index``, tal como respondió la API."""
        return self.interactions[index]["json"]

    def text(self, index: int = 0) -> str:
        """Cuerpo de texto (CSV, XML...) de la petición ``index``."""
        return self.interactions[index]["text"]

    def csv(self, index: int = 0) -> pd.DataFrame:
        """Cuerpo CSV de la petición ``index`` como ``DataFrame`` (sin interpretar)."""
        return pd.read_csv(io.StringIO(self.text(index)), dtype=str)

    def yahoo_frame(self, symbol: str) -> pd.DataFrame:
        """``DataFrame`` que devolvió ``yfinance`` para ``symbol``."""
        return _history_frame(self._yahoo_entry(symbol)["history"])

    def _yahoo_entry(self, symbol: str) -> dict[str, Any]:
        for entry in self.yahoo:
            if entry["symbol"] == symbol:
                return entry
        raise KeyError(f"{self.source}/{self.case}: no hay grabación de yfinance para {symbol}")


@cache
def _read(source: str, case: str) -> str:
    path = RESOURCES / source / f"{case}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}: añade la respuesta real de la API en ese fichero"
        )
    return path.read_text(encoding="utf-8")


def load(source: str, case: str) -> Cassette:
    """Lee la grabación ``tests/resources/<source>/<case>.json``."""
    raw = json.loads(_read(source, case))
    return Cassette(
        source=raw["source"],
        case=raw["case"],
        recorded_on=date.fromisoformat(raw["recorded_on"]),
        outcome=raw["outcome"],
        interactions=raw.get("interactions", []),
        yahoo=raw.get("yahoo", []),
    )


def _resolve(value: Any) -> Any:
    """Sustituye ``<NOMBRE>`` por el valor (falso) de esa variable de entorno."""
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return value


def register_http(mock: responses.RequestsMock, cassette: Cassette) -> None:
    """Registra cada respuesta grabada; solo casa con la misma URL y parámetros."""
    for interaction in cassette.interactions:
        query = {k: _resolve(v) for k, v in interaction["query"].items()}
        content_type = interaction["content_type"] or "text/plain"
        if "json" in interaction:
            body = json.dumps(_resolve_json(interaction["json"]))
        else:
            body = _resolve(interaction["text"])
        charset = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
        mock.add(
            responses.GET,
            interaction["url"],
            body=body.encode(charset.group(1) if charset else "utf-8"),
            status=interaction["status"],
            content_type=content_type,
            match=[matchers.query_param_matcher(query)],
        )


def _resolve_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_json(v) for v in value]
    return _resolve(value)


# ---------------------------------------------------------------------- yfinance


def _history_frame(history: Mapping[str, Any]) -> pd.DataFrame:
    """Reconstruye el ``DataFrame`` de ``Ticker.history`` (índice con zona horaria)."""
    if history["index"]:
        index = pd.to_datetime(history["index"], utc=True)
        index = index.tz_convert(history["tz"]) if history["tz"] else index.tz_localize(None)
    else:
        index = pd.DatetimeIndex([], tz=history["tz"])
    return pd.DataFrame(history["data"], index=index.rename("Date"), columns=history["columns"])


def _as_recorded(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Serializa los argumentos de ``history`` igual que el grabador."""
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in kwargs.items()}


class ReplayTicker:
    """``yfinance.Ticker`` falso que devuelve lo grabado para un símbolo."""

    def __init__(self, entry: Mapping[str, Any]) -> None:
        self._entry = entry

    def history(self, **kwargs: Any) -> pd.DataFrame:
        expected = self._entry["history_kwargs"]
        actual = _as_recorded(kwargs)
        assert actual == expected, f"yfinance.history({actual}) ≠ grabado ({expected})"
        if "error" in self._entry:
            error = self._entry["error"]
            cls = getattr(yf_exceptions, error["type"], RuntimeError)
            raise cls(error["message"])
        return _history_frame(self._entry["history"])

    def get_history_metadata(self) -> dict[str, Any]:
        return dict(self._entry.get("metadata", {}))


class YahooReplay:
    """Fábrica de ``ReplayTicker`` que sustituye a ``yfinance.Ticker``."""

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, Any]] = {}
        self.requested: list[str] = []

    def add(self, cassette: Cassette) -> None:
        for entry in cassette.yahoo:
            self._entries[entry["symbol"]] = entry

    def __call__(self, symbol: str) -> ReplayTicker:
        self.requested.append(symbol)
        if symbol not in self._entries:
            raise AssertionError(f"yfinance.Ticker({symbol!r}) no está grabado")
        return ReplayTicker(self._entries[symbol])
