import json
from unittest.mock import Mock

import pytest
import requests

from quant_finance_toolkit.providers.base import (
    Context,
    HttpClient,
    ProviderError,
    Request,
    decode_json,
    load_config,
    number,
    redact,
)
from quant_finance_toolkit.providers.registry import get_providers


@pytest.fixture
def ctx():
    return Context("test", "sample", "2026-10-25T20:00:00+00:00")


def test_registry_and_public_sources_do_not_require_keys(monkeypatch):
    providers = get_providers()
    assert len(providers) == 18
    for name in (
        "ecb",
        "eurostat",
        "bis",
        "world_bank",
        "banco_espana",
        "us_treasury",
        "cnmv",
        "esma",
    ):
        assert providers[name].request().url.startswith("https://")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="FRED_API_KEY"):
        providers["fred"].request()


@pytest.mark.parametrize("value", [None, True, "NaN", "inf", "-inf", "."])
def test_reject_invalid_numbers(value):
    with pytest.raises((ValueError, TypeError)):
        number(value)


@pytest.mark.parametrize(
    "payload",
    [
        {"Note": "quota reached"},
        {"Information": "premium"},
        {"Error Message": "invalid"},
        {"error": "invalid key"},
        {"quandl_error": {"code": "QEX"}},
        {"status": "error", "message": "not authorized"},
    ],
)
def test_http_200_error_is_not_data(payload):
    with pytest.raises(ProviderError):
        decode_json(json.dumps(payload).encode())


def response(code, body=b"{}", headers=None):
    r = requests.Response()
    r.status_code, r._content = code, body
    r.headers.update(headers or {})
    return r


def test_http_retry_and_timeout(monkeypatch):
    monkeypatch.setattr("quant_finance_toolkit.providers.base.time.sleep", lambda _: None)
    client = HttpClient(timeout=7, attempts=3)
    client.session.get = Mock(
        side_effect=[requests.Timeout(), response(503), response(200, b"data")]
    )
    assert client.get(Request("https://example.com")) == b"data"
    assert client.session.get.call_count == 3
    assert client.session.get.call_args.kwargs["timeout"] == (7, 7)
    assert client.session.get.call_args.kwargs["allow_redirects"] is False


def test_large_retry_after_does_not_retry_early():
    client = HttpClient()
    client.session.get = Mock(return_value=response(429, headers={"Retry-After": "120"}))
    with pytest.raises(ProviderError) as error:
        client.get(Request("https://example.com"))
    assert error.value.status == "rate_limited"
    assert client.session.get.call_count == 1


def test_transport_exceptions_never_expose_credentials():
    client = HttpClient(attempts=1)
    client.session.get = Mock(
        side_effect=requests.ConnectionError("https://example.com?apikey=secret")
    )
    with pytest.raises(ProviderError) as error:
        client.get(Request("https://example.com"))
    assert "secret" not in str(error.value)


