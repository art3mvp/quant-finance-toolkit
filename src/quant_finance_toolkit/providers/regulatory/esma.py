from quant_finance_toolkit.models.data import DocumentRecord
from quant_finance_toolkit.providers.base import Provider, Request, decode_json


def parse(body, ctx):
    return [
        DocumentRecord(
            ctx.meta(r["id"], published_at=r.get("publication_date")),
            r["file_name"],
            r["download_link"],
        )
        for r in decode_json(body)["response"]["docs"]
        if r.get("download_link")
    ]


provider = Provider(
    "esma",
    "regulatory",
    "documents",
    "FIRDS/files",
    ("document",),
    lambda: Request(
        "https://registers.esma.europa.eu/solr/esma_registers_firds_files/select",
        {"q": "download_link:*", "rows": 5, "wt": "json", "sort": "publication_date desc"},
    ),
    parse,
)
