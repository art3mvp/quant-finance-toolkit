import csv
import io

from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, number


def parse(body, ctx):
    rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    return [
        EconomicObservation(
            ctx.meta(
                r["KEY"], unit=r.get("UNIT"), currency=r.get("CURRENCY"), frequency=r.get("FREQ")
            ),
            r["TIME_PERIOD"],
            number(r["OBS_VALUE"]),
        )
        for r in rows
        if r.get("OBS_VALUE")
    ]


provider = Provider(
    "ecb",
    "macro",
    "macro",
    "EXR/D.USD.EUR.SP00.A",
    ("economic",),
    lambda: Request(
        "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
        {"lastNObservations": 5, "format": "csvdata"},
        extension="csv",
    ),
    parse,
)
