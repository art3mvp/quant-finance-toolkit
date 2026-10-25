from quant_finance_toolkit.models.data import PriceObservation
from quant_finance_toolkit.providers.base import Provider, Request, credential, decode_json, number


def parse(body, ctx):
    data = decode_json(body)
    return [
        PriceObservation(
            ctx.meta("IBM", currency="USD", frequency="daily"),
            date,
            number(r["4. close"]),
            open=number(r["1. open"]),
            high=number(r["2. high"]),
            low=number(r["3. low"]),
            volume=number(r["5. volume"]),
            adjusted=False,
            timezone=data["Meta Data"].get("5. Time Zone"),
        )
        for date, r in sorted(data["Time Series (Daily)"].items(), reverse=True)[:5]
    ]


provider = Provider(
    "alpha_vantage",
    "market",
    "market",
    "TIME_SERIES_DAILY/IBM",
    ("price",),
    lambda: Request(
        "https://www.alphavantage.co/query",
        {
            "function": "TIME_SERIES_DAILY",
            "symbol": "IBM",
            "outputsize": "compact",
            "apikey": credential("ALPHA_VANTAGE_API_KEY"),
        },
    ),
    parse,
)
