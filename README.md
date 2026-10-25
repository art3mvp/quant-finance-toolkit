# quant-finance-toolkit

Toolkit en Python para extraccion financiera, analisis bursatil y gestion de carteras.

## Instalacion en Windows (PowerShell)

Requisitos: Python **3.14** y Git. Desde la raiz del repositorio:

```bash
py -3.14 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m quant_finance_toolkit
```

## Dependencias

#TODO

## Estructura

```text
src/quant_finance_toolkit/
    providers/       # APIs y descarga en lote
    models/          # Dataclasses de series y cartera
    preprocessing/   # Validacion, nulos y calendarios
    analytics/       # Retornos, estadisticos y riesgo
    simulation/      # Monte Carlo
    reports/         # Markdown y visualizaciones
config/              # Plantilla de credenciales
data/raw/            # Datos originales, ignorados por Git
data/processed/      # Datos preparados, ignorados por Git
docs/                # Arquitectura y decisiones
examples/            # Futuros ejemplos reproducibles
reports/             # Salidas generadas, ignoradas por Git
tests/               # Futuras pruebas
```

Ver [arquitectura y siguientes pasos](docs/architecture.md).
`python -m quant_finance_toolkit` comprueba la instalacion sin descargar datos.

## Credenciales

```bash
cp config/.env.example config/.env
```

La plantilla incluye las claves de FRED, EIA, Twelve Data, Alpha Vantage, Finnhub,
CoinGecko, Nasdaq Data Link y SIX Market Signal, ademas del User-Agent de SEC EDGAR.
Completar solo las fuentes que se utilicen y cargar con `load_dotenv("config/.env")`.
Los 18 adaptadores cargan las variables de `config/.env` sin sobrescribir el entorno.
Las credenciales se validan al utilizar cada fuente. `config/.env` queda excluido de Git.
El directorio `.env/` preexistente se conserva; el entorno del proyecto es `.venv/`.

## Fuentes de datos

Las 18 fuentes previstas se organizan por uso principal: macroeconomia, finanzas
publicas, emisores y registros regulatorios, mercados, energia/cripto y catalogos
de datasets. Ver el [catalogo de fuentes](docs/data-sources.md) para consultar la
cobertura, los requisitos de acceso y la estructura prevista de adaptadores.

## Comprobaciones

```powershell
python -m pip check
python -m ruff check .
```

Ejecutar las pruebas sin red ni credenciales con `python -m pytest`.

## Descarga y comprobacion de APIs

Desde la raiz del proyecto, con el entorno activado:

```powershell
python -m quant_finance_toolkit.providers.check
python -m quant_finance_toolkit.providers.check --provider fred --provider ecb
```

El comando descarga una muestra real por proveedor y comprueba que contiene
registros validos. Guarda originales en `data/raw/<grupo>/<proveedor>/`, datos
normalizados en `data/processed/<dominio>/<proveedor>/` y el informe en
`reports/provider-check.json`. Las claves se eliminan tambien de respuestas que
las devuelven como eco. Cada ejecucion conserva sus extracciones con nombres unicos.

Opciones: `--env-file`, `--data-dir`, `--report`, `--timeout` (25 segundos por lectura)
y `--attempts` (3 intentos). Devuelve codigo 1 si alguna fuente falla, esta vacia o
carece de configuracion; continua comprobando las restantes.

Ver [muestras y resultado de verificacion](docs/provider-check.md).
