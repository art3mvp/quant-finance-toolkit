"""Documentos regulatorios: el contrato común de las fuentes no numéricas.

Hechos relevantes (CNMV), ficheros de registros (ESMA)... no son series temporales, así
que no se fuerzan en ``PriceSeries``/``MacroSeries``. Todas las fuentes de documentos
devuelven ``RegulatoryDocument``, con independencia de su formato original (RSS, JSON).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from toolkit.domain.errors import InvalidDocumentError, InvalidRequestError


@dataclass(frozen=True)
class DocumentRequest:
    """Petición de listado de documentos regulatorios (validada al crearla).

    Attributes:
        query: Filtro propio de la fuente (emisor en CNMV, tipo de fichero en ESMA...).
            Una cadena vacía equivale a ``None``.
        start: Publicados desde esta fecha (incluida).
        end: Publicados hasta esta fecha (incluida).
        limit: Máximo de documentos a devolver (``>= 1``).

    Raises:
        InvalidRequestError: Si ``limit < 1`` o ``start > end``.
    """

    query: str | None = None
    start: date | None = None
    end: date | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", (self.query or "").strip() or None)
        if self.limit < 1:
            raise InvalidRequestError(f"limit debe ser >= 1 (recibido {self.limit})")
        if self.start is not None and self.end is not None and self.start > self.end:
            raise InvalidRequestError(
                f"start ({self.start}) no puede ser posterior a end ({self.end})"
            )


@dataclass(frozen=True)
class RegulatoryDocument:
    """Documento publicado por un regulador o registro oficial.

    Attributes:
        source: Fuente que lo publica (``"cnmv"``, ``"esma"``...).
        identifier: Id estable en la fuente (número de registro, id del fichero...).
        title: Título legible.
        url: Enlace ``http(s)`` al documento.
        published_at: Fecha y hora de publicación en UTC, tz-naive (como el resto del dominio).
        issuer: Emisor o entidad afectada, si aplica.
        category: Tipo de documento en la fuente (p. ej. ``"DLTINS"``).
        summary: Resumen en texto plano.
    """

    source: str
    identifier: str
    title: str
    url: str
    published_at: datetime
    issuer: str | None = None
    category: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        """Valida los campos obligatorios.

        Raises:
            InvalidDocumentError: Si falta un campo, la URL no es http(s) o la fecha
                no es un ``datetime`` tz-naive.
        """
        for field_name in ("source", "identifier", "title", "url"):
            if not str(getattr(self, field_name) or "").strip():
                raise InvalidDocumentError(f"RegulatoryDocument: {field_name} vacío")
        if not self.url.startswith(("http://", "https://")):
            raise InvalidDocumentError(f"{self.identifier}: URL no http(s): {self.url!r}")
        if not isinstance(self.published_at, datetime) or self.published_at.tzinfo is not None:
            raise InvalidDocumentError(
                f"{self.identifier}: published_at debe ser datetime tz-naive"
            )
