"""Adaptadores de salida (fuentes, persistencia y gráficos), agrupados por tipo.

* ``market/``: precios de acciones e índices (Yahoo, Alpha Vantage, Twelve Data).
* ``macro/``: series macroeconómicas (FRED, BCE, Eurostat, BIS, Banco Mundial, BdE).
* ``fiscal/``: datos fiscales (U.S. Treasury Fiscal Data).
* ``regulatory/``: fundamentales (SEC EDGAR) y documentos regulatorios (CNMV, ESMA).
* ``specialized/``: activos y materias primas específicos (CoinGecko, EIA).
* ``storage/``: persistencia de series en ficheros (CSV, Parquet).
* ``plotting/``: visualización de carteras y simulaciones (matplotlib).

Los módulos ``_*.py`` son infraestructura común (HTTP, periodos, OHLCV, SDMX), no
adaptadores. Un adaptador nunca importa otro.
"""
