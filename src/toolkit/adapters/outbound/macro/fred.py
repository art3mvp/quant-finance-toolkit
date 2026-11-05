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

El transporte (reintentos, Retry-After, sesión por hilo, ocultación de la clave) es el
``HttpClient`` común; FRED solo aporta cómo leer sus errores 400.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import infer_frequency, to_series
from toolkit.domain.errors import (
    ConfigurationError,
    ProviderError,
    SeriesNotFoundError,
    ToolkitError,
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


class FredMacroProvider:
    """Proveedor de series macroeconómicas desde la API REST de FRED/ALFRED.

    Args:
        api_key: API key de FRED. Si es ``None`` o vacía, ``fetch_series`` lanza
            ``ConfigurationError``.
        base_url: URL base de la API.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "fred"

    def __init__(
        self, api_key: str | None, base_url: str = DEFAULT_BASE_URL, **http_options: Any
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self.base_url = base_url.rstrip("/")
        self._http = HttpClient(
            self.name, secrets=[self._api_key], error_mapper=map_error, **http_options
        )

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

        meta = _first_series(
            self._get("series", {"series_id": series_id, **realtime}, series_id), series_id
        )
        obs_params: dict[str, str] = {"series_id": series_id, **realtime}
        if start is not None:
            obs_params["observation_start"] = start.isoformat()
        if end is not None:
            obs_params["observation_end"] = end.isoformat()
        data = parse_observations(
            self._get("series/observations", obs_params, series_id), series_id
        )
        return MacroSeries(
            series_id=series_id,
            name=meta.get("title") or None,
            source=self.name,
            units=meta.get("units") or None,
            frequency=map_frequency(meta.get("frequency_short"), data.index, series_id),
            data=data,
            vintage=as_of,
        )

    def _get(self, endpoint: str, params: Mapping[str, str], series_id: str) -> Any:
        return self._http.get_json(
            f"{self.base_url}/{endpoint}",
            {**params, "api_key": self._api_key, "file_type": "json"},
            identifier=series_id,
        )


# ---------------------------------------------------------------------- parsing


def map_error(status: int, body: str) -> ToolkitError | None:
    """FRED responde 400 (o 404) con ``error_message`` para clave inválida y serie inexistente."""
    if status not in (400, 404):
        return None
    message = _error_message(body)
    if "api_key" in message.lower():
        return ConfigurationError(f"API key rechazada: {message}")
    return SeriesNotFoundError(f"serie no encontrada: {message}")


def parse_observations(payload: Mapping[str, Any], series_id: str) -> pd.Series:
    """Convierte la respuesta de ``/series/observations`` en una ``pd.Series`` float.

    Los valores ``"."`` (dato no disponible en FRED) se convierten en ``NaN``.

    Raises:
        SeriesNotFoundError: Si no hay observaciones.
        ProviderError: Si el formato de la respuesta no es el esperado.
    """
    observations = payload.get("observations") if isinstance(payload, Mapping) else None
    if not isinstance(observations, list):
        raise ProviderError(f"fred: {series_id}: respuesta sin 'observations'")
    if not observations:
        raise SeriesNotFoundError(f"fred: {series_id}: sin observaciones en el rango solicitado")
    try:
        dates = [o["date"] for o in observations]
        values = [None if o["value"] == "." else o["value"] for o in observations]
        return to_series(dates, values, series_id)
    except (KeyError, ValueError, TypeError) as exc:
        raise ProviderError(f"fred: {series_id}: formato de observaciones inválido: {exc}") from exc


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
    inferred = infer_frequency(index)
    logger.warning(
        "fred: %s frecuencia desconocida %r; inferida %s", series_id, code, inferred.value
    )
    return inferred


def _first_series(payload: Mapping[str, Any], series_id: str) -> Mapping[str, Any]:
    """Extrae el primer elemento de ``seriess`` de la respuesta de ``/fred/series``."""
    items = payload.get("seriess") if isinstance(payload, Mapping) else None
    if not isinstance(items, list) or not items:
        raise SeriesNotFoundError(f"fred: serie {series_id} sin metadatos")
    first = items[0]
    if not isinstance(first, Mapping):
        raise ProviderError(f"fred: {series_id}: metadatos con formato inválido")
    return first


def _error_message(body: str) -> str:
    """Extrae ``error_message`` del cuerpo JSON de error de FRED (o el texto plano)."""
    try:
        payload = json.loads(body)
    except ValueError:
        return body[:200]
    if isinstance(payload, Mapping) and payload.get("error_message"):
        return str(payload["error_message"])
    return str(payload)[:200]
