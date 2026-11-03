"""Tests del composition root."""

from __future__ import annotations

import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit import bootstrap
from toolkit.adapters.outbound.macro.fred import FredMacroProvider
from toolkit.adapters.outbound.market.yahoo import YahooPriceProvider
from toolkit.domain.errors import ConfigurationError
from toolkit.domain.models import MacroRequest


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita que un .env local real interfiera con los tests."""
    monkeypatch.setattr(bootstrap, "load_settings", lambda: None)


@pytest.fixture
def fake_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    """Registra los proveedores fake de tests como fuentes ``fake``."""
    monkeypatch.setitem(bootstrap.PRICE_PROVIDERS, "fake", FakePriceProvider)
    monkeypatch.setitem(bootstrap.MACRO_PROVIDERS, "fake", FakeMacroProvider)


def test_default_wiring_is_yahoo_and_fred() -> None:
    service = bootstrap.build_download_service()
    assert isinstance(service.price_provider, YahooPriceProvider)
    assert isinstance(service.macro_provider, FredMacroProvider)


@pytest.mark.usefixtures("fake_sources")
def test_registered_wiring_and_case_insensitive_names() -> None:
    service = bootstrap.build_download_service("FAKE", "fake", max_workers=2)
    assert isinstance(service.price_provider, FakePriceProvider)
    assert isinstance(service.macro_provider, FakeMacroProvider)
    assert service.max_workers == 2


def test_macro_source_can_be_disabled() -> None:
    assert bootstrap.build_download_service("yahoo", None).macro_provider is None


def test_unknown_source_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="Disponibles"):
        bootstrap.build_download_service("bloomberg")


def test_fred_without_key_fails_with_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    service = bootstrap.build_download_service("yahoo", "fred")
    with pytest.raises(ConfigurationError, match="FRED_API_KEY"):
        service.download_macro(MacroRequest(series_ids=["CPIAUCSL"]))


def test_adding_a_provider_is_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bootstrap.PRICE_PROVIDERS, "mine", lambda: FakePriceProvider(name="mine"))
    assert bootstrap.build_download_service("mine", None).price_provider.name == "mine"


@pytest.mark.usefixtures("fake_sources")
def test_main_runs_cli_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    code = bootstrap.main(["prices", "AAPL", "MSFT", "--source", "fake"])
    assert code == 0
    assert "2 OK, 0 fallidas" in capsys.readouterr().out
