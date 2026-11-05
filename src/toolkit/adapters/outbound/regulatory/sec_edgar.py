"""Adaptador outbound de SEC EDGAR (XBRL ``companyfacts``): fundamentales contables.

Identificador: ``"<ticker|CIK>/[<taxonomía>/]<concepto>[:FY]"``, p. ej.:
    * ``AAPL/us-gaap/Assets``     → activo total (saldo, trimestral).
    * ``AAPL/Revenues``           → ingresos trimestrales (taxonomía ``us-gaap`` por defecto).
    * ``0000320193/us-gaap/NetIncomeLoss:FY`` → beneficio neto anual.

Se modela como ``MacroSeries`` (serie univariante con unidades), lo que da descarga en
lote y CLI sin tocar el núcleo, y aprovecha ``as_of``: solo se usan datos **presentados**
(``filed``) hasta esa fecha. Es el mismo *point-in-time* que ALFRED y evita el sesgo de
anticipación al usar fundamentales en backtests.

Normalización:
    * Conceptos de flujo (con ``start``): ``:FY`` toma periodos de ~1 año; por defecto,
      de ~1 trimestre. El 4.º trimestre no se publica como tal (solo el anual), así que
      la serie trimestral tiene ese hueco: no se deriva para no inventar datos.
    * Conceptos de saldo (sin ``start``): todos los cierres publicados.
    * Reexpresiones: por cada fecha de cierre gana la última presentación.
    * El índice es la **fecha de cierre** del periodo (``end``), la convención contable.

Particularidades (verificadas contra el servicio real):
    * Las rutas por concepto distinguen mayúsculas (``ASSETS`` → 404). Por eso se descarga
      ``companyfacts`` (todos los conceptos de la empresa, cacheado por CIK) y el concepto
      se busca sin distinguir mayúsculas: ``aapl/us-gaap/assets`` también vale.
    * La SEC exige un ``User-Agent`` con contacto (``SEC_USER_AGENT``); sin él da 403.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from toolkit.adapters.outbound._http import HttpClient
from toolkit.adapters.outbound._periods import clip, infer_frequency
from toolkit.domain.errors import (
    ConfigurationError,
    InvalidRequestError,
    ProviderError,
    SeriesNotFoundError,
)
from toolkit.domain.models import Frequency, MacroSeries

DEFAULT_DATA_URL = "https://data.sec.gov/api/xbrl"
DEFAULT_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

#: Duración en días aceptada para cada modo de periodo de los conceptos de flujo.
_DURATIONS = {"Q": (80, 100), "FY": (350, 380)}


@dataclass(frozen=True)
class ConceptQuery:
    """Id de serie interpretado: empresa, taxonomía, concepto y modo de periodo."""

    company: str
    taxonomy: str
    concept: str
    period: str = "Q"

    @classmethod
    def parse(cls, series_id: str) -> ConceptQuery:
        """Interpreta ``empresa/[taxonomía/]concepto[:FY]``.

        Raises:
            InvalidRequestError: Si el formato no es válido.
        """
        body, _, period = series_id.strip().partition(":")
        period = period.upper() or "Q"
        parts = [p for p in body.split("/") if p]
        if period not in _DURATIONS or len(parts) not in (2, 3):
            raise InvalidRequestError(
                f"id inválido {series_id!r}: usa '<ticker|CIK>/[<taxonomía>/]<concepto>[:FY]'"
            )
        taxonomy = parts[1] if len(parts) == 3 else "us-gaap"
        return cls(parts[0], taxonomy, parts[-1], period)


class SecEdgarMacroProvider:
    """Fundamentales XBRL de empresas cotizadas en EE. UU. desde SEC EDGAR.

    Args:
        user_agent: ``User-Agent`` con nombre y email de contacto (requisito de la SEC).
        data_url: URL base de la API XBRL.
        tickers_url: Fichero oficial ticker → CIK.
        **http_options: Opciones del ``HttpClient`` (``timeout``, ``max_retries``, ``sleep``).
    """

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str | None,
        data_url: str = DEFAULT_DATA_URL,
        tickers_url: str = DEFAULT_TICKERS_URL,
        **http_options: Any,
    ) -> None:
        self._user_agent = user_agent.strip() if user_agent else None
        self.data_url = data_url.rstrip("/")
        self.tickers_url = tickers_url
        self._http = HttpClient(self.name, secrets=[self._user_agent], **http_options)
        self._lock = threading.Lock()  # protege el mapa de tickers y el de locks
        self._cik_locks: dict[str, threading.Lock] = {}
        self._facts: dict[str, dict[str, Any]] = {}
        self._tickers: dict[str, str] | None = None

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Descarga el concepto pedido y lo normaliza a una serie por fecha de cierre.

        Raises:
            ConfigurationError: Si falta ``SEC_USER_AGENT`` o la SEC lo rechaza.
            InvalidRequestError: Si el id no tiene el formato esperado.
            SeriesNotFoundError: Si la empresa o el concepto no existen o no hay datos.
            ProviderError: Ante errores HTTP o de formato.
        """
        if not self._user_agent:
            raise ConfigurationError(
                "Falta SEC_USER_AGENT (la SEC exige nombre y email, p. ej. 'Ana Ruiz ana@x.com')"
            )
        query = ConceptQuery.parse(series_id)
        cik = self._resolve_cik(query.company, series_id)
        concept = _find_concept(self._company_facts(cik, series_id), query, series_id)
        unit, facts = _pick_unit(concept, series_id)
        data = select_facts(facts, query.period, as_of, series_id)
        data = clip(data, start, end)
        if data.empty:
            raise SeriesNotFoundError(f"sec_edgar: {series_id}: sin datos en el rango solicitado")
        is_flow = any("start" in f for f in facts)
        return MacroSeries(
            series_id=series_id,
            name=concept.get("label") or query.concept,
            source=self.name,
            units=unit,
            frequency=_frequency(query.period, is_flow, data.index),
            data=data,
            vintage=as_of,
        )

    # ------------------------------------------------------------------ descargas

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": str(self._user_agent)}

    def _resolve_cik(self, company: str, series_id: str) -> str:
        """Devuelve el CIK con 10 dígitos; acepta un CIK numérico o un ticker."""
        digits = company.upper().removeprefix("CIK")
        if digits.isdigit():
            return digits.zfill(10)
        with self._lock:
            if self._tickers is None:
                payload = self._http.get_json(
                    self.tickers_url, headers=self._headers(), identifier="company_tickers"
                )
                self._tickers = _ticker_map(payload)
        cik = self._tickers.get(company.upper())
        if cik is None:
            raise SeriesNotFoundError(f"sec_edgar: {series_id}: ticker {company!r} desconocido")
        return cik

    def _company_facts(self, cik: str, series_id: str) -> dict[str, Any]:
        """``companyfacts`` de la empresa, cacheado durante la vida del proveedor.

        Un lock por CIK: varias series de la misma empresa comparten una sola petición y
        empresas distintas se descargan en paralelo.
        """
        with self._lock:
            company_lock = self._cik_locks.setdefault(cik, threading.Lock())
        with company_lock:
            if cik not in self._facts:
                payload = self._http.get_json(
                    f"{self.data_url}/companyfacts/CIK{cik}.json",
                    headers=self._headers(),
                    identifier=series_id,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("facts"), dict):
                    raise ProviderError(f"sec_edgar: {series_id}: respuesta sin 'facts'")
                self._facts[cik] = payload["facts"]
            return self._facts[cik]


