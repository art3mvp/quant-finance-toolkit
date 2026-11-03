"""Periodos y frecuencias de series estadísticas, comunes a los adaptadores macro.

No es un adaptador. Las fuentes oficiales (SDMX, Banco Mundial, bancos centrales)
expresan el periodo de cada observación en formatos distintos; aquí se normalizan a la
fecha de **inicio** del periodo, que es la convención del dominio (como FRED).
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

from toolkit.domain.models import Frequency

logger = logging.getLogger(__name__)

#: Códigos de frecuencia SDMX / bancos centrales → ``Frequency``.
#: ``B`` (días hábiles) es diaria; ``S`` (semestral) se aproxima a anual, como en FRED.
FREQUENCY_CODES: dict[str, Frequency] = {
    "D": Frequency.DAILY,
    "B": Frequency.DAILY,
    "W": Frequency.WEEKLY,
    "M": Frequency.MONTHLY,
    "Q": Frequency.QUARTERLY,
    "T": Frequency.QUARTERLY,  # trimestral (Banco de España)
    "S": Frequency.ANNUAL,
    "H": Frequency.ANNUAL,
    "A": Frequency.ANNUAL,
    "Y": Frequency.ANNUAL,
}

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(\d{4})-?Q([1-4])$"), "quarter"),  # 2024-Q1, 2024Q1
    (re.compile(r"^(\d{4})-?S([12])$"), "semester"),  # 2024-S1
    (re.compile(r"^(\d{4})-?W(\d{2})$"), "week"),  # 2024-W01 (ISO)
    (re.compile(r"^(\d{4})M(\d{2})$"), "month"),  # 2024M01 (Banco Mundial)
]


def parse_period(text: str) -> pd.Timestamp:
    """Convierte un periodo a la fecha de inicio (tz-naive, medianoche).

    Formatos: ``2024-01-02``, ``2024-01-02T08:15:00Z``, ``2024-01``, ``2024M01``,
    ``2024-Q1``, ``2024-S2``, ``2024-W05`` y ``2024``.

    Raises:
        ValueError: Si el formato no se reconoce.
    """
    text = text.strip()
    for pattern, kind in _PATTERNS:
        match = pattern.match(text)
        if match:
            year, number = int(match[1]), int(match[2])
            if kind == "quarter":
                return pd.Timestamp(year, 3 * number - 2, 1)
            if kind == "semester":
                return pd.Timestamp(year, 6 * number - 5, 1)
            if kind == "month":
                return pd.Timestamp(year, number, 1)
            return pd.Timestamp.fromisocalendar(year, number, 1)
    if re.fullmatch(r"\d{4}", text):
        return pd.Timestamp(int(text), 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}", text):
        return pd.Timestamp(f"{text}-01")
    timestamp = pd.Timestamp(text)  # ISO completo, con o sin hora/zona
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp.normalize()


def frequency_from_code(code: str | None, index: pd.DatetimeIndex, label: str) -> Frequency:
    """Traduce un código de frecuencia; si falta o es desconocido, la infiere del índice."""
    key = (code or "").strip().upper()[:1]
    if key in FREQUENCY_CODES:
        return FREQUENCY_CODES[key]
    inferred = infer_frequency(index)
    logger.warning("%s: frecuencia desconocida %r; inferida %s", label, code, inferred.value)
    return inferred


def infer_frequency(index: pd.DatetimeIndex) -> Frequency:
    """Infiere la frecuencia por el número mediano de días entre observaciones."""
    if len(index) < 2:
        return Frequency.DAILY
    median_days = float(np.median(np.diff(index.values).astype("timedelta64[D]").astype(float)))
    for limit, frequency in (
        (4, Frequency.DAILY),
        (16, Frequency.WEEKLY),
        (45, Frequency.MONTHLY),
        (135, Frequency.QUARTERLY),
    ):
        if median_days <= limit:
            return frequency
    return Frequency.ANNUAL


def to_series(periods: list[str], values: list[object], name: str) -> pd.Series:
    """Construye una ``pd.Series`` float ordenada y sin duplicados (``None`` → ``NaN``).

    Raises:
        ValueError, TypeError: Si algún periodo o valor no es interpretable.
    """
    index = pd.DatetimeIndex([parse_period(str(p)) for p in periods], name="date")
    numbers = pd.to_numeric(pd.Series(values, dtype=object), errors="raise")
    series = pd.Series(numbers.to_numpy(dtype=float), index=index, name=name).sort_index()
    return series[~series.index.duplicated(keep="last")]
