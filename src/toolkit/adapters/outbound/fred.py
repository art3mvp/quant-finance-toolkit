"""Adaptador outbound de FRED/ALFRED (Federal Reserve Bank of St. Louis) vía API REST.

Endpoints utilizados (formato JSON):
    * ``/fred/series``              → metadatos (título, unidades, frecuencia).
    * ``/fred/series/observations`` → observaciones (fecha, valor).

Modos:
    * **FRED** (``as_of=None``): última revisión disponible de cada observación.
    * **ALFRED** (``as_of`` informado): se envían ``realtime_start = realtime_end = as_of``
      para obtener los datos *tal como se publicaron ese día* (vintage), lo que evita el
      sesgo de anticipación (look-ahead bias) en backtests.

La API key se recibe por constructor; el composition root (``bootstrap``) la lee de la
variable de entorno ``FRED_API_KEY``. Nunca aparece en logs ni en mensajes de error.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import requests

from toolkit.domain.errors import (
    ConfigurationError,
    ProviderError,
    SeriesNotFoundError,
)
from toolkit.domain.models import Frequency, MacroSeries

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.stlouisfed.org/fred"

#: Frecuencias de FRED (``frequency_short``) → ``Frequency`` del dominio.
#: ``BW`` (quincenal) y ``SA`` (semestral) no existen en el dominio y se aproximan.
_FREQUENCY_MAP: dict[str, Frequency] = {
    "d": Frequency.DAILY,
    "w": Frequency.WEEKLY,
    "bw": Frequency.WEEKLY,
    "m": Frequency.MONTHLY,
    "q": Frequency.QUARTERLY,
    "sa": Frequency.ANNUAL,
    "a": Frequency.ANNUAL,
}
_APPROXIMATED = {"bw", "sa"}

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FredMacroProvider:
    """Proveedor de series macroeconómicas desde la API REST de FRED/ALFRED.

    Args:
        api_key: API key de FRED. Si es ``None`` o vacía, ``fetch_series`` lanza
            ``ConfigurationError``.
        base_url: URL base de la API.
        timeout: Timeout en segundos de cada petición HTTP.
        max_retries: Reintentos máximos ante 429, 5xx o errores de conexión.
        backoff_factor: Espera base del backoff exponencial (``factor * 2**intento``).
        sleep: Función de espera entre reintentos (por defecto ``time.sleep``).
    """

    name = "fred"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._sleep = sleep
        self._local = threading.local()  # una requests.Session por hilo

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga metadatos y observaciones de ``series_id``.

        Raises:
            ConfigurationError: Si falta la API key o FRED la rechaza.
            SeriesNotFoundError: Si la serie no existe (400/404) o no tiene observaciones.
            ProviderError: Ante cualquier otro error HTTP, de red o de formato.
        """
        if not self._api_key:
            raise ConfigurationError(
                "Falta la API key de FRED. Define FRED_API_KEY en el entorno o en el fichero "
                ".env (ver .env.example). Puedes obtenerla gratis en "
                "https://fred.stlouisfed.org/docs/api/api_key.html"
            )
        realtime: dict[str, str] = {}
        if as_of is not None:
            realtime = {"realtime_start": as_of.isoformat(), "realtime_end": as_of.isoformat()}

        meta_payload = self._get("series", {"series_id": series_id, **realtime}, series_id)
        meta = _first_series(meta_payload, series_id)

        obs_params: dict[str, str] = {"series_id": series_id, **realtime}
        if start is not None:
            obs_params["observation_start"] = start.isoformat()
        if end is not None:
            obs_params["observation_end"] = end.isoformat()
        obs_payload = self._get("series/observations", obs_params, series_id)

        data = parse_observations(obs_payload, series_id)
        return MacroSeries(
            series_id=series_id,
            name=meta.get("title") or None,
            source=self.name,
            units=meta.get("units") or None,
            frequency=map_frequency(meta.get("frequency_short"), data.index, series_id),
            data=data,
            vintage=as_of,
        )

    # ------------------------------------------------------------------ HTTP

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def _get(self, endpoint: str, params: Mapping[str, str], series_id: str) -> dict[str, Any]:
        """GET con timeout y reintentos con backoff exponencial ante 429/5xx/red."""
        url = f"{self.base_url}/{endpoint}"
        full_params = {**params, "api_key": self._api_key, "file_type": "json"}
        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session().get(url, params=full_params, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = self._redact(f"error de red: {exc}")
                retry_after = None
            except requests.RequestException as exc:
                raise ProviderError(self._redact(f"fred: {series_id}: {exc}")) from None
            else:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise ProviderError(f"fred: {series_id}: respuesta no es JSON") from None
                message = self._redact(_error_message(response))
                if status in (400, 404):
                    if "api_key" in message.lower():
                        raise ConfigurationError(f"fred: API key rechazada: {message}")
                    raise SeriesNotFoundError(f"fred: serie {series_id} no encontrada: {message}")
                if status not in _RETRYABLE_STATUS:
                    raise ProviderError(f"fred: {series_id}: HTTP {status}: {message}")
                last_error = f"HTTP {status}: {message}"
                retry_after = _retry_after(response)

            if attempt < self.max_retries:
                delay = self.backoff_factor * (2**attempt)
                if retry_after is not None:
                    delay = max(delay, retry_after)
                logger.warning(
                    "fred: %s (%s); reintento %d/%d en %.1fs",
                    series_id,
                    last_error,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                self._sleep(delay)
        raise ProviderError(
            f"fred: {series_id}: agotados {self.max_retries} reintentos ({last_error})"
        )

    def _redact(self, text: str) -> str:
        """Elimina la API key de cualquier texto (las URLs de requests la incluyen)."""
        return text.replace(self._api_key, "***") if self._api_key else text


# ---------------------------------------------------------------------- parsing


def parse_observations(payload: Mapping[str, Any], series_id: str) -> pd.Series:
    """Convierte la respuesta de ``/series/observations`` en una ``pd.Series`` float.

    Los valores ``"."`` (dato no disponible en FRED) se convierten en ``NaN``.

    Raises:
        SeriesNotFoundError: Si no hay observaciones.
        ProviderError: Si el formato de la respuesta no es el esperado.
    """
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise ProviderError(f"fred: {series_id}: respuesta sin 'observations'")
    if not observations:
        raise SeriesNotFoundError(f"fred: {series_id}: sin observaciones en el rango solicitado")
    try:
        frame = pd.DataFrame(observations, columns=["date", "value"])
        index = pd.DatetimeIndex(pd.to_datetime(frame["date"], format="%Y-%m-%d"), name="date")
        values = pd.to_numeric(frame["value"].replace(".", np.nan), errors="raise")
    except (KeyError, ValueError, TypeError) as exc:
        raise ProviderError(f"fred: {series_id}: formato de observaciones inválido: {exc}") from exc
    series = pd.Series(values.to_numpy(dtype=float), index=index, name=series_id)
    series = series.sort_index()
    return series[~series.index.duplicated(keep="last")]


def map_frequency(code: str | None, index: pd.DatetimeIndex, series_id: str) -> Frequency:
    """Traduce ``frequency_short`` de FRED a ``Frequency``.

    Si el código falta o es desconocido, se infiere a partir del espaciado mediano entre
    fechas. ``BW`` y ``SA`` se aproximan a ``WEEKLY`` y ``ANNUAL`` con un aviso en el log.
    """
    key = (code or "").strip().lower()
    if key in _FREQUENCY_MAP:
        if key in _APPROXIMATED:
            logger.warning(
                "fred: %s tiene frecuencia %s; se aproxima a %s",
                series_id,
                code,
                _FREQUENCY_MAP[key].value,
            )
        return _FREQUENCY_MAP[key]
    inferred = _infer_frequency(index)
    logger.warning(
        "fred: %s frecuencia desconocida %r; inferida %s", series_id, code, inferred.value
    )
    return inferred


def _infer_frequency(index: pd.DatetimeIndex) -> Frequency:
    """Infiere la frecuencia a partir del número mediano de días entre observaciones."""
    if len(index) < 2:
        return Frequency.DAILY
    median_days = float(np.median(np.diff(index.values).astype("timedelta64[D]").astype(float)))
    if median_days <= 4:
        return Frequency.DAILY
    if median_days <= 16:
        return Frequency.WEEKLY
    if median_days <= 45:
        return Frequency.MONTHLY
    if median_days <= 135:
        return Frequency.QUARTERLY
    return Frequency.ANNUAL


def _first_series(payload: Mapping[str, Any], series_id: str) -> Mapping[str, Any]:
    """Extrae el primer elemento de ``seriess`` de la respuesta de ``/fred/series``."""
    items = payload.get("seriess")
    if not isinstance(items, list) or not items:
        raise SeriesNotFoundError(f"fred: serie {series_id} sin metadatos")
    first = items[0]
    if not isinstance(first, Mapping):
        raise ProviderError(f"fred: {series_id}: metadatos con formato inválido")
    return first


def _error_message(response: requests.Response) -> str:
    """Extrae ``error_message`` del cuerpo JSON de error de FRED (o el texto plano)."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, Mapping) and body.get("error_message"):
        return str(body["error_message"])
    return str(body)[:200]


def _retry_after(response: requests.Response) -> float | None:
    """Lee la cabecera ``Retry-After`` (en segundos) si existe y es numérica."""
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
