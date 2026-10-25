import xml.etree.ElementTree as ET

from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, number


def parse(body, ctx):
    root = ET.fromstring(body)
    records = []
    for series in root.findall(".//Series"):
        identifier = ".".join(
            series.get(k, "") for k in ("FREQ", "EER_TYPE", "EER_BASKET", "REF_AREA")
        )
        for obs in series.findall("Obs"):
            if obs.get("OBS_VALUE"):
                records.append(
                    EconomicObservation(
                        ctx.meta(identifier, unit="index (2020=100)", frequency=series.get("FREQ")),
                        obs.attrib["TIME_PERIOD"],
                        number(obs.attrib["OBS_VALUE"]),
                    )
                )
    return records


provider = Provider(
    "bis",
    "macro",
    "macro",
    "WS_EER/M.N.B.ES",
    ("economic",),
    lambda: Request(
        "https://stats.bis.org/api/v1/data/WS_EER/M.N.B.ES",
        {"startPeriod": "2024-01", "endPeriod": "2024-03"},
        extension="xml",
    ),
    parse,
)
