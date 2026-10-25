from quant_finance_toolkit.models.data import EconomicObservation
from quant_finance_toolkit.providers.base import Provider, Request, decode_json, number


def parse(body, ctx):
    return [
        EconomicObservation(
            ctx.meta("tot_pub_debt_out_amt", unit="USD", currency="USD", frequency="daily"),
            r["record_date"],
            number(r["tot_pub_debt_out_amt"]),
        )
        for r in decode_json(body)["data"]
    ]


provider = Provider(
    "us_treasury",
    "fiscal",
    "fiscal",
    "debt_to_penny",
    ("economic",),
    lambda: Request(
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
        {"sort": "-record_date", "page[size]": 5, "fields": "record_date,tot_pub_debt_out_amt"},
    ),
    parse,
)
