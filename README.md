# Toolkit financiero

Toolkit en Python para **extraer, estandarizar y analizar datos bursátiles y
macroeconómicos** y **gestionar y simular carteras**. Taller B1-T1, Máster de IA
aplicada a mercados financieros.

**Autores:** Artem Pesin ([art3mvp](https://github.com/art3mvp)) y
[JuanPoveda13](https://github.com/JuanPoveda13).

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
- **Cartera** (`Portfolio`): pesos validados, **limpieza y alineación de calendarios**
  (NaNs, festivos, cripto 24/7), métricas anualizadas, Sharpe, drawdown, VaR/CVaR y
  avisos de divisa.
- **Monte Carlo** parametrizable (iteraciones, horizonte, μ, σ, semilla) para la
  cartera o un activo, con gráfico de trayectorias y distribución final (`sim.plot()`).
- **Informes**: `cartera.report()` genera Markdown parametrizable con métricas,
  diagnósticos y advertencias de riesgo; `cartera.plots_report()` dibuja rendimiento
  comparado, evolución, drawdown, correlaciones, pesos y riesgo/retorno.
- **Arquitectura hexagonal**: añadir una fuente nueva no requiere tocar el núcleo
  (ver [Arquitectura](#arquitectura)).
- **Notebook de demostración** con datos reales:
  [notebooks/demo_toolkit.ipynb](notebooks/demo_toolkit.ipynb).

## Prerrequisitos

- Python **3.10 o superior** (probado en 3.14).
- `git`.
- API keys gratuitas, solo para las fuentes que vayas a usar:
  - FRED (series macro): <https://fred.stlouisfed.org/docs/api/api_key.html>.
  - Alpha Vantage (precios): <https://www.alphavantage.co/support/#api-key>.
  - Twelve Data (precios): <https://twelvedata.com/register>.
  - EIA (energía): <https://www.eia.gov/opendata/register.php>.
  - Yahoo Finance, BCE, Eurostat, BIS, Banco Mundial, Banco de España, Tesoro de
    EE. UU., CNMV y ESMA no necesitan clave.
  - CoinGecko funciona sin clave (plan público/demo, histórico de 365 días como máximo).
  - SEC EDGAR no usa clave, pero exige identificarse: en `.env`,
    `SEC_USER_AGENT=Nombre Apellido email@dominio.com` (solo el valor, sin
    `User-Agent:`).

## Instalación

Hay dos formas: instalarlo como librería directamente desde GitHub (para usarlo
en tus propios scripts o notebooks) o clonar el repositorio (para desarrollar,
ejecutar los tests o abrir el notebook de demostración).

### Como librería, sin clonar el repositorio

```bash
pip install "git+https://github.com/art3mvp/quant-finance-toolkit.git@v0.1.0"

# con soporte para guardar en Parquet:
pip install "toolkit-financiero[parquet] @ git+https://github.com/art3mvp/quant-finance-toolkit.git@v0.1.0"

# última versión de la rama main (puede cambiar sin aviso):
pip install "git+https://github.com/art3mvp/quant-finance-toolkit.git"
```

Esto instala el paquete `toolkit` y el comando `toolkit` (`toolkit --help`). Las
API keys se leen de las variables de entorno o de un fichero `.env` en el
directorio desde el que ejecutes tu código; puedes usar como plantilla
[.env.example](.env.example). Para actualizar a una versión nueva, repite el
`pip install` con el tag correspondiente.

En `requirements.txt` o en las dependencias de otro `pyproject.toml`:

```text
toolkit-financiero @ git+https://github.com/art3mvp/quant-finance-toolkit.git@v0.1.0
```

### Clonando el repositorio (desarrollo)

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

Notas por fuente (lo que conviene saber al usarlas):

- **`--as-of`** solo lo admiten FRED (vintages de ALFRED) y SEC EDGAR (solo lo
  **presentado** hasta esa fecha, *point-in-time*). En el resto es una petición inválida
  y se informa como error de cada serie.
- **Ids**: se envían tal como se escriben (solo se quitan espacios y duplicados); cada
  API decide si distingue mayúsculas. En **BCE, BIS y Eurostat** la clave SDMX debe fijar
  todas las dimensiones: si devuelve varias series, se rechaza en lugar de mezclarlas.
- **Fechas**: toda observación semanal o menos frecuente se fecha al **inicio** del
  periodo (`2024-Q1` → `2024-01-01`), sea cual sea la fuente
  ([Convención de fechas](docs/architecture.md#convención-de-fechas)).
- **Yahoo** es la única fuente de mercado con `adj_close` gratis: úsala para retornos
  totales (dividendos y splits).
- **Alpha Vantage** gratuito: 1 petición por segundo, cupo diario y sin histórico diario
  completo (`outputsize=full` es premium). Se pide `compact` (~100 sesiones) cuando el
  rango cabe; si no, la API lo rechaza con un mensaje claro.
- **Twelve Data**: como máximo 5000 barras por petición; los índices pueden venir sin
  volumen (`NaN`).
- **CoinGecko** gratuito: sin OHLC diario, así que `open/high/low` quedan a `NaN` (no se
  inventan velas) y las frecuencias superiores se agregan en local. Con el plan demo, un
  `--start` de hace más de 365 días se rechaza antes de llamar a la API.
- **EIA**: devuelve `MacroSeries`; su API ignora `start`/`end`, así que se pagina y se
  filtra en local. Sin vintages.
- **Tesoro de EE. UU.**: los endpoints con varias filas por fecha exigen el filtro
  `campo=valor` (no distingue mayúsculas).
- **SEC EDGAR**: el índice es la fecha de cierre del periodo. La serie trimestral no
  tiene el 4.º trimestre (la SEC solo publica el anual) y no se deriva.
- **CNMV**: el RSS solo incluye lo publicado desde la sesión anterior.

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
        tickers=["AAPL", "MSFT", "XLE", "IEF", "GLD"],   # acciones y ETFs (tipo equity)
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

build_storage_service("data/", "csv").store(result.series)   # data/AAPL.csv, data/GLD.csv...
```

### Cartera, informes y Monte Carlo

```python
from toolkit.bootstrap import configure_plotting
from toolkit.domain.portfolio import Portfolio

# Renta variable (AAPL, MSFT), energía (XLE), bonos del Tesoro (IEF) y oro (GLD):
# activos poco correlacionados entre sí
cartera = Portfolio(
    series=list(result.series.values()),
    weights={"AAPL": 0.20, "MSFT": 0.20, "XLE": 0.15, "IEF": 0.25, "GLD": 0.20},
    alignment="inner",          # o "ffill" (con ffill_limit=5)
)
cartera.prices, cartera.returns            # precios alineados y sus retornos
cartera.alignment_report.dropped_dates     # fechas descartadas al alinear calendarios
cartera.warnings                           # p. ej. divisas mezcladas
cartera.mean_return, cartera.volatility    # por periodo, sin anualizar

# Monte Carlo: cartera completa o un activo (desde su último precio)
sim = cartera.monte_carlo(n_steps=252, n_simulations=2000, seed=42)   # μ y σ estimados
sim = cartera.monte_carlo(n_steps=252, n_simulations=2000, mu=0.0003, sigma=0.012)
sim_aapl = cartera.monte_carlo_asset("AAPL", n_steps=126, n_simulations=1000)
sim.quantile(0.05), sim.var(0.95), sim.cvar(0.95), sim.prob_loss   # CVaR: pérdida media en la cola

# Informe Markdown parametrizable
texto = cartera.report(
    risk_free=0.03,                 # anual, para el Sharpe
    confidence=0.99,                # VaR/CVaR
    sections=["resumen", "metricas", "advertencias"],   # por defecto, todas
    simulation=sim,                 # añade la sección de Monte Carlo
)
# En Jupyter: from IPython.display import Markdown; Markdown(texto)

# Gráficos: se registra el renderer una vez (o se pasa en cada llamada)
configure_plotting()                # matplotlib
fig = cartera.plots_report()        # Figure: se muestra en Jupyter; en un script, fig.savefig(...)
sim.plot()
```

Secciones de `report()`: `resumen`, `metricas`, `pesos`, `activos`, `correlaciones`,
`diagnostico`, `simulacion` y `advertencias`. Los umbrales de las advertencias
(concentración, muestra corta, correlación y volatilidad altas, fechas descartadas) se
cambian con `thresholds=RiskThresholds(...)` (`toolkit.domain.report`).

La anualización usa 252 sesiones al año (365 si todos los activos son cripto), 52
semanas o 12 meses según la frecuencia; se puede forzar con `periods_per_year=`.

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

[`notebooks/demo_toolkit.ipynb`](notebooks/demo_toolkit.ipynb) recorre todas las
capacidades del toolkit con **datos reales**, cada una en una sección. Se guarda
ejecutado, así que se puede leer en GitHub con sus tablas, gráficos e informes sin
instalar nada.

| § | Qué enseña | Claves en `.env` |
|---|---|---|
| 2 | Acciones e índices (S&P 500, IBEX 35, Euro Stoxx 50) en lote; un ticker inválido no aborta el lote | — |
| 3 | La misma `PriceSeries` desde Twelve Data, Alpha Vantage (semanal) y CoinGecko (cripto) | `TWELVE_DATA_API_KEY`, `ALPHA_VANTAGE_API_KEY` |
| 4 | Datos adicionales: BCE, Eurostat, BIS, Banco de España, Banco Mundial, Tesoro de EE. UU., Brent (EIA) y fundamentales (SEC EDGAR) | `EIA_API_KEY`, `SEC_USER_AGENT` |
| 5 | FRED: dato actual frente a vintage (*look-ahead bias*) | `FRED_API_KEY` |
| 6 | Documentos regulatorios (CNMV, ESMA) | — |
| 7 | Validación de peticiones, series y cartera (errores y avisos) | — |
| 8 | Limpieza y alineación de calendarios (AAPL + IBEX + BTC): método ingenuo frente a alineado, `inner` frente a `ffill` | — |
| 9 | Cartera: métricas y `plots_report()` | — |
| 10 | Monte Carlo: escenario estimado, de estrés (μ y σ propios) y de un solo activo | — |
| 11 | `report()` completo en Markdown, con umbrales de riesgo propios | — |
| 12 | Guardado de series e informe, y la misma descarga desde la CLI | — |

Las celdas que necesitan una clave que no está en `.env` se saltan con un aviso; el
resto funciona sin ninguna.

```bash
pip install -e ".[dev]" jupyter    # matplotlib ya es dependencia del toolkit
jupyter lab notebooks/demo_toolkit.ipynb
# o ábrelo en VS Code y elige como kernel el Python del .venv
```

## Limpieza de datos y validación de inputs

### Limpieza y alineación de calendarios

`Portfolio` alinea los precios en un calendario común **antes** de calcular retornos
(cripto 24/7, festivos distintos en cada bolsa):

- `alignment="inner"` (por defecto): solo las fechas comunes.
- `alignment="ffill"`: la unión, rellenando hacia delante como mucho `ffill_limit`
  periodos. Cada relleno es un retorno 0 artificial que **reduce** la volatilidad y la
  correlación medidas.
- Los `NaN`/`inf` se descartan y se cuentan; un precio `<= 0` es un error. Todo queda en
  `cartera.alignment_report` y en la sección `diagnostico` de `report()`.

Por qué se alinean precios y no retornos, y el detalle de cada método:
[Limpieza y alineación](docs/architecture.md#limpieza-y-alineación).

### ¿Admitir cualquier serie temporal de precios? Estricto en el núcleo, flexible en los adaptadores

El toolkit **no** acepta "cualquier cosa que contenga una serie de precios". El núcleo
solo trabaja con `PriceSeries` y `MacroSeries`, que validan un **esquema cerrado** al
crearse:

- índice `DatetimeIndex` ordenado, sin duplicados y sin zona horaria;
- columnas conocidas (`open, high, low, close, [adj_close], volume`), todas numéricas;
- al menos una observación.

Las peticiones (`DownloadRequest`...) y la cartera (pesos numéricos, finitos, no
negativos y que suman 1, misma frecuencia) también se validan al construirse.

Por qué se decidió así:

1. **La ambigüedad se paga en cada métrica.** Con un input libre, cada cálculo tendría
   que adivinar: ¿`close` o `adj_close`? ¿Fechas con zona horaria? ¿Fin o inicio de
   periodo? ¿Hay duplicados? ¿Qué divisa? Un error de ese tipo no falla: da un Sharpe o
   un VaR **silenciosamente incorrecto**, que es lo peor en finanzas.
2. **Fallar pronto y cerca de la causa.** Una serie mal formada se rechaza al crearla,
   con un mensaje que dice qué columna o índice está mal, no a mitad de un Monte Carlo.
3. **Un único contrato para 15 fuentes.** La flexibilidad está donde de verdad varían los
   formatos: los adaptadores. Cada uno traduce su API al esquema común, y todo lo que
   viene después (cartera, informes, gráficos) confía en su entrada.
4. **No bloquea a nadie.** Para analizar un CSV propio basta con construir una
   `PriceSeries` con el esquema documentado (o escribir un adaptador).

Lo que **no** se rechaza a propósito, porque son datos válidos pero con riesgo:

- **Huecos y `NaN`**: se limpian al alinear y se informa de ellos.
- **Divisas mezcladas o desconocidas**: se avisa en `cartera.warnings` y en el informe,
  porque comparar mercados en moneda local es un análisis legítimo y convertir exigiría
  una serie de tipo de cambio. Con `strict_currency=True` pasa a ser un error.

En resumen: los datos **mal formados** son un error, y los datos **válidos pero
arriesgados** generan un aviso.

## Arquitectura

Arquitectura **hexagonal**: un núcleo (`domain/`, `ports/`, `services/`) que no sabe de
dónde vienen los datos ni adónde van, y adaptadores (`adapters/`) que traducen cada
fuente al mismo formato. `bootstrap.py` es el único módulo que conoce las clases
concretas. Las dependencias solo apuntan hacia el núcleo, y
`tests/unit/test_architecture.py` lo comprueba en cada `pytest`.

[docs/architecture.md](docs/architecture.md) contiene el diagrama de arquitectura, los
**diagramas UML de clases**, qué hay en cada capa, la regla de dependencias, el flujo de
una petición, el criterio de errores y cómo extender el sistema.

```
├── pyproject.toml          # dependencias, entry point `toolkit`, pytest, ruff
├── .env.example            # claves de API
├── docs/architecture.md    # diseño y diagramas
├── notebooks/              # demo_toolkit.ipynb
├── src/toolkit/
│   ├── domain/             # modelos, cartera, limpieza, métricas, Monte Carlo, informe
│   ├── ports/              # contratos inbound (casos de uso) y outbound (fuentes, guardado, gráficos)
│   ├── services/           # descarga en lote, documentos, guardado
│   ├── adapters/           # inbound/cli.py y outbound/ (fuentes por tipo, storage, plotting)
│   └── bootstrap.py        # composition root + entry point
└── tests/                  # unit/, integration/, resources/ (respuestas grabadas), fakes.py
```

## Tests

```bash
pytest                      # unitarios + integración (≈ 3 s, sin red)
pytest tests/integration    # solo integración
pytest --cov=toolkit        # con cobertura
ruff check .                # linter
```

**Ningún test sale a la red** (`tests/conftest.py` lo bloquea). Los unitarios usan fakes
(`tests/fakes.py`) o HTTP simulado; los de integración ejecutan todo `src` contra
**respuestas reales grabadas** de las 15 fuentes (`tests/resources/`), un caso correcto
y otro de error por fuente. Detalle en
[Cómo se prueba cada capa](docs/architecture.md#cómo-se-prueba-cada-capa).
