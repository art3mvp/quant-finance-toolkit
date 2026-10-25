"""Comprobacion de instalacion sin acceso a APIs externas."""

from quant_finance_toolkit import __version__


def main() -> None:
    print(f"quant-finance-toolkit {__version__}: entorno preparado.")


if __name__ == "__main__":
    main()
