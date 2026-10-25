import os
from datetime import UTC, datetime

from quant_finance_toolkit.models.data import PriceObservation
from quant_finance_toolkit.providers.base import (
    Provider,
    ProviderError,
    Request,
    credential,
    decode_json,
    number,
)


def request():
    plan = os.getenv("COINGECKO_API_PLAN", "demo").strip().lower()
    if plan not in ("demo", "pro"):
        raise ProviderError("missing_config", "COINGECKO_API_PLAN debe ser demo o pro")
    key = credential("COINGECKO_API_KEY") if plan == "pro" else os.getenv("COINGECKO_API_KEY")
    host = "pro-api" if plan == "pro" else "api"
    return Request(
        f"https://{host}.coingecko.com/api/v3/simple/price",
        {"ids": "bitcoin", "vs_currencies": "usd", "include_last_updated_at": "true"},
        {f"x-cg-{plan}-api-key": key} if key else {},
    )


def parse(body, ctx):
    data = decode_json(body)["bitcoin"]
    return [
        PriceObservation(
            ctx.meta("bitcoin", currency="USD", frequency="quote"),
            datetime.fromtimestamp(data["last_updated_at"], UTC).isoformat(),
            number(data["usd"]),
            timezone="UTC",
        )
    ]


provider = Provider(
    "coingecko", "specialized", "crypto", "simple/price/bitcoin", ("price",), request, parse
)
