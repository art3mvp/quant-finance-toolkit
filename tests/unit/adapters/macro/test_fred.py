"""Tests del adaptador FRED/ALFRED con HTTP mockeado mediante ``responses`` (sin red)."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest
import responses
from responses import matchers

from toolkit.adapters.outbound.macro.fred import (
    DEFAULT_BASE_URL,
    FredMacroProvider,
    map_frequency,
    parse_observations,
)
from toolkit.domain.errors import ConfigurationError, ProviderError, SeriesNotFoundError
from toolkit.domain.models import Frequency, MacroSeries
from toolkit.ports.outbound import MacroProvider

KEY = "test-key-123"
SERIES_URL = f"{DEFAULT_BASE_URL}/series"
OBS_URL = f"{DEFAULT_BASE_URL}/series/observations"

META = {
    "seriess": [
        {
            "id": "CPIAUCSL",
            "title": "Consumer Price Index for All Urban Consumers",
            "units": "Index 1982-1984=100",
            "frequency_short": "M",
        }
    ]
}
OBS = {
    "observations": [
        {"realtime_start": "x", "realtime_end": "x", "date": "2020-01-01", "value": "258.7"},
        {"realtime_start": "x", "realtime_end": "x", "date": "2020-02-01", "value": "."},
        {"realtime_start": "x", "realtime_end": "x", "date": "2020-03-01", "value": "258.1"},
    ]
}


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def sleeper() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def provider(sleeper: SleepRecorder) -> FredMacroProvider:
    return FredMacroProvider(api_key=KEY, sleep=sleeper)


def test_satisfies_port() -> None:
    assert isinstance(FredMacroProvider(api_key=None), MacroProvider)


@responses.activate
def test_fred_mode_parses_dot_as_nan(provider: FredMacroProvider) -> None:
    responses.get(SERIES_URL, json=META)
    responses.get(
        OBS_URL,
        json=OBS,
        match=[
            matchers.query_param_matcher(
                {
                    "series_id": "CPIAUCSL",
                    "api_key": KEY,
                    "file_type": "json",
                    "observation_start": "2020-01-01",
                    "observation_end": "2020-03-31",
                }
            )
        ],
    )

    series = provider.fetch_series("CPIAUCSL", date(2020, 1, 1), date(2020, 3, 31), None)

    assert isinstance(series, MacroSeries)
    assert series.source == "fred"
    assert series.name == "Consumer Price Index for All Urban Consumers"
    assert series.units == "Index 1982-1984=100"
    assert series.frequency is Frequency.MONTHLY
    assert series.vintage is None
    assert series.n_obs == 3
    assert math.isnan(series.data.iloc[1])
    assert series.mean == pytest.approx((258.7 + 258.1) / 2)
    assert "realtime_start" not in responses.calls[1].request.url


@responses.activate
def test_alfred_mode_sends_realtime_params(provider: FredMacroProvider) -> None:
    realtime = {"realtime_start": "2015-06-30", "realtime_end": "2015-06-30"}
    responses.get(
        SERIES_URL, json=META, match=[matchers.query_param_matcher(realtime, strict_match=False)]
    )
    responses.get(
        OBS_URL,
        json=OBS,
        match=[
            matchers.query_param_matcher(
                {"series_id": "CPIAUCSL", "observation_start": "2000-01-01", **realtime},
                strict_match=False,
            )
        ],
    )

    series = provider.fetch_series("CPIAUCSL", date(2000, 1, 1), None, as_of=date(2015, 6, 30))

    assert series.vintage == date(2015, 6, 30)
    assert len(responses.calls) == 2


@responses.activate
def test_retries_on_429_with_exponential_backoff(
    provider: FredMacroProvider, sleeper: SleepRecorder
) -> None:
    responses.get(SERIES_URL, json=META)
    responses.get(OBS_URL, status=429, json={"error_code": 429, "error_message": "Too Many"})
    responses.get(OBS_URL, status=503, body="unavailable")
    responses.get(OBS_URL, json=OBS)

    series = provider.fetch_series("CPIAUCSL", None, None, None)

    assert series.n_obs == 3
    assert sleeper.delays == [0.5, 1.0]
    assert len(responses.calls) == 4


@responses.activate
def test_retry_after_header_is_respected(
    provider: FredMacroProvider, sleeper: SleepRecorder
) -> None:
    responses.get(SERIES_URL, status=429, headers={"Retry-After": "7"})
    responses.get(SERIES_URL, json=META)
    responses.get(OBS_URL, json=OBS)
    provider.fetch_series("CPIAUCSL", None, None, None)
    assert sleeper.delays == [7.0]


@responses.activate
def test_gives_up_after_max_retries(provider: FredMacroProvider, sleeper: SleepRecorder) -> None:
    responses.get(SERIES_URL, status=500, body="boom")
    with pytest.raises(ProviderError, match="reintentos"):
        provider.fetch_series("CPIAUCSL", None, None, None)
    assert len(responses.calls) == 4  # 1 intento + 3 reintentos
    assert sleeper.delays == [0.5, 1.0, 2.0]


def test_missing_api_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="FRED_API_KEY"):
        FredMacroProvider(api_key=None).fetch_series("CPIAUCSL", None, None, None)
    with pytest.raises(ConfigurationError):
        FredMacroProvider(api_key="   ").fetch_series("CPIAUCSL", None, None, None)


@responses.activate
def test_unknown_series_raises_not_found(provider: FredMacroProvider) -> None:
    responses.get(
        SERIES_URL,
        status=400,
        json={"error_code": 400, "error_message": "Bad Request.  The series does not exist."},
    )
    with pytest.raises(SeriesNotFoundError, match="does not exist"):
        provider.fetch_series("NOPE", None, None, None)


@responses.activate
def test_rejected_api_key_raises_configuration_error_without_leaking_key(
    provider: FredMacroProvider,
) -> None:
    responses.get(
        SERIES_URL,
        status=400,
        json={
            "error_code": 400,
            "error_message": f"Bad Request.  The value for variable api_key ({KEY}) is invalid.",
        },
    )
    with pytest.raises(ConfigurationError) as excinfo:
        provider.fetch_series("CPIAUCSL", None, None, None)
    assert KEY not in str(excinfo.value)


@responses.activate
def test_other_http_errors_raise_provider_error(provider: FredMacroProvider) -> None:
    responses.get(SERIES_URL, status=403, body="forbidden")
    with pytest.raises(ProviderError) as excinfo:
        provider.fetch_series("CPIAUCSL", None, None, None)
    assert not isinstance(excinfo.value, SeriesNotFoundError)


@responses.activate
def test_empty_observations_raise_not_found(provider: FredMacroProvider) -> None:
    responses.get(SERIES_URL, json=META)
    responses.get(OBS_URL, json={"observations": []})
    with pytest.raises(SeriesNotFoundError):
        provider.fetch_series("CPIAUCSL", None, None, None)


def test_parse_observations_sorts_and_rejects_garbage() -> None:
    payload = {
        "observations": [{"date": "2020-02-01", "value": "2"}, {"date": "2020-01-01", "value": "1"}]
    }
    assert parse_observations(payload, "X").tolist() == [1.0, 2.0]
    with pytest.raises(ProviderError):
        parse_observations({"observations": [{"date": "2020-01-01", "value": "abc"}]}, "X")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("D", Frequency.DAILY),
        ("W", Frequency.WEEKLY),
        ("BW", Frequency.WEEKLY),
        ("M", Frequency.MONTHLY),
        ("Q", Frequency.QUARTERLY),
        ("SA", Frequency.ANNUAL),
        ("A", Frequency.ANNUAL),
    ],
)
def test_map_frequency(code: str, expected: Frequency) -> None:
    assert map_frequency(code, pd.DatetimeIndex([]), "X") is expected


def test_map_frequency_infers_when_unknown() -> None:
    index = pd.date_range("2020-01-01", periods=8, freq="QS")
    assert map_frequency(None, index, "X") is Frequency.QUARTERLY
