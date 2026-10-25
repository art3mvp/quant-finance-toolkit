from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, credential, decode_json, number


def parse(body, ctx):
    return [
        EconomicObservation(
            ctx.meta(
                "FEDFUNDS",
                unit="percent",
                frequency="monthly",
                vintage_start=r.get("realtime_start"),
                vintage_end=r.get("realtime_end"),
            ),
            r["date"],
            number(r["value"]),
        )
        for r in decode_json(body)["observations"]
        if r["value"] != "."
    ]


provider = Provider(
    "fred",
    "macro",
    "macro",
    "FEDFUNDS",
    ("economic",),
    lambda: Request(
        "https://api.stlouisfed.org/fred/series/observations",
        {
            "api_key": credential("FRED_API_KEY"),
            "series_id": "FEDFUNDS",
            "file_type": "json",
            "sort_order": "desc",
            "limit": 5,
        },
    ),
    parse,
)
