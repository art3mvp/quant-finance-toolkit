import json
from datetime import UTC, datetime

from quant_finance_toolkit.models.data import PriceObservation
from quant_finance_toolkit.providers.base import Context, Extraction, ProviderError, number


class YahooProvider:
    id = "yahoo"
    group = "market"
    domain = "market"
    dataset = "history/AAPL/5d"
    capabilities = ("price",)

    def fetch(self, client):
        import yfinance as yf

        try:
            ticker = yf.Ticker("AAPL")
            frame = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False,
                timeout=client.timeout,
                raise_errors=True,
            )
            meta = ticker.history_metadata
        except Exception:  
             raise ProviderError(
                "network_error", "yfinance no pudo descargar el historico"
            ) from None
        if frame.empty:
            raise ProviderError("empty", "yfinance no devolvio precios")
        now = datetime.now(UTC).isoformat()
        ctx = Context(self.id, self.dataset, now)
        records = [
            PriceObservation(
                ctx.meta("AAPL", currency=meta.get("currency"), frequency="daily"),
                date.isoformat(),
                number(r["Close"]),
                open=number(r["Open"]),
                high=number(r["High"]),
                low=number(r["Low"]),
                volume=number(r["Volume"]),
                adjusted=False,
                timezone=meta.get("exchangeTimezoneName"),
            )
            for date, r in frame.iterrows()
        ]

    
        def serialize(value):
            if hasattr(value, "to_json"):
                return json.loads(value.to_json(orient="table", date_format="iso"))
            if hasattr(value, "isoformat"):
                return value.isoformat()
            raise TypeError(type(value).__name__)

        raw = json.dumps(
            {
                "format": "yfinance_dataframe",
                "metadata": dict(meta.items()),
                "data": json.loads(frame.to_json(orient="table", date_format="iso")),
            },
            default=serialize,
        )
        return Extraction(
            self.id, self.group, self.domain, self.dataset, now, records, raw.encode()
        )


provider = YahooProvider()
