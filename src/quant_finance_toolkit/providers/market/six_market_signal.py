import os
import re

from quant_finance_toolkit.models.data import ReferenceRecord
from quant_finance_toolkit.providers.base import (
    Provider,
    ProviderError,
    Request,
    credential,
    decode_json,
)


def request():
    dataset = os.getenv("SIX_MARKET_SIGNAL_DATASET", "SIX_1BBO")
    isin = os.getenv("SIX_MARKET_SIGNAL_ISIN", "CH0012032048")
    if not re.fullmatch(r"[A-Za-z0-9_]+", dataset) or not re.fullmatch(r"[A-Z0-9]{12}", isin):
        raise ProviderError("missing_config", "Dataset SIX o ISIN no valido")
    return Request(
        f"https://api.marketsignal.six-group.com/v1/data/CORE/{dataset}/{isin}",
        {"token": credential("SIX_MARKET_SIGNAL_TOKEN"), "limit": 5},
        dataset=f"CORE/{dataset}/{isin}",
    )


def parse(body, ctx):
    data = decode_json(body)
    if not isinstance(data, list):
        raise TypeError("SIX debe devolver una lista de registros")
    dataset = os.getenv("SIX_MARKET_SIGNAL_DATASET", "SIX_1BBO")
    isin = os.getenv("SIX_MARKET_SIGNAL_ISIN", "CH0012032048")
    # BBO is a reference/quote record, not an invented OHLCV candle.
    if any(not isinstance(r, dict) or not r.get("isin") for r in data):
        raise ValueError("Registro SIX sin ISIN")
    return [
        ReferenceRecord(ctx.meta(f"{dataset}/{isin}", currency=r.get("currency")), r) for r in data
    ]


provider = Provider(
    "six_market_signal", "market", "market", "CORE (configurable)", ("reference",), request, parse
)
