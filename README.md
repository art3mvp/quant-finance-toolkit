# Toolkit financiero

Toolkit en Python para **extraer, estandarizar y analizar datos bursátiles y
macroeconómicos** y, en próximas fases, **gestionar carteras**. Taller B1-T1, Máster de IA
aplicada a mercados financieros.

- Descarga **multifuente**, con un adaptador por fuente agrupado por tipo:

  | Tipo | Fuente | Datos | `--source` | Clave |
  |------|--------|-------|------------|-------|
  | market | Yahoo Finance | acciones e índices (OHLCV) | `yahoo` | no |
  | market | Alpha Vantage | acciones (OHLCV diario/semanal/mensual) | `alpha_vantage` | `ALPHA_VANTAGE_API_KEY` |
  | market | Twelve Data | acciones, índices, ETFs (OHLCV) | `twelve_data` | `TWELVE_DATA_API_KEY` |
  | macro | FRED/ALFRED | series macro, con vintages (*look-ahead bias*) | `fred` | `FRED_API_KEY` |
  | macro | BCE | tipos de cambio, tipos oficiales, HICP | `ecb` | no |
  | macro | Eurostat | precios, empleo, PIB de la UE | `eurostat` | no |
  | macro | BIS | tipos de cambio efectivos, tipos oficiales, vivienda | `bis` | no |
  | macro | Banco Mundial | indicadores por país (PIB, inflación...) | `world_bank` | no |
  | macro | Banco de España | Euríbor, tipos, crédito... | `banco_espana` | no |
  | fiscal | U.S. Treasury Fiscal Data | deuda pública, tipos medios de la deuda... | `us_treasury` | no |
  | specialized | CoinGecko | criptoactivos (cierre + volumen) | `coingecko` | opcional |
  | specialized | EIA | energía: WTI, Brent, gas Henry Hub... | `eia` | `EIA_API_KEY` |
- **Formato estándar** para todas las fuentes (`PriceSeries`, `MacroSeries`) con
  estadísticos calculados automáticamente.
- Descarga **en lote y en paralelo**: un fallo individual no tumba el lote.
- **Arquitectura hexagonal**: añadir una fuente nueva no requiere tocar el core.
  Ver [docs/architecture.md](docs/architecture.md) y el
  [ADR 0001](docs/adr/0001-arquitectura-hexagonal.md).

## Prerrequisitos

- Python **3.10 o superior** (probado en 3.14).
- `git`.
- API keys gratuitas, solo para las fuentes que vayas a usar:
  - FRED (series macro): <https://fred.stlouisfed.org/docs/api/api_key.html>.
  - EIA (energía): <https://www.eia.gov/opendata/register.php>.
  - CoinGecko funciona sin clave (plan público/demo, histórico de 365 días como máximo).

## Instalación

```bash
git clone https://github.com/art3mvp/quant-finance-toolkit.git
cd quant-finance-toolkit

python -m venv .venv
# Windows (PowerShell):  .venv\Scripts\Activate.ps1
# Linux / macOS:         source .venv/bin/activate

pip install -e ".[dev]"            # añade ",parquet" para poder guardar en Parquet
cp .env.example .env               # Windows: copy .env.example .env
# edita .env y rellena FRED_API_KEY=...
```

Para comprobar la instalación:

```bash
toolkit --help
pytest
```

## Uso

### Línea de comandos

