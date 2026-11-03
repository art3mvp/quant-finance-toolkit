# Toolkit financiero

Toolkit en Python para **extraer, estandarizar y analizar datos bursátiles y
macroeconómicos** y, en próximas fases, **gestionar carteras**. Taller B1-T1, Máster de IA
aplicada a mercados financieros.

- Descarga **multifuente**: Yahoo Finance (acciones e índices) y FRED/ALFRED
  (series macro, con vintages para evitar el *look-ahead bias*).
- **Formato estándar** para todas las fuentes (`PriceSeries`, `MacroSeries`) con
  estadísticos calculados automáticamente.
- Descarga **en lote y en paralelo**: un fallo individual no tumba el lote.
- **Arquitectura hexagonal**: añadir una fuente nueva no requiere tocar el core.
  Ver [docs/architecture.md](docs/architecture.md) y el
  [ADR 0001](docs/adr/0001-arquitectura-hexagonal.md).

## Prerrequisitos

- Python **3.10 o superior** (probado en 3.14).
- `git`.
- Una API key gratuita de FRED (solo para series macro):
  <https://fred.stlouisfed.org/docs/api/api_key.html>.

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

```

Ejemplo de salida:

```
Descargadas: 3 OK, 1 fallidas
ticker      fuente  divisa   n_obs  inicio     fin           media_ret    std_ret
AAPL        yahoo   USD       1258  2020-01-02 2024-12-31     0.001182   0.019956
MSFT        yahoo   USD       1258  2020-01-02 2024-12-31     0.000988   0.019211
^GSPC       yahoo   USD       1258  2020-01-02 2024-12-31     0.000561   0.013443
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
├── .env.example                # FRED_API_KEY=
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
│   │       ├── market/         # yahoo.py
│   │       └── macro/          # fred.py
│   └── bootstrap.py            # composition root + entry point
└── tests/                      # todo el código de test (src solo contiene producción)
    ├── fakes.py                # proveedores sintéticos que implementan los puertos
    ├── unit/{domain,services,adapters}/
    ├── unit/test_architecture.py
    └── integration/            # @pytest.mark.network
```
