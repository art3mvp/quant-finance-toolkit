from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, decode_json, number


def parse(body, ctx):
    data = decode_json(body)
    # JSON-stat indices are flattened across ALL dimensions, not just time.
    categories = {}
    for dim in data["id"]:
        index = data["dimension"][dim]["category"]["index"]
        categories[dim] = (
            {v: k for k, v in index.items()} if isinstance(index, dict) else dict(enumerate(index))
        )
    values = data["value"]
    values = values.items() if isinstance(values, dict) else enumerate(values)
    records = []
    for flat, value in values:
        if value is None:
            continue
        remainder, coords = int(flat), {}
        for dim, size in reversed(list(zip(data["id"], data["size"], strict=True))):
            coords[dim] = categories[dim][remainder % size]
            remainder //= size
        identifier = ".".join(coords[d] for d in data["id"] if d != "time")
        records.append(
            EconomicObservation(
                ctx.meta(
                    identifier,
                    unit=coords.get("unit"),
                    frequency=coords.get("freq"),
                    revised_at=data.get("updated"),
                ),
                coords["time"],
                number(value),
            )
        )
    return records


provider = Provider(
    "eurostat",
    "macro",
    "macro",
    "prc_hicp_manr",
    ("economic",),
    lambda: Request(
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr",
        {
            "geo": "ES",
            "coicop": "CP00",
            "unit": "RCH_A",
            "freq": "M",
            "lastTimePeriod": 5,
            "lang": "EN",
        },
    ),
    parse,
)
