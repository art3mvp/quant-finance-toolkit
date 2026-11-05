"""Tests del composition root."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes import FakeMacroProvider, FakePriceProvider
from toolkit import bootstrap
from toolkit.adapters.outbound.fiscal.us_treasury import UsTreasuryMacroProvider
from toolkit.adapters.outbound.macro.banco_espana import BancoEspanaMacroProvider
from toolkit.adapters.outbound.macro.bis import BisMacroProvider
from toolkit.adapters.outbound.macro.ecb import EcbMacroProvider
from toolkit.adapters.outbound.macro.eurostat import EurostatMacroProvider
from toolkit.adapters.outbound.macro.fred import FredMacroProvider
from toolkit.adapters.outbound.macro.world_bank import WorldBankMacroProvider
from toolkit.adapters.outbound.market.alpha_vantage import AlphaVantagePriceProvider
from toolkit.adapters.outbound.market.twelve_data import TwelveDataPriceProvider
from toolkit.adapters.outbound.market.yahoo import YahooPriceProvider
from toolkit.adapters.outbound.regulatory.cnmv import CnmvDocumentProvider
from toolkit.adapters.outbound.regulatory.esma import EsmaDocumentProvider
from toolkit.adapters.outbound.regulatory.sec_edgar import SecEdgarMacroProvider
from toolkit.adapters.outbound.specialized.coingecko import CoinGeckoPriceProvider
from toolkit.adapters.outbound.specialized.eia import EiaMacroProvider
from toolkit.adapters.outbound.storage.files import FileSeriesRepository
from toolkit.domain.errors import ConfigurationError
from toolkit.domain.models import MacroRequest
from toolkit.ports.inbound import StoreSeries

#: ``load_settings`` real, antes de que ``no_dotenv`` lo sustituya en cada test.
REAL_LOAD_SETTINGS = bootstrap.load_settings


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


def test_specialized_sources_are_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COINGECKO_API_PLAN", "pro")
    service = bootstrap.build_download_service("coingecko", "eia")
    assert isinstance(service.price_provider, CoinGeckoPriceProvider)
    assert service.price_provider.plan == "pro"
    assert isinstance(service.macro_provider, EiaMacroProvider)


@pytest.mark.parametrize(
    ("name", "cls"),
    [
        ("alpha_vantage", AlphaVantagePriceProvider),
        ("twelve_data", TwelveDataPriceProvider),
    ],
)
def test_market_sources_are_registered(name: str, cls: type) -> None:
    assert isinstance(bootstrap.build_download_service(name, None).price_provider, cls)


@pytest.mark.parametrize(
    ("name", "cls"),
    [
        ("ecb", EcbMacroProvider),
        ("eurostat", EurostatMacroProvider),
        ("bis", BisMacroProvider),
        ("world_bank", WorldBankMacroProvider),
        ("banco_espana", BancoEspanaMacroProvider),
        ("us_treasury", UsTreasuryMacroProvider),
        ("sec_edgar", SecEdgarMacroProvider),
    ],
)
def test_macro_sources_are_registered(name: str, cls: type) -> None:
    assert isinstance(bootstrap.build_download_service("yahoo", name).macro_provider, cls)


def test_document_services_wrap_registered_providers() -> None:
    assert isinstance(bootstrap.build_document_service("CNMV").provider, CnmvDocumentProvider)
    assert isinstance(bootstrap.build_document_service("esma").provider, EsmaDocumentProvider)
    with pytest.raises(ConfigurationError, match="documentos"):
        bootstrap.build_document_service("sec")


def test_macro_only_service_builds_no_price_provider() -> None:
    service = bootstrap.build_download_service(None, "ecb")
    assert service.price_provider is None
    assert isinstance(service.macro_provider, EcbMacroProvider)


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


def test_storage_service_wraps_file_repository(tmp_path: Path) -> None:
    service = bootstrap.build_storage_service(tmp_path, "csv")
    assert isinstance(service, StoreSeries)
    assert isinstance(service.repository, FileSeriesRepository)
    assert service.repository.directory == tmp_path


@pytest.mark.usefixtures("fake_sources")
def test_main_saves_files_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = bootstrap.main(["prices", "AAPL", "^GSPC", "--source", "fake", "--out", str(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["AAPL.csv", "_GSPC.csv"]
    assert "guardado" in capsys.readouterr().out


def test_settings_are_loaded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(bootstrap, "find_dotenv", lambda **_: ".env")
    monkeypatch.setattr(bootstrap, "load_dotenv", lambda *args, **_: calls.append(args))
    REAL_LOAD_SETTINGS.cache_clear()
    try:
        REAL_LOAD_SETTINGS()
        REAL_LOAD_SETTINGS()
    finally:
        REAL_LOAD_SETTINGS.cache_clear()
    assert len(calls) == 1
