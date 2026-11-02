"""Proveedores fake para tests: series sintéticas deterministas, sin red.

Implementan los puertos ``PriceProvider`` y ``MacroProvider`` y viven fuera de ``src``
porque son código de test. Sirven para:
    * Tests unitarios del servicio, la CLI y el composition root.
    * Desarrollar ``Portfolio`` y Monte Carlo sin red (desde la raíz del repo)::

        from tests.fakes import FakePriceProvider
        service = DownloadService(FakePriceProvider())

La semilla se deriva del ticker con CRC32 (estable entre ejecuciones, a diferencia de
``hash()``), así que el mismo ticker y rango producen siempre la misma serie.

Ejemplo::

    provider = FakePriceProvider(not_found={"XXX"}, fail_on={"BOOM"})
    series = provider.fetch_prices("AAPL", date(2023, 1, 1), date(2023, 12, 31),
                                   Frequency.DAILY, AssetType.EQUITY)
"""

from __future__ import annotations

import threading
import zlib
from collections.abc import Iterable, Mapping
from datetime import date, timedelta

import numpy as np
import pandas as pd

from toolkit.domain.errors import ProviderError, SeriesNotFoundError
from toolkit.domain.models import AssetType, Frequency, MacroSeries, PriceSeries

#: Rango por defecto cuando la petición no indica fechas.
DEFAULT_END = date(2024, 12, 31)
DEFAULT_LOOKBACK = timedelta(days=365 * 2)

_PANDAS_FREQ: dict[Frequency, str] = {
    Frequency.DAILY: "B",
    Frequency.WEEKLY: "W-FRI",
    Frequency.MONTHLY: "ME",
    Frequency.QUARTERLY: "QE",
    Frequency.ANNUAL: "YE",
}

#: Drift y volatilidad por periodo de cada frecuencia (aprox. a partir de 7 % / 20 % anual).
_PERIOD_PARAMS: dict[Frequency, tuple[float, float]] = {
    Frequency.DAILY: (0.07 / 252, 0.20 / np.sqrt(252)),
    Frequency.WEEKLY: (0.07 / 52, 0.20 / np.sqrt(52)),
    Frequency.MONTHLY: (0.07 / 12, 0.20 / np.sqrt(12)),
    Frequency.QUARTERLY: (0.07 / 4, 0.20 / 2),
    Frequency.ANNUAL: (0.07, 0.20),
}


def _seed(key: str) -> int:
    """Semilla determinista a partir de una cadena."""
    return zlib.crc32(key.encode("utf-8"))


def _resolve_range(start: date | None, end: date | None) -> tuple[date, date]:
    """Aplica el rango por defecto cuando faltan fechas."""
    end = end or DEFAULT_END
    start = start or (end - DEFAULT_LOOKBACK)
    return start, end


