from datetime import UTC, datetime

from quant_finance_toolkit.models.data import PriceObservation
from quant_finance_toolkit.providers.base import Provider, Request, credential, decode_json, number


def parse(body, ctx):
    r = decode_json(body)
    if not r.get("t") or number(r["c"]) <= 0:
        return []
    return [
        PriceObservation(
            ctx.meta("AAPL", currency="USD", frequency="quote"),
            datetime.fromtimestamp(r["t"], UTC).isoformat(),
            number(r["c"]),
            open=number(r["o"]),
            high=number(r["h"]),
            low=number(r["l"]),
            timezone="UTC",
        )
    ]


provider = Provider(
    "finnhub",
    "market",
    "market",
    "quote/AAPL",
    ("price",),
    lambda: Request(
        "https://finnhub.io/api/v1/quote",
        {"symbol": "AAPL"},
        {"X-Finnhub-Token": credential("FINNHUB_API_KEY")},
    ),
    parse,
)
