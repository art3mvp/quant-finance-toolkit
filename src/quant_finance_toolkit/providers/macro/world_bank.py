from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, decode_json, number


def parse(body, ctx):
    data = decode_json(body)
    return [
        EconomicObservation(
            ctx.meta(
                r["countryiso3code"] + ":" + r["indicator"]["id"],
                unit="current USD",
                currency="USD",
                frequency="annual",
                revised_at=data[0].get("lastupdated"),
            ),
            r["date"],
            number(r["value"]),
        )
        for r in data[1]
        if r["value"] is not None
    ]


provider = Provider(
    "world_bank",
    "macro",
    "macro",
    "NY.GDP.MKTP.CD/ESP",
    ("economic",),
    lambda: Request(
        "https://api.worldbank.org/v2/country/ESP/indicator/NY.GDP.MKTP.CD",
        {"format": "json", "mrv": 5, "per_page": 5},
    ),
    parse,
)
