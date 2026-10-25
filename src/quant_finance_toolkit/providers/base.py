"""HTTP compartido, validacion y persistencia sin credenciales."""

import json
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus
from uuid import uuid4

import requests
from dotenv import load_dotenv

from quant_finance_toolkit.models.data import Metadata, Record


class ProviderError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def credential(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ProviderError("missing_config", f"Falta {name}")
    return value


def load_config(path: str | Path = "config/.env") -> None:
    load_dotenv(path, override=False)


def redact(text: str) -> str:
    for name, value in os.environ.items():
        if value and (name.endswith(("_KEY", "_TOKEN")) or name == "SEC_USER_AGENT"):
            for secret in {value, quote(value, safe=""), quote_plus(value)}:
                text = text.replace(secret, "[REDACTED]")
    return re.sub(
        r'(?i)([?&](?:api_?key|token|x_cg_\w+_api_key)=)[^&\s"<>]+',
        r"\1[REDACTED]",
        text,
    )


def number(value) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("Valor numerico ausente")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Valor numerico no finito")
    return result


def optional_number(value) -> float | None:
    return None if value is None or value == "" else number(value)


def decode_json(body: bytes):
    data = json.loads(body)
    if isinstance(data, dict):
        for key in ("Error Message", "Note", "Information", "error", "quandl_error"):
            if data.get(key):
                status = "rate_limited" if key == "Note" else "api_error"
                raise ProviderError(status, redact(str(data[key]))[:300])
        if data.get("status") == "error":
            raise ProviderError("api_error", redact(str(data.get("message", "API error")))[:300])
    return data


@dataclass
class Request:
    url: str
    params: dict = field(default_factory=dict, repr=False)
    headers: dict = field(default_factory=dict, repr=False)
    extension: str = "json"
    dataset: str | None = None


class HttpClient:
    def __init__(self, timeout: float = 25, attempts: int = 3):
        if timeout <= 0 or attempts < 1:
            raise ValueError("timeout y attempts deben ser positivos")
        self.timeout = timeout
        self.attempts = attempts
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "quant-finance-toolkit/0.1"

    def close(self):
        self.session.close()

    def get(self, request: Request) -> bytes:
        for attempt in range(self.attempts):
            try:
                response = self.session.get(
                    request.url,
                    params=request.params,
                    headers=request.headers,
                    timeout=(min(10, self.timeout), self.timeout),
                    # Never forward URL tokens or custom auth headers to another host.
                    allow_redirects=False,
                )
            except requests.RequestException:
                if attempt + 1 == self.attempts:
                    raise ProviderError("network_error", "Fallo de conexion o timeout") from None
                time.sleep(2**attempt)
                continue
            code = response.status_code
            if 200 <= code < 300:
                return response.content
            status = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(
                code, "http_error"
            )
            if code in (429, 500, 502, 503, 504) and attempt + 1 < self.attempts:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        from email.utils import parsedate_to_datetime

                        try:
                            delay = (
                                parsedate_to_datetime(retry_after) - datetime.now(UTC)
                            ).total_seconds()
                        except TypeError, ValueError:
                            delay = 61
                    if delay > 30:
                        raise ProviderError(status, f"HTTP {code}; reintentar mas tarde")
                    delay = max(0, delay)
                else:
                    delay = 2**attempt
                time.sleep(delay)
                continue
            # Do not log response URLs, request headers or arbitrary error HTML.
            if code == 403 and b"Incapsula" in response.content:
                raise ProviderError(
                    "access_blocked", "HTTP 403; bloqueo del servicio de proteccion web"
                )
            raise ProviderError(status, f"HTTP {code}")
        raise AssertionError("unreachable")


@dataclass(frozen=True)
class Context:
    provider: str
    dataset: str
    downloaded_at: str

    def meta(self, identifier: str, **kwargs) -> Metadata:
        return Metadata(self.provider, self.dataset, identifier, self.downloaded_at, **kwargs)


@dataclass
class Extraction:
    provider: str
    group: str
    domain: str
    dataset: str
    downloaded_at: str
    records: list[Record]
    raw: bytes = field(repr=False)
    extension: str = "json"

    def save(self, root: Path) -> dict[str, str]:
        stem = self.downloaded_at.replace(":", "").replace("+", "_") + "_" + uuid4().hex[:8]
        raw_path = root / "raw" / self.group / self.provider / f"{stem}.{self.extension}"
        processed_path = root / "processed" / self.domain / self.provider / f"{stem}.json"
        for path in (raw_path, processed_path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # EIA and other services can echo credentials inside their response body.
        raw_path.write_text(redact(self.raw.decode("utf-8-sig")), encoding="utf-8")
        payload = {
            "provider": self.provider,
            "dataset": self.dataset,
            "downloaded_at": self.downloaded_at,
            "records": [asdict(record) for record in self.records],
        }
        processed_path.write_text(
            redact(json.dumps(payload, ensure_ascii=False, indent=2)), encoding="utf-8"
        )
        return {"raw": str(raw_path), "processed": str(processed_path)}


@dataclass(frozen=True)
class Provider:
    id: str
    group: str
    domain: str
    dataset: str
    capabilities: tuple[str, ...]
    request: Callable[[], Request]
    parse: Callable[[bytes, Context], list[Record]]

    def fetch(self, client: HttpClient) -> Extraction:
        request = self.request()
        body = client.get(request)
        now = datetime.now(UTC).isoformat()
        dataset = request.dataset or self.dataset
        try:
            records = self.parse(body, Context(self.id, dataset, now))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ProviderError(
                "invalid_response", f"Respuesta no valida ({type(exc).__name__})"
            ) from None
        if not records:
            raise ProviderError("empty", "Respuesta sin registros validos")
        return Extraction(
            self.id, self.group, self.domain, dataset, now, records, body, request.extension
        )
