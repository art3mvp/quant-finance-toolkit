from importlib import import_module

MODULES = {
    "macro": ("ecb", "fred", "eurostat", "bis", "world_bank", "banco_espana"),
    "fiscal": ("us_treasury",),
    "regulatory": ("sec_edgar", "cnmv", "esma"),
    "market": ("twelve_data", "alpha_vantage", "finnhub", "yahoo", "six_market_signal"),
    "specialized": ("eia", "coingecko"),
    "datasets": ("nasdaq_data_link",),
}


def get_providers():
    return {
        name: import_module(f"quant_finance_toolkit.providers.{group}.{name}").provider
        for group, names in MODULES.items()
        for name in names
    }
