"""Tests del adaptador del Banco de España con una respuesta real recortada (sin red)."""

from __future__ import annotations

from datetime import date

import pytest
import responses

from toolkit.adapters.outbound.macro.banco_espana import (
    DEFAULT_BASE_URL,
    BancoEspanaMacroProvider,
)
from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency
from toolkit.ports.outbound import MacroProvider

URL = f"{DEFAULT_BASE_URL}/listaSeries"
PAYLOAD = [
    {
        "serie": "D_1NBAF472",
        "descripcionCorta": "Euribor a un año",
        "codFrecuencia": "M",
        "simbolo": "%",
        "fechas": ["2024-03-01T08:15:00Z", "2024-02-01T08:15:00Z", "2024-01-01T09:15:00Z"],
        "valores": [3.718, 3.671, None],
    }
]


@pytest.fixture
def provider() -> BancoEspanaMacroProvider:
    return BancoEspanaMacroProvider(sleep=lambda _: None)


def test_satisfies_port() -> None:
    assert isinstance(BancoEspanaMacroProvider(), MacroProvider)


@responses.activate
def test_happy_path_keeps_param_order_and_clips(provider: BancoEspanaMacroProvider) -> None:
    responses.get(URL, json=PAYLOAD)
    series = provider.fetch_series("D_1NBAF472", date(2024, 2, 1), None, None)
    assert responses.calls[0].request.url.endswith("?idioma=es&series=D_1NBAF472&rango=MAX")
    assert (series.source, series.name, series.units) == ("banco_espana", "Euribor a un año", "%")
    assert series.frequency is Frequency.MONTHLY
    assert series.data.index.strftime("%Y-%m-%d").tolist() == ["2024-02-01", "2024-03-01"]
    assert series.data.tolist() == [3.671, 3.718]


@responses.activate
def test_unknown_series_412_is_not_found(provider: BancoEspanaMacroProvider) -> None:
    responses.get(URL, status=412)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("NOPE", None, None, None)


@responses.activate
def test_malformed_responses(provider: BancoEspanaMacroProvider) -> None:
    responses.get(URL, json=[{"fechas": ["2024-01-01"], "valores": []}])
    responses.get(URL, json=[])
    responses.get(URL, json={"x": 1})
    with pytest.raises(ProviderError, match="no cuadran"):
        provider.fetch_series("X", None, None, None)
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("X", None, None, None)
    with pytest.raises(ProviderError):
        provider.fetch_series("X", None, None, None)


def test_as_of_is_not_supported(provider: BancoEspanaMacroProvider) -> None:
    with pytest.raises(ProviderError, match="vintages"):
        provider.fetch_series("D_1NBAF472", None, None, date(2020, 1, 1))
