"""Jerarquía de errores del toolkit.

Todos los errores que cruzan las fronteras del hexágono derivan de ``ToolkitError``,
de modo que los adaptadores inbound (CLI, notebooks) solo necesitan capturar esta base
y nunca excepciones específicas de librerías de terceros (``yfinance``, ``requests``...).
"""

from __future__ import annotations


class ToolkitError(Exception):
    """Error base de todo el toolkit."""


class InvalidSeriesError(ToolkitError):
    """La serie no cumple el esquema estándar (índice, columnas, tipos...)."""


class InvalidDocumentError(ToolkitError):
    """El documento regulatorio no cumple el contrato (campos vacíos, URL, fecha...)."""


class ProviderError(ToolkitError):
    """Fallo genérico de un proveedor de datos (red, formato inesperado, límites...)."""


class SeriesNotFoundError(ProviderError):
    """El proveedor no tiene datos para el identificador o rango solicitados."""


class ConfigurationError(ToolkitError):
    """Configuración ausente o inválida (p. ej. falta una API key)."""


class InvalidRequestError(ToolkitError, ValueError):
    """La petición de descarga es inválida (lista vacía, ``start > end``...)."""
