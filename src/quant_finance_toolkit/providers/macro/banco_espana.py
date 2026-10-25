from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, decode_json, number


def parse(body, ctx):
    return [
        EconomicObservation(
            ctx.meta(r["serie"], unit=r.get("simbolo"), frequency=r.get("codFrecuencia")),
            r["fechaValor"],
            number(r["valor"]),
        )
        for r in decode_json(body)
        if r.get("valor") is not None
    ]


provider = Provider(
    "banco_espana",
    "macro",
    "macro",
    "D_1NBAF472",
    ("economic",),
    lambda: Request(
        "https://app.bde.es/bierest/resources/srdatosapp/favoritas",
        {"idioma": "en", "series": "D_1NBAF472"},
    ),
    parse,
)