# ---------------------------------------------------------------------- normalización


def select_facts(
    facts: list[dict[str, Any]], period: str, as_of: date | None, series_id: str
) -> pd.Series:
    """Filtra hechos XBRL (duración, ``as_of``) y deja uno por fecha de cierre.

    Raises:
        SeriesNotFoundError: Si no queda ningún hecho.
        ProviderError: Si algún hecho tiene un formato inválido.
    """
    low, high = _DURATIONS[period]
    rows: list[tuple[pd.Timestamp, str, str, float]] = []
    try:
        for fact in facts:
            end = pd.Timestamp(fact["end"])
            if "start" in fact and not low <= (end - pd.Timestamp(fact["start"])).days <= high:
                continue
            filed = str(fact.get("filed", ""))
            if as_of is not None and (not filed or date.fromisoformat(filed) > as_of):
                continue  # aún no publicado en la fecha as_of
            rows.append((end, filed, str(fact.get("accn", "")), float(fact["val"])))
    except (KeyError, ValueError, TypeError) as exc:
        raise ProviderError(f"sec_edgar: {series_id}: hecho XBRL inválido: {exc}") from exc
    if not rows:
        raise SeriesNotFoundError(f"sec_edgar: {series_id}: sin hechos para ese periodo/as_of")
    frame = pd.DataFrame(rows, columns=["end", "filed", "accn", "val"])
    latest = frame.sort_values(["end", "filed", "accn"]).groupby("end").tail(1)
    index = pd.DatetimeIndex(latest["end"], name="date")
    return pd.Series(latest["val"].to_numpy(dtype=float), index=index, name=series_id)


def _ticker_map(payload: Any) -> dict[str, str]:
    """``company_tickers.json`` → ``{TICKER: CIK de 10 dígitos}``."""
    if not isinstance(payload, dict):
        raise ProviderError("sec_edgar: company_tickers con formato inválido")
    return {
        str(item["ticker"]).upper(): str(item["cik_str"]).zfill(10)
        for item in payload.values()
        if isinstance(item, dict) and "ticker" in item and "cik_str" in item
    }


def _find_concept(facts: dict[str, Any], query: ConceptQuery, series_id: str) -> dict[str, Any]:
    """Busca taxonomía y concepto sin distinguir mayúsculas."""
    taxonomies = {k.lower(): v for k, v in facts.items() if isinstance(v, dict)}
    concepts = {k.lower(): v for k, v in taxonomies.get(query.taxonomy.lower(), {}).items()}
    concept = concepts.get(query.concept.lower())
    if not isinstance(concept, dict):
        raise SeriesNotFoundError(
            f"sec_edgar: {series_id}: concepto {query.taxonomy}/{query.concept} no reportado"
        )
    return concept


def _pick_unit(concept: dict[str, Any], series_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Prefiere ``USD``; si no existe, la primera unidad publicada."""
    units = concept.get("units")
    if not isinstance(units, dict) or not units:
        raise SeriesNotFoundError(f"sec_edgar: {series_id}: concepto sin valores")
    unit = "USD" if "USD" in units else next(iter(units))
    if not isinstance(units[unit], list):
        raise ProviderError(f"sec_edgar: {series_id}: unidad {unit} con formato inválido")
    return unit, units[unit]


def _frequency(period: str, is_flow: bool, index: pd.DatetimeIndex) -> Frequency:
    if not is_flow:
        return infer_frequency(index)
    return Frequency.ANNUAL if period == "FY" else Frequency.QUARTERLY