class _CallRecorder:
    """Registro thread-safe de las llamadas recibidas (útil para aserciones en tests)."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self._lock = threading.Lock()

    def _record(self, *args: object) -> None:
        with self._lock:
            self.calls.append(args)


class FakePriceProvider(_CallRecorder):
    """Proveedor de precios sintéticos: paseo aleatorio geométrico por ticker.

    Args:
        not_found: Tickers para los que se lanza ``SeriesNotFoundError``.
        fail_on: Tickers para los que se lanza ``ProviderError`` (fallo genérico).
        fixtures: Series predefinidas que se devuelven tal cual para ciertos tickers.
        name: Nombre de la fuente que se guarda en ``PriceSeries.source``.
    """

    def __init__(
        self,
        not_found: Iterable[str] = (),
        fail_on: Iterable[str] = (),
        fixtures: Mapping[str, PriceSeries] | None = None,
        name: str = "fake",
    ) -> None:
        super().__init__()
        self.name = name
        self.not_found = {t.upper() for t in not_found}
        self.fail_on = {t.upper() for t in fail_on}
        self.fixtures = dict(fixtures or {})

    def fetch_prices(
        self,
        ticker: str,
        start: date | None,
        end: date | None,
        interval: Frequency,
        asset_type: AssetType,
    ) -> PriceSeries:
        """Genera (o devuelve del fixture) la serie de precios de ``ticker``."""
        self._record(ticker, start, end, interval, asset_type)
        key = ticker.upper()
        if key in self.not_found:
            raise SeriesNotFoundError(f"{self.name}: no hay datos para {ticker}")
        if key in self.fail_on:
            raise ProviderError(f"{self.name}: fallo simulado para {ticker}")
        if ticker in self.fixtures:
            return self.fixtures[ticker]

        start, end = _resolve_range(start, end)
        index = pd.date_range(start, end, freq=_PANDAS_FREQ[interval])
        if index.empty:
            raise SeriesNotFoundError(f"{self.name}: rango sin observaciones para {ticker}")

        rng = np.random.default_rng(_seed(key))
        mu, sigma = _PERIOD_PARAMS[interval]
        n = len(index)
        log_ret = rng.normal(mu - 0.5 * sigma**2, sigma, size=n)
        close = 100.0 * np.exp(np.cumsum(log_ret))
        open_ = np.concatenate(([100.0], close[:-1]))
        spread = np.abs(rng.normal(0.0, sigma / 2, size=n))
        data = pd.DataFrame(
            {
                "open": open_,
                "high": np.maximum(open_, close) * (1 + spread),
                "low": np.minimum(open_, close) * (1 - spread),
                "close": close,
                "adj_close": close,
                "volume": rng.integers(1_000_000, 5_000_000, size=n).astype(float),
            },
            index=pd.DatetimeIndex(index.normalize(), name="date"),
        )
        return PriceSeries(
            ticker=ticker,
            name=f"Fake {ticker}",
            asset_type=asset_type,
            source=self.name,
            currency="USD",
            frequency=interval,
            data=data,
        )


class FakeMacroProvider(_CallRecorder):
    """Proveedor macro sintético: serie mensual determinista alrededor de 100.

    Si se pasa ``as_of``, simula ALFRED: descarta las observaciones posteriores a esa
    fecha y guarda ``vintage=as_of``.

    Args:
        not_found: Identificadores para los que se lanza ``SeriesNotFoundError``.
        fail_on: Identificadores para los que se lanza ``ProviderError``.
        fixtures: Series predefinidas que se devuelven tal cual.
        name: Nombre de la fuente.
    """

    def __init__(
        self,
        not_found: Iterable[str] = (),
        fail_on: Iterable[str] = (),
        fixtures: Mapping[str, MacroSeries] | None = None,
        name: str = "fake",
    ) -> None:
        super().__init__()
        self.name = name
        self.not_found = {s.upper() for s in not_found}
        self.fail_on = {s.upper() for s in fail_on}
        self.fixtures = dict(fixtures or {})

    def fetch_series(
        self,
        series_id: str,
        start: date | None,
        end: date | None,
        as_of: date | None,
    ) -> MacroSeries:
        """Genera (o devuelve del fixture) la serie macro ``series_id``."""
        self._record(series_id, start, end, as_of)
        key = series_id.upper()
        if key in self.not_found:
            raise SeriesNotFoundError(f"{self.name}: la serie {series_id} no existe")
        if key in self.fail_on:
            raise ProviderError(f"{self.name}: fallo simulado para {series_id}")
        if series_id in self.fixtures:
            return self.fixtures[series_id]

        start, end = _resolve_range(start, end)
        if as_of is not None:
            end = min(end, as_of)
        index = pd.date_range(start, end, freq="MS")
        if index.empty:
            raise SeriesNotFoundError(f"{self.name}: rango sin observaciones para {series_id}")

        rng = np.random.default_rng(_seed(key))
        values = 100.0 + np.cumsum(rng.normal(0.2, 1.0, size=len(index)))
        return MacroSeries(
            series_id=series_id,
            name=f"Fake {series_id}",
            source=self.name,
            units="Index",
            frequency=Frequency.MONTHLY,
            data=pd.Series(values, index=pd.DatetimeIndex(index, name="date"), name=series_id),
            vintage=as_of,
        )
