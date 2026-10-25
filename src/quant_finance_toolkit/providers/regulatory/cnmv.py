import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from quant_finance_toolkit.models.data import DocumentRecord
from quant_finance_toolkit.providers.base import Provider, Request


def parse(body, ctx):
    root = ET.fromstring(body)
    records = []
    for item in root.findall(".//item"):
        fields = {child.tag.lower(): child.text for child in item}
        url = fields["link"]
        if not url or not fields.get("title"):
            raise ValueError("Documento sin titulo o enlace")
        published = fields.get("pubdate")
        records.append(
            DocumentRecord(
                ctx.meta(
                    fields.get("guid") or url,
                    published_at=parsedate_to_datetime(published).isoformat()
                    if published
                    else None,
                ),
                fields["title"],
                url,
                fields.get("description"),
            )
        )
    return records


provider = Provider(
    "cnmv",
    "regulatory",
    "documents",
    "otra_informacion_relevante_rss",
    ("document",),
    lambda: Request(
        "https://www.cnmv.es/portal/Otra-Informacion-Relevante/RSS.asmx/GetNoticiasCNMV",
        extension="xml",
    ),
    parse,
)