```bash
# Acciones (Yahoo Finance), guardando un CSV por ticker en data/
toolkit prices AAPL MSFT --start 2020-01-01 --end 2024-12-31 --type equity --out data/

# Índices, frecuencia mensual
toolkit prices ^GSPC ^IBEX ^STOXX50E --type index --interval monthly --start 2015-01-01

# Series macro (FRED): última revisión
toolkit macro CPIAUCSL DGS10 --start 2000-01-01

# Series macro tal como se publicaron el 30/06/2015 (ALFRED)
toolkit macro CPIAUCSL GDP --start 2000-01-01 --as-of 2015-06-30 --out data/ --format parquet

# Macro sin clave: BCE / BIS / Eurostat usan ids SDMX '<flujo>/<clave>'
toolkit macro EXR/D.USD.EUR.SP00.A ICP/M.U2.N.000000.4.ANR --source ecb --start 2020-01-01
toolkit macro WS_CBPOL/M.US WS_EER/M.N.B.ES --source bis --start 2015-01-01
toolkit macro prc_hicp_manr/M.RCH_A.CP00.ES --source eurostat --start 2015-01-01
toolkit macro ESP/NY.GDP.MKTP.CD USA/FP.CPI.TOTL.ZG --source world_bank   # '<ISO3>/<indicador>'
toolkit macro D_1NBAF472 --source banco_espana --start 2010-01-01           # Euríbor 1 año

# Fiscal (Tesoro de EE. UU.): '<endpoint>:<campo>[:<filtro>=<valor>]'
toolkit macro v2/accounting/od/debt_to_penny:tot_pub_debt_out_amt --source us_treasury --start 2020-01-01
toolkit macro "v2/accounting/od/avg_interest_rates:avg_interest_rate_amt:security_desc=Treasury Bills" --source us_treasury

# Misma petición, otra fuente de mercado: la salida es la misma PriceSeries
toolkit prices AAPL MSFT --source twelve_data --start 2024-01-01
toolkit prices IBM --source alpha_vantage --interval weekly

# Criptoactivos (CoinGecko): el ticker es el id de CoinGecko, no el símbolo
toolkit prices bitcoin ethereum --source coingecko --type crypto --start 2026-01-01

# Energía (EIA): WTI y Brent diarios, gas natural Henry Hub mensual
toolkit macro PET.RWTC.D PET.RBRTE.D NG.RNGWHHD.M --source eia --start 2020-01-01
```

Notas sobre las fuentes macro:

- Solo FRED ofrece vintages (`--as-of`). En el resto, pedirlos da un error por serie.
- BCE, BIS y Eurostat comparten una base SDMX-CSV (`adapters/outbound/_sdmx.py`). La
  clave debe fijar todas las dimensiones: si la consulta devuelve varias series, se
  rechaza en lugar de mezclarlas.
- Todas las fechas se normalizan al **inicio** del periodo (`2024-Q1` → `2024-01-01`),
  igual que FRED.

Notas sobre la fuente fiscal:

- `us_treasury` usa el mismo puerto `MacroProvider`: una serie fiscal es una serie
  temporal univariante, como una macro. Se separa en `fiscal/` por tipo de fuente.
- Los endpoints con varias filas por fecha (p. ej. una por tipo de valor) exigen el
  filtro `campo=valor`, que no distingue mayúsculas. Las fechas son el `record_date`
  publicado (p. ej. fin de mes).

Notas sobre las fuentes de mercado:

- Ninguna de las fuentes REST da `adj_close` en su plan gratuito. Para retornos totales
  (con dividendos y splits) usa Yahoo.
- **Alpha Vantage** fecha las barras semanales y mensuales en la última sesión del
  periodo, y Yahoo en la primera. El plan gratuito limita las peticiones por minuto y día.
- **Twelve Data** devuelve como máximo 5000 barras por petición. Los índices pueden no
  traer volumen, que queda a `NaN`.

Notas sobre las fuentes especializadas:

- **CoinGecko** no ofrece OHLC diario en el plan gratuito: `close` y `volume` vienen de
  la API y `open/high/low` quedan a `NaN` (no se inventan velas). Las frecuencias
  semanal, mensual, etc. se agregan en local.
- **EIA** devuelve `MacroSeries` (precios de materias primas sin OHLCV). Su API ignora
  `start`/`end`, así que el adaptador pagina y filtra el rango en local. No tiene vintages
  (`--as-of`).

Ejemplo de salida:

