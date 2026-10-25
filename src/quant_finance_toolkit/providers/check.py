"""Comprobacion explicita en vivo; nunca se ejecuta al importar el paquete."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from quant_finance_toolkit.providers.base import HttpClient, ProviderError, load_config, redact
from quant_finance_toolkit.providers.registry import get_providers


def main(argv=None) -> int:
    providers = get_providers()
    parser = argparse.ArgumentParser(description="Descargar y validar una muestra por proveedor")
    parser.add_argument(
        "--provider", action="append", choices=providers, help="Repetible; defecto: todos"
    )
    parser.add_argument("--env-file", default="config/.env")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--report", type=Path, default=Path("reports/provider-check.json"))
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.attempts < 1:
        parser.error("timeout y attempts deben ser positivos")
    load_config(args.env_file)
    client = HttpClient(args.timeout, args.attempts)
    results = []
    try:
        for name in dict.fromkeys(args.provider or providers):
            provider = providers[name]
            result = {"provider": name, "group": provider.group, "dataset": provider.dataset}
            try:
                extraction = provider.fetch(client)
                paths = extraction.save(args.data_dir)
                result.update(
                    status="ok",
                    records=len(extraction.records),
                    files=paths,
                    dataset=extraction.dataset,
                    downloaded_at=extraction.downloaded_at,
                )
                if name == "coingecko":
                    result["access"] = (
                        "authenticated" if os.getenv("COINGECKO_API_KEY") else "public"
                    )
            except ProviderError as exc:
                result.update(status=exc.status, records=0, detail=redact(str(exc)))
            except Exception as exc:  # noqa: BLE001 - isolate each provider in the batch
                # Keep checking the rest; do not expose arbitrary exception messages.
                result.update(status="error", records=0, detail=type(exc).__name__)
            results.append(result)
            print(
                f"{name:20s} {result['status']:18s} {result['records']:4d} registros"
                + (f" | {result['detail']}" if "detail" in result else ""),
                flush=True,
            )
    finally:
        client.close()
    report = {"checked_at": datetime.now(UTC).isoformat(), "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        redact(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8"
    )
    print(f"Informe: {args.report}")
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
