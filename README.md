# quant-finance-toolkit

Toolkit en Python para extraccion financiera, analisis bursatil y gestion de carteras.

## Instalacion en Windows (PowerShell)

Requisitos: Python **3.14** y Git. Desde la raiz del repositorio:

```bash
py -3.14 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements-dev.txt
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

```powershell
Copy-Item config/.env.example config/.env
```

La plantilla incluye las claves de FRED, EIA, Twelve Data, Alpha Vantage, Finnhub,
CoinGecko, Nasdaq Data Link y SIX Market Signal, ademas del User-Agent de SEC EDGAR.
Completar solo las fuentes que se utilicen y cargar con `load_dotenv("config/.env")`.
Los adaptadores de descarga aun no estan implementados. `config/.env` queda excluido de Git.
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

Cuando se incorporen pruebas, ejecutarlas con `python -m pytest`.