```
Descargadas: 3 OK, 1 fallidas
ticker      fuente        divisa   n_obs  inicio     fin           media_ret    std_ret
AAPL        yahoo         USD       1258  2020-01-02 2024-12-31     0.001182   0.019956
MSFT        yahoo         USD       1258  2020-01-02 2024-12-31     0.000988   0.019211
^GSPC       yahoo         USD       1258  2020-01-02 2024-12-31     0.000561   0.013443
Errores:
  NOTATICKER123: yahoo: sin datos para NOTATICKER123 en el rango solicitado
```

Códigos de salida: `0` si se descarga al menos una serie, `1` si fallan todas y `2` ante
errores de uso o de configuración (p. ej. falta `FRED_API_KEY`). Con `-v` se activa el
logging detallado. `python -m toolkit ...` equivale a `toolkit ...`.

### Desde Python

```python
from datetime import date

from toolkit.bootstrap import build_download_service
from toolkit.domain.models import AssetType, DownloadRequest, Frequency, MacroRequest

service = build_download_service()  # Yahoo + FRED

result = service.download_prices(
    DownloadRequest(
        tickers=["AAPL", "MSFT", "^GSPC"],
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
        interval=Frequency.DAILY,
        asset_type=AssetType.EQUITY,
    )
)
print(result.n_success, result.n_failed, result.errors)

aapl = result.series["AAPL"]
aapl.data.head()                        # open, high, low, close, adj_close, volume
aapl.mean_return, aapl.std_return       # calculados al construir la serie
aapl.returns, aapl.log_returns          # pd.Series

cpi = service.download_macro(
    MacroRequest(series_ids=["CPIAUCSL"], start=date(2000, 1, 1), as_of=date(2015, 6, 30))
).series["CPIAUCSL"]
cpi.vintage, cpi.mean, cpi.std
```

Para desarrollar sin red (por ejemplo, la cartera), los proveedores sintéticos de los tests
(`tests/fakes.py`) se pueden inyectar directamente desde la raíz del repo:

```python
from tests.fakes import FakePriceProvider
from toolkit.services.download_service import DownloadService

service = DownloadService(FakePriceProvider())  # series deterministas, sin red
```

## Tests

```bash
pytest                      # tests unitarios, sin red
pytest --cov=toolkit        # con cobertura
pytest -m network           # tests de integración contra Yahoo/FRED reales
ruff check .                # linter
```

## Estructura del proyecto

```
├── pyproject.toml              # dependencias, entry point `toolkit`, pytest, ruff
├── .env.example                # FRED_API_KEY, EIA_API_KEY, COINGECKO_API_KEY...
├── docs/
│   ├── architecture.md         # capas, regla de dependencias, flujo, diagrama
│   └── adr/0001-arquitectura-hexagonal.md
├── notebooks/                  # demo (fase 3)
├── src/toolkit/
│   ├── domain/                 # CORE: models.py, errors.py, portfolio.py (stub)
│   ├── ports/                  # inbound.py (DownloadData), outbound.py (Price/MacroProvider)
│   ├── services/               # download_service.py (lote paralelo)
│   ├── adapters/
│   │   ├── inbound/cli.py      # argparse
│   │   └── outbound/           # un subpaquete por tipo de fuente
│   │       ├── _http.py        # cliente HTTP común (reintentos, ocultar claves)
│   │       ├── _prices.py      # normalización OHLCV común
│   │       ├── _periods.py     # periodos (2024-Q1, 2024M01...) y frecuencias
│   │       ├── _sdmx.py        # base SDMX-CSV (BCE, BIS, Eurostat)
│   │       ├── market/         # yahoo, alpha_vantage, twelve_data
│   │       ├── macro/          # fred, ecb, eurostat, bis, world_bank, banco_espana
│   │       ├── fiscal/         # us_treasury
│   │       └── specialized/    # coingecko.py, eia.py
│   └── bootstrap.py            # composition root + entry point
└── tests/                      # todo el código de test (src solo contiene producción)
    ├── fakes.py                # proveedores sintéticos que implementan los puertos
    ├── unit/{domain,services,adapters}/
    ├── unit/test_architecture.py
    └── integration/            # @pytest.mark.network
```
