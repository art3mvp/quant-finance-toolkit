"""Contratos de extraccion: no convierten registros ni magnitudes en precios."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Metadata:
    provider: str
    dataset: str
    identifier: str
    downloaded_at: str
    unit: str | None = None
    currency: str | None = None
    frequency: str | None = None
    published_at: str | None = None
    revised_at: str | None = None
    vintage_start: str | None = None
    vintage_end: str | None = None


@dataclass(frozen=True)
class EconomicObservation:
    metadata: Metadata
    period: str
    value: float
    kind: str = field(default="economic", init=False)


@dataclass(frozen=True)
class PriceObservation:
    metadata: Metadata
    period: str
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    adjusted: bool | None = None
    timezone: str | None = None
    kind: str = field(default="price", init=False)


@dataclass(frozen=True)
class FinancialObservation:
    metadata: Metadata
    period: str
    value: float
    period_start: str | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    accession: str | None = None
    kind: str = field(default="financial", init=False)


@dataclass(frozen=True)
class DocumentRecord:
    metadata: Metadata
    title: str
    url: str
    description: str | None = None
    kind: str = field(default="document", init=False)


@dataclass(frozen=True)
class ReferenceRecord:
    metadata: Metadata
    fields: dict[str, Any]
    kind: str = field(default="reference", init=False)


Record = (
    EconomicObservation | PriceObservation | FinancialObservation | DocumentRecord | ReferenceRecord
)