def test_config_does_not_override_environment(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text("FRED_API_KEY=file-value\n")
    monkeypatch.setenv("FRED_API_KEY", "environment-value")
    load_config(config)
    assert get_providers()["fred"].request().params["api_key"] == "environment-value"


def test_secret_redaction_and_eia_persistence(tmp_path, monkeypatch):
    secret = "test-sensitive-token"
    monkeypatch.setenv("EIA_API_KEY", secret)
    assert secret not in redact(f"https://example.com?api_key={secret}")
    payload = {
        "request": {"params": {"api_key": secret}},
        "response": {
            "data": [
                {
                    "series": "RWTC",
                    "period": "2024-01-01",
                    "value": "70.5",
                    "value-units": "USD/barrel",
                }
            ]
        },
    }
    client = Mock()
    client.get.return_value = json.dumps(payload).encode()
    extraction = get_providers()["eia"].fetch(client)
    paths = extraction.save(tmp_path)
    assert extraction.records[0].metadata.unit == "USD/barrel"
    for path in paths.values():
        from pathlib import Path

        text = Path(path).read_text(encoding="utf-8")
        assert secret not in text
        json.loads(text)


def test_eurostat_sparse_multidimensional_indices(ctx):
    from quant_finance_toolkit.providers.macro.eurostat import parse

    payload = {
        "id": ["geo", "time"],
        "size": [2, 2],
        "dimension": {
            "geo": {"category": {"index": {"ES": 0, "FR": 1}}},
            "time": {"category": {"index": {"2024": 0, "2025": 1}}},
        },
        "value": {"0": 1, "3": 2},
    }
    records = parse(json.dumps(payload).encode(), ctx)
    assert [(r.metadata.identifier, r.period, r.value) for r in records] == [
        ("ES", "2024", 1),
        ("FR", "2025", 2),
    ]


def test_esma_skips_maintenance_marker(ctx):
    from quant_finance_toolkit.providers.regulatory.esma import parse

    payload = {
        "response": {
            "docs": [
                {"id": "lastModification"},
                {
                    "id": "1",
                    "file_name": "test.zip",
                    "download_link": "https://firds.esma.europa.eu/test.zip",
                },
            ]
        }
    }
    assert len(parse(json.dumps(payload).encode(), ctx)) == 1


def test_cnmv_capitalized_title_and_publication_date(ctx):
    from quant_finance_toolkit.providers.regulatory.cnmv import parse

    records = parse(
        b"<rss><Channel><item><Title>Issuer</Title><link>https://www.cnmv.es/1</link>"
        b"<pubDate>Fri, 23 Oct 2026 17:57:35 GMT</pubDate></item></Channel></rss>",
        ctx,
    )
    assert records[0].title == "Issuer"
    assert records[0].metadata.published_at == "2026-10-23T17:57:35+00:00"


def test_empty_and_invalid_responses_are_not_success():
    client = Mock()
    client.get.return_value = b'{"observations": []}'
    # Use public source so no credentials are needed in offline tests.
    provider = get_providers()["world_bank"]
    client.get.return_value = b"[{}, []]"
    with pytest.raises(ProviderError) as error:
        provider.fetch(client)
    assert error.value.status == "empty"
    client.get.return_value = b"<html>Access denied</html>"
    with pytest.raises(ProviderError) as error:
        provider.fetch(client)
    assert error.value.status == "invalid_response"


def test_finnhub_zero_quote_is_not_data(ctx):
    from quant_finance_toolkit.providers.market.finnhub import parse

    assert parse(b'{"c":0,"t":0}', ctx) == []


def test_coingecko_plan_and_header(monkeypatch):
    from quant_finance_toolkit.providers.specialized.coingecko import request

    monkeypatch.setenv("COINGECKO_API_PLAN", "pro")
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        request()
    monkeypatch.setenv("COINGECKO_API_KEY", "secret")
    req = request()
    assert req.url.startswith("https://pro-api.coingecko.com/")
    assert req.headers == {"x-cg-pro-api-key": "secret"}
    assert "secret" not in repr(req)


def test_sec_preserves_fiscal_and_publication_context(ctx):
    from quant_finance_toolkit.providers.regulatory.sec_edgar import parse

    payload = {
        "cik": 320193,
        "taxonomy": "us-gaap",
        "tag": "Assets",
        "units": {
            "USD": [
                {
                    "end": "2024-09-30",
                    "val": 42,
                    "filed": "2024-11-01",
                    "fy": 2024,
                    "fp": "FY",
                    "form": "10-K",
                    "accn": "original-id",
                }
            ]
        },
    }
    record = parse(json.dumps(payload).encode(), ctx)[0]
    assert record.metadata.published_at == "2024-11-01"
    assert record.period == "2024-09-30"
    assert record.accession == "original-id"
    assert record.fiscal_year == 2024


def test_nasdaq_columns_not_assumed_to_be_prices(ctx):
    from quant_finance_toolkit.providers.datasets.nasdaq_data_link import parse

    payload = {
        "dataset": {
            "database_code": "X",
            "dataset_code": "Y",
            "column_names": ["Date", "Value"],
            "data": [["2024-01-01", 12]],
        }
    }
    record = parse(json.dumps(payload).encode(), ctx)[0]
    assert record.kind == "reference"
    assert record.fields == {"Date": "2024-01-01", "Value": 12}


def test_yahoo_serializes_mapping_timestamps_and_dataframes(monkeypatch):
    from collections import UserDict

    import pandas as pd
    import yfinance as yf

    from quant_finance_toolkit.providers.market.yahoo import provider

    date = pd.Timestamp("2024-01-02", tz="America/New_York")
    frame = pd.DataFrame(
        {"Open": [1], "High": [3], "Low": [1], "Close": [2], "Volume": [5]},
        index=pd.DatetimeIndex([date], name="Date"),
    )
    ticker = Mock()
    ticker.history.return_value = frame
    ticker.history_metadata = UserDict(
        {
            "currency": "USD",
            "exchangeTimezoneName": "America/New_York",
            "firstTradeDate": date,
            "tradingPeriods": frame,
        }
    )
    monkeypatch.setattr(yf, "Ticker", lambda _: ticker)
    extraction = provider.fetch(HttpClient())
    payload = json.loads(extraction.raw)
    assert payload["metadata"]["firstTradeDate"] == date.isoformat()
    assert payload["metadata"]["tradingPeriods"]["data"]
    assert extraction.records[0].close == 2
    assert extraction.records[0].adjusted is False


def test_fred_vintage_is_not_publication_date(ctx):
    from quant_finance_toolkit.providers.macro.fred import parse

    payload = {
        "observations": [
            {
                "date": "2024-01-01",
                "value": "5.33",
                "realtime_start": "2026-10-25",
                "realtime_end": "2026-10-25",
            }
        ]
    }
    record = parse(json.dumps(payload).encode(), ctx)[0]
    assert record.metadata.vintage_start == "2026-10-25"
    assert record.metadata.published_at is None
    assert record.metadata.revised_at is None


def test_batch_continues_and_returns_nonzero(tmp_path, monkeypatch):
    from quant_finance_toolkit.providers import check

    calls = []

    class BrokenProvider:
        group, dataset = "macro", "test"

        def fetch(self, client):
            calls.append(1)
            raise ProviderError("empty", "No data")

    monkeypatch.setattr(
        check, "get_providers", lambda: {"a": BrokenProvider(), "b": BrokenProvider()}
    )
    report = tmp_path / "report.json"
    assert check.main(["--env-file", str(tmp_path / "missing"), "--report", str(report)]) == 1
    assert len(calls) == 2
    assert len(json.loads(report.read_text())["results"]) == 2
