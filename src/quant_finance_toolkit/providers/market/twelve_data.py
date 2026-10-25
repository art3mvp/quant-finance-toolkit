from quant_finance_toolkit.models.data import PriceObservation
from quant_finance_toolkit.providers.base import (
    Provider,
    Request,
    credential,
    decode_json,
    number,
    optional_number,
)


def parse(body, ctx):
    data = decode_json(body)
    meta = data["meta"]
    return [
        PriceObservation(
            ctx.meta(meta["symbol"], currency=meta.get("currency"), frequency=meta.get("interval")),
            r["datetime"],
            number(r["close"]),
            open=number(r["open"]),
            high=number(r["high"]),
            low=number(r["low"]),
            volume=optional_number(r.get("volume")),
            adjusted=False,
            timezone=meta.get("exchange_timezone"),
        )
        for r in data["values"]
    ]


provider = Provider(
    "twelve_data",
    "market",
    "market",
    "time_series/AAPL/1day",
    ("price",),
    lambda: Request(
        "https://api.twelvedata.com/time_series",
        {
            "symbol": "AAPL",
            "interval": "1day",
            "outputsize": 5,
            "adjust": "none",
            "apikey": credential("TWELVE_DATA_API_KEY"),
        },
    ),
    parse,
)
