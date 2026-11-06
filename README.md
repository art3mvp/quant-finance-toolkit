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
  | regulatory | SEC EDGAR | fundamentales XBRL *point-in-time* | `sec_edgar` | `SEC_USER_AGENT` |
  | regulatory | CNMV | hechos relevantes del día (documentos) | `docs --source cnmv` | no |
  | regulatory | ESMA | ficheros FIRDS publicados (documentos) | `docs --source esma` | no |
  | specialized | CoinGecko | criptoactivos (cierre + volumen) | `coingecko` | opcional |
  | specialized | EIA | energía: WTI, Brent, gas Henry Hub... | `eia` | `EIA_API_KEY` |
- **Formato estándar** para todas las fuentes (`PriceSeries`, `MacroSeries`,
  `RegulatoryDocument`) con estadísticos calculados automáticamente y una misma
  convención de fechas (inicio del periodo), para que las series de fuentes distintas
  se alineen.
- Descarga **en lote y en paralelo**: un fallo individual no tumba el lote.
- **Arquitectura hexagonal**: añadir una fuente nueva no requiere tocar el núcleo
  (resumen en [Cómo está organizado](#cómo-está-organizado); detalle en
  [docs/architecture.md](docs/architecture.md)).
- **Notebook de demostración** con datos reales:
  [notebooks/demo_toolkit.ipynb](notebooks/demo_toolkit.ipynb).

## Prerrequisitos

- Python **3.10 o superior** (probado en 3.14).
- `git`.
- API keys gratuitas, solo para las fuentes que vayas a usar:
  - FRED (series macro): <https://fred.stlouisfed.org/docs/api/api_key.html>.
  - EIA (energía): <https://www.eia.gov/opendata/register.php>.
  - CoinGecko funciona sin clave (plan público/demo, histórico de 365 días como máximo).
  - SEC EDGAR no usa clave, pero exige identificarse: en `.env`,
    `SEC_USER_AGENT=Nombre Apellido email@dominio.com` (solo el valor, sin
    `User-Agent:`).

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

# Fundamentales (SEC EDGAR): '<ticker|CIK>/[<taxonomía>/]<concepto>[:FY]'
toolkit macro AAPL/us-gaap/Assets MSFT/NetIncomeLoss --source sec_edgar --start 2018-01-01
toolkit macro AAPL/Revenues:FY --source sec_edgar --as-of 2020-06-30   # solo lo presentado a esa fecha

# Documentos regulatorios
toolkit docs --source cnmv --query indra          # hechos relevantes de hoy de un emisor
toolkit docs --source esma --query DLTINS --start 2026-11-01 --limit 5

# Misma petición, otra fuente de mercado: la salida es la misma PriceSeries
toolkit prices AAPL MSFT --source twelve_data --start 2024-01-01
toolkit prices IBM --source alpha_vantage --interval weekly

# Criptoactivos (CoinGecko): el ticker es el id de CoinGecko, no el símbolo
toolkit prices bitcoin ethereum --source coingecko --type crypto --start 2026-01-01

# Energía (EIA): WTI y Brent diarios, gas natural Henry Hub mensual
toolkit macro PET.RWTC.D PET.RBRTE.D NG.RNGWHHD.M --source eia --start 2020-01-01
```

Notas sobre las fuentes macro:

- Solo FRED y SEC EDGAR admiten `--as-of`. En el resto, pedirlo es una petición
  inválida y se informa como error de cada serie.
- Los ids se envían tal como se escriben (solo se quitan espacios y duplicados): cada
  adaptador decide si su API distingue mayúsculas. `exr/d.usd.eur.sp00.a` y
  `EXR/D.USD.EUR.SP00.A` piden la misma serie al BCE.
- BCE, BIS y Eurostat comparten una base SDMX-CSV (`adapters/outbound/_sdmx.py`). La
  clave debe fijar todas las dimensiones: si la consulta devuelve varias series, se
  rechaza en lugar de mezclarlas.
- Todas las fechas se normalizan al **inicio** del periodo (`2024-Q1` → `2024-01-01`),
  igual que FRED.

Notas sobre las fuentes regulatorias:

- **SEC EDGAR** devuelve `MacroSeries` (una serie univariante por concepto), así que
  hereda la descarga en lote y la CLI. Con `--as-of` solo usa los datos **presentados**
  hasta esa fecha: es la versión *point-in-time* de los fundamentales, como ALFRED para la
  macro. El índice es la fecha de cierre del periodo. La serie trimestral no tiene el
  4.º trimestre porque la SEC solo publica el dato anual, y no se deriva.
- **CNMV** y **ESMA** publican documentos, no series. Por eso tienen su propio modelo
  (`RegulatoryDocument`), sus puertos (`DocumentProvider` y el caso de uso
  `ListDocuments`) y su servicio, en lugar de forzarlos en `PriceSeries`/`MacroSeries`.
  El RSS de la CNMV solo incluye lo publicado desde la sesión anterior.

Notas sobre la fuente fiscal:

- `us_treasury` usa el mismo puerto `MacroProvider`: una serie fiscal es una serie
  temporal univariante, como una macro. Se separa en `fiscal/` por tipo de fuente.
- Los endpoints con varias filas por fecha (p. ej. una por tipo de valor) exigen el
  filtro `campo=valor`, que no distingue mayúsculas. El `record_date` publicado (fin
  de mes en las series mensuales) se refecha al inicio del periodo, como el resto.

Notas sobre las fuentes de mercado:

- Ninguna de las fuentes REST da `adj_close` en su plan gratuito. Para retornos totales
  (con dividendos y splits) usa Yahoo.
- Las barras semanales y mensuales se fechan al **inicio** del periodo en todas las
  fuentes (Alpha Vantage las publica en la última sesión y se refechan).
- **Alpha Vantage** gratuito: 1 petición por segundo y cupo diario, y el histórico
  diario completo (`outputsize=full`) es premium. El adaptador pide `compact` (~100
  sesiones) cuando el rango cabe; si no, la API lo rechaza con un mensaje claro.
- **Twelve Data** devuelve como máximo 5000 barras por petición. Los índices pueden no
  traer volumen, que queda a `NaN`.

Notas sobre las fuentes especializadas:

- **CoinGecko** no ofrece OHLC diario en el plan gratuito: `close` y `volume` vienen de
  la API y `open/high/low` quedan a `NaN` (no se inventan velas). Las frecuencias
  semanal, mensual, etc. se agregan en local. Con el plan demo, un `--start` de hace
  más de 365 días se rechaza antes de llamar a la API.
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

Códigos de salida: `0` si se obtiene al menos una serie o documento, `1` si fallan
todas (o falla la fuente de documentos) y `2` ante errores de uso o de configuración
(p. ej. falta `FRED_API_KEY` o `--workers 0`). Con `-v` se activa el
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

# Solo macro (no construye ninguna fuente de precios) y documentos regulatorios
ecb = build_download_service(None, "ecb")

from toolkit.bootstrap import build_document_service
from toolkit.domain.documents import DocumentRequest

docs = build_document_service("esma").list_documents(DocumentRequest("DLTINS", limit=5))

# Guardar lo descargado (CSV o Parquet): devuelve la ruta de cada fichero
from toolkit.bootstrap import build_storage_service

build_storage_service("data/", "csv").store(result.series)   # data/AAPL.csv, data/_GSPC.csv...
```

Para análisis de cartera y Monte Carlo:

```python
from toolkit.domain.portfolio import Portfolio

cartera = Portfolio(
    series=[result.series["AAPL"], result.series["MSFT"]],
    weights={"AAPL": 0.6, "MSFT": 0.4},
)
cartera.mean_return, cartera.volatility          # por periodo, sin anualizar
sim = cartera.monte_carlo(n_steps=252, n_simulations=1000, seed=42)
sim.quantile(0.05), sim.prob_loss                # percentil 5 del valor final y P(pérdida)
```

Las peticiones se validan al crearlas: `DownloadRequest(tickers=[])` o un
`start > end` lanzan `InvalidRequestError` antes de cualquier descarga.

Para desarrollar sin red (por ejemplo, la cartera), los proveedores sintéticos de los tests
(`tests/fakes.py`) se pueden inyectar directamente desde la raíz del repo:

```python
from tests.fakes import FakePriceProvider
from toolkit.services.download_service import DownloadService

service = DownloadService(FakePriceProvider())  # series deterministas, sin red
```

### Notebook de demostración

`notebooks/demo_toolkit.ipynb` recorre el toolkit con **datos reales**: precios de
Yahoo (con un ticker inválido para ver la tolerancia a fallos), series del BCE y del
Banco Mundial, FRED con y sin vintage, documentos de CNMV y ESMA, una cartera con
Monte Carlo y el guardado en ficheros. Las celdas que necesitan una clave que no está
en `.env` se saltan con un aviso.

```bash
pip install -e ".[dev]" jupyter    # matplotlib viene en [dev]
jupyter lab notebooks/demo_toolkit.ipynb
```

## Cómo está organizado

El código sigue una **arquitectura hexagonal**: un núcleo que no sabe de dónde vienen
los datos ni adónde van, rodeado de adaptadores que traducen cada fuente al mismo
formato.

| Capa | Carpeta | En una frase |
|------|---------|--------------|
| Dominio | `domain/` | Los objetos con los que trabaja todo el mundo (`PriceSeries`, `MacroSeries`, `Portfolio`...), validados al crearse. Sin red, ficheros ni gráficos. |
| Puertos | `ports/` | Los contratos: qué ofrece el núcleo (`DownloadData`, `ListDocuments`, `StoreSeries`) y qué necesita (`PriceProvider`, `MacroProvider`, `DocumentProvider`, `SeriesRepository`). |
| Servicios | `services/` | Los casos de uso: descarga en lote en paralelo, listado de documentos y guardado. Solo hablan con puertos. |
| Adaptadores | `adapters/` | La traducción con el exterior: la CLI (entrada) y las 15 fuentes y el guardado en ficheros (salida). |
| Composition root | `bootstrap.py` | El único sitio que conoce las clases concretas: lee `.env` y lo conecta todo. |

Las dependencias solo apuntan hacia dentro (adaptadores → puertos → dominio) y un
test (`tests/unit/test_architecture.py`) lo comprueba en cada ejecución de `pytest`.
Qué hay en cada capa, la regla completa, el criterio de errores y la convención de
fechas están en [docs/architecture.md](docs/architecture.md).

## Tests

```bash
pytest                      # unitarios + integración (≈ 3 s, sin red)
pytest tests/integration    # solo integración
pytest --cov=toolkit        # con cobertura
ruff check .                # linter
```

**Ningún test sale a la red.** `tests/conftest.py` bloquea cualquier conexión: si a un
test le falta un mock, falla con un mensaje claro en lugar de llamar a la API real.

| Tipo | Carpeta | Qué es real | Qué se simula |
|------|---------|-------------|---------------|
| Unitarios | `tests/unit/` | una pieza (un modelo, un servicio, un adaptador) | lo demás: fakes (`tests/fakes.py`) o HTTP mínimo escrito a mano |
| Integración | `tests/integration/` | todo `src`: `bootstrap`, CLI, servicios, adaptadores, `HttpClient`, `Portfolio`, ficheros | solo las APIs, con **respuestas reales grabadas** (`tests/resources/`) |

Los tests de integración cubren las 15 fuentes. Para cada una comprueban una respuesta
correcta y otra de error, ambas tal como las devolvió la API: un 404, un 400 con XML,
un HTTP 200 con el error en el cuerpo, el límite de peticiones de Alpha Vantage... Los
valores esperados se leen del cuerpo grabado, no del adaptador. El mock es estricto:
si un adaptador cambia la URL o un parámetro, el test falla, igual que fallaría contra
la API real.

Las credenciales aparecen en las grabaciones como `<NOMBRE_DE_LA_VARIABLE>` y las
respuestas muy grandes están recortadas sin cambiar su estructura. Un test comprueba que
ninguna grabación contiene una clave y que todas están en uso.

## Estructura del proyecto

```
├── pyproject.toml              # dependencias, entry point `toolkit`, pytest, ruff
├── .env.example                # FRED_API_KEY, EIA_API_KEY, COINGECKO_API_KEY...
├── docs/
│   └── architecture.md         # capas, regla de dependencias, flujo, diagrama
├── notebooks/
│   └── demo_toolkit.ipynb      # recorrido con datos reales
├── src/toolkit/
│   ├── domain/                 # núcleo: models.py, documents.py, errors.py, portfolio.py, simulation.py
│   ├── ports/                  # inbound.py (casos de uso), outbound.py (fuentes y SeriesRepository)
│   ├── services/               # download_service.py, document_service.py, storage_service.py
│   ├── adapters/
│   │   ├── inbound/cli.py      # argparse
│   │   └── outbound/           # un subpaquete por tipo de fuente
│   │       ├── _http.py        # cliente HTTP común (reintentos, ocultar claves)
│   │       ├── _prices.py      # normalización OHLCV común
│   │       ├── _periods.py     # periodos, frecuencias, clip y refechado al inicio
│   │       ├── _sdmx.py        # base SDMX-CSV (BCE, BIS, Eurostat)
│   │       ├── market/         # yahoo, alpha_vantage, twelve_data
│   │       ├── macro/          # fred, ecb, eurostat, bis, world_bank, banco_espana
│   │       ├── fiscal/         # us_treasury
│   │       ├── regulatory/     # sec_edgar (series), cnmv y esma (documentos)
│   │       ├── specialized/    # coingecko.py, eia.py
│   │       └── storage/        # files.py: CSV / Parquet
│   └── bootstrap.py            # composition root + entry point
└── tests/                      # todo el código de test (src solo contiene producción)
    ├── fakes.py                # proveedores sintéticos que implementan los puertos
    ├── unit/{domain,services,adapters}/
    ├── unit/test_architecture.py
    ├── integration/            # todo src real, APIs con respuestas grabadas
    ├── resources/<fuente>/     # respuestas reales grabadas (sin credenciales)
    └── conftest.py             # bloquea la red en todos los tests
```
