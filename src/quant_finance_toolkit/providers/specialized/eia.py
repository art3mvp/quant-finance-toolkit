from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, credential, decode_json, number


def parse(body, ctx):
    return [
        EconomicObservation(
            ctx.meta(r["series"], unit=r.get("value-units"), frequency="daily"),
            r["period"],
            number(r["value"]),
        )
        for r in decode_json(body)["response"]["data"]
        if r.get("value") is not None
    ]


provider = Provider(
    "eia",
    "specialized",
    "energy",
    "petroleum/pri/spt/RWTC",
    ("economic",),
    lambda: Request(
        "https://api.eia.gov/v2/petroleum/pri/spt/data/",
        {
            "api_key": credential("EIA_API_KEY"),
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RWTC",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 5,
        },
    ),
    parse,
)
