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
    dataset = os.getenv("NASDAQ_DATA_LINK_DATASET", "FRED/GDP")
    if not re.fullmatch(r"[A-Za-z0-9_]+/[A-Za-z0-9_]+", dataset):
        raise ProviderError("missing_config", "NASDAQ_DATA_LINK_DATASET debe ser BASE/SERIE")
    return Request(
        f"https://data.nasdaq.com/api/v3/datasets/{dataset}.json",
        {"api_key": credential("NASDAQ_DATA_LINK_API_KEY"), "rows": 5},
        dataset=dataset,
    )


def parse(body, ctx):
    data = decode_json(body)["dataset"]
    dataset = data["database_code"] + "/" + data["dataset_code"]
    # Dataset-dependent units and schema: preserve named fields, without assuming OHLCV.
    return [
        ReferenceRecord(
            ctx.meta(dataset, frequency=data.get("frequency"), revised_at=data.get("refreshed_at")),
            dict(zip(data["column_names"], row, strict=True)),
        )
        for row in data["data"]
    ]


provider = Provider(
    "nasdaq_data_link",
    "datasets",
    "datasets",
    "time-series (configurable)",
    ("reference",),
    request,
    parse,
)
