"""Cliente HTTP compartido por los adaptadores outbound REST.

No es un adaptador: es infraestructura común (timeout, reintentos con backoff, sesión por
hilo y ocultación de credenciales). Traduce los fallos HTTP a errores del dominio para que
ninguna excepción de ``requests`` salga de la capa de adaptadores.

Mapeo de estados:
    * 2xx → se devuelve el cuerpo.
    * 401/403 → ``ConfigurationError`` (credencial ausente, inválida o sin permisos).
    * 404 → ``SeriesNotFoundError``.
    * 429, 5xx y errores de red → reintento; al agotarse, ``ProviderError``.
    * Resto → ``ProviderError``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import requests

from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_RETRY_AFTER = 60.0  # no se espera más de un minuto aunque el servidor lo pida


class HttpClient:
    """GET con reintentos para un proveedor concreto.

    Args:
        source: Nombre de la fuente; prefija todos los mensajes de error.
        timeout: Timeout en segundos de cada petición.
        max_retries: Reintentos máximos ante 429, 5xx o errores de red.
        backoff_factor: Espera base del backoff exponencial (``factor * 2**intento``).
        sleep: Función de espera (inyectable en tests).
        secrets: Valores que nunca deben aparecer en mensajes (API keys, tokens).
    """

    def __init__(
        self,
        source: str,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        secrets: Iterable[str | None] = (),
    ) -> None:
        self.source = source
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._sleep = sleep
        self._secrets = tuple(s for s in secrets if s)
        self._local = threading.local()  # requests.Session no es thread-safe

    def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        identifier: str = "",
    ) -> Any:
        """GET que devuelve el cuerpo JSON decodificado.

        Raises:
            ProviderError: Si la respuesta no es JSON o ante fallos HTTP (ver módulo).
        """
        response = self._request(url, params, headers, identifier)
        try:
            return response.json()
        except ValueError:
            raise ProviderError(self._label(identifier, "respuesta no es JSON")) from None

    def get_text(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        identifier: str = "",
    ) -> str:
        """GET que devuelve el cuerpo como texto (CSV, XML...)."""
        response = self._request(url, params, headers, identifier)
        response.encoding = response.encoding or "utf-8"
        return response.text

    def redact(self, text: str) -> str:
        """Sustituye cualquier credencial conocida por ``***``."""
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    # ------------------------------------------------------------------ internos

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = "toolkit-financiero/0.1"
            self._local.session = session
        return session

    def _request(
        self,
        url: str,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        identifier: str,
    ) -> requests.Response:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            retry_after: float | None = None
            try:
                response = self._session().get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = self.redact(f"error de red: {exc}")
            except requests.RequestException as exc:
                raise ProviderError(self._label(identifier, self.redact(str(exc)))) from None
            else:
                status = response.status_code
                if 200 <= status < 300:
                    return response
                self._raise_for_status(status, response, identifier)
                last_error = f"HTTP {status}"
                retry_after = parse_retry_after(response.headers.get("Retry-After"))

            if attempt < self.max_retries:
                delay = self.backoff_factor * (2**attempt)
                if retry_after is not None:
                    delay = max(delay, retry_after)
                logger.warning(
                    "%s: %s (%s); reintento %d/%d en %.1fs",
                    self.source,
                    identifier,
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                self._sleep(delay)
        raise ProviderError(
            self._label(identifier, f"agotados {self.max_retries} reintentos ({last_error})")
        )

    def _raise_for_status(self, status: int, response: requests.Response, identifier: str) -> None:
        """Lanza el error de dominio adecuado; vuelve sin lanzar si el estado es reintentable."""
        if status in RETRYABLE_STATUS:
            return
        detail = self.redact(response.text[:200].strip())
        if status in (401, 403):
            raise ConfigurationError(
                self._label(identifier, f"HTTP {status}: credencial ausente o rechazada")
            )
        if status == 404:
            raise SeriesNotFoundError(self._label(identifier, "no encontrado (HTTP 404)"))
        raise ProviderError(self._label(identifier, f"HTTP {status}: {detail}"))

    def _label(self, identifier: str, message: str) -> str:
        return (
            f"{self.source}: {identifier}: {message}" if identifier else f"{self.source}: {message}"
        )


def parse_retry_after(value: str | None) -> float | None:
    """Lee ``Retry-After`` en segundos (acotado a un minuto); ``None`` si falta o no es numérico."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return min(max(seconds, 0.0), _MAX_RETRY_AFTER)
