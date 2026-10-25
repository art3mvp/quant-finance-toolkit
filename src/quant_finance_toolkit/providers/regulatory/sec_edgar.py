from quant_finance_toolkit.models.data import FinancialObservation
from quant_finance_toolkit.providers.base import Provider, Request, credential, decode_json, number


def parse(body, ctx):
    data = decode_json(body)
    return [
        FinancialObservation(
            ctx.meta(
                f"CIK{data['cik']:010d}/{data['taxonomy']}/{data['tag']}",
                unit="USD",
                currency="USD",
                published_at=r.get("filed"),
            ),
            r["end"],
            number(r["val"]),
            period_start=r.get("start"),
            fiscal_year=r.get("fy"),
            fiscal_period=r.get("fp"),
            form=r.get("form"),
            accession=r.get("accn"),
        )
        for r in data["units"]["USD"][-5:]
    ]


provider = Provider(
    "sec_edgar",
    "regulatory",
    "fundamentals",
    "CIK0000320193/us-gaap/Assets",
    ("financial",),
    lambda: Request(
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json",
        headers={"User-Agent": credential("SEC_USER_AGENT")},
    ),
    parse,
)
