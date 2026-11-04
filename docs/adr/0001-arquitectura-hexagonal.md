# ADR 0001: Arquitectura hexagonal (puertos y adaptadores)

- **Estado**: aceptada
- **Ámbito**: todo el paquete `toolkit`

## Contexto

El enunciado exige que la capa de ingesta esté **desacoplada** del análisis, el modelado
y la simulación. Añadir una fuente nueva no debe tocar el núcleo, y la salida del
extractor debe ser idéntica con independencia de la API.

Las fuentes que integramos difieren en casi todo:

- **Transporte**: librería (`yfinance`), REST JSON, CSV SDMX y RSS.
- **Autenticación**: sin clave, clave en la URL, clave en cabecera o `User-Agent` obligatorio.
- **Errores**: HTTP 200 con el error en el cuerpo, 400 ambiguos y 412.
- **Fechas**: última sesión, fin de mes o inicio de periodo.
- **Mayúsculas**: unas rutas las distinguen y otras no.

Si esas diferencias llegan al análisis, cada script nuevo tendría que conocerlas.

## Decisión

Se adopta una arquitectura hexagonal, al estilo de *Architecture Patterns with Python*
(Percival & Gregory):

- **Dominio** (`domain/`): dataclasses inmutables que se validan en `__post_init__`.
  - Series: `PriceSeries` y `MacroSeries`, que calculan media y desviación al crearse.
  - Documentos: `RegulatoryDocument`.
  - Peticiones: `DownloadRequest`, `MacroRequest` y `DocumentRequest`.
  - Además, los errores y la cartera.

  Es el contrato común: todo lo que sale de un adaptador cumple estos esquemas y la
  convención de fechas, que es el inicio del periodo.
- **Puertos** (`ports/`): `Protocol`s comprobables con `isinstance`.
  - Inbound: `DownloadData` y `ListDocuments`.
  - Outbound: `PriceProvider`, `MacroProvider` y `DocumentProvider`.
- **Servicios** (`services/`): implementan los casos de uso.
  - Descarga en lote paralela y tolerante a fallos.
  - Listado de documentos con orden y límite garantizados.

  Dependen solo de los puertos.
- **Adaptadores** (`adapters/`):
  - Inbound: la CLI.
  - Outbound: uno por fuente, agrupados por tipo (`market/`, `macro/`, `fiscal/`,
    `regulatory/`, `specialized/`).

  Lo que comparten (HTTP, periodos, OHLCV, SDMX) vive en módulos privados `_*.py`.
  Un adaptador nunca importa otro.
- **Composition root** (`bootstrap.py`): el único módulo que conoce las clases
  concretas.
  - Lee `.env`.
  - Registra las fuentes por nombre.
  - Inyecta proveedores en los servicios y las fábricas en la CLI.

La regla de dependencias (siempre hacia dentro) la verifica `tests/unit/test_architecture.py`
analizando los imports con `ast`.

## Alternativas consideradas

1. **Scripts por fuente que devuelven `DataFrame`s.** Es lo más rápido al principio, pero
   cada fuente impone su formato (columnas, zonas horarias, fechas) al análisis. Es
   justo la fragilidad que el enunciado pide evitar.
2. **Una clase base abstracta (`ABC`) por tipo de fuente con herencia.** Ofrece
   desacoplamiento parecido, pero acopla los adaptadores a una jerarquía. Los tests
   tendrían que heredar de ella, y los fakes ya no podrían ser objetos sueltos. Los
   `Protocol` dan el mismo contrato con tipado estructural.
3. **Capas clásicas (datos → negocio → presentación).** No impide que el negocio dependa
   de detalles de la capa de datos, como los tipos de `requests` o `yfinance`. En la
   hexagonal es la infraestructura la que depende del núcleo.

## Consecuencias

**Ventajas:**

- **Fuentes nuevas sin tocar el núcleo:** añadir una fuente de un tipo existente es un
  módulo más una línea en `bootstrap`. Así se integraron 15 fuentes sin cambiar el
  dominio.
- **Tipos de dato nuevos como extensiones:** un tipo de dato nuevo, como los documentos,
  se añade con nuevos modelos, puertos y servicio, sin modificar los existentes.
- **Tests sin red:** el núcleo se prueba con fakes, y cada adaptador con HTTP simulado
  (`responses`).
- **Contrato uniforme:** la cartera, Monte Carlo y los reportes reciben siempre los
  mismos objetos, validados y alineados en fechas.

**Costes:**

- **Más módulos e indirección** que un script.
- **Disciplina explícita:** el test de arquitectura recuerda las reglas, pero no
  sustituye a la revisión.
- **Decisiones transversales centralizadas:** el criterio de errores, la convención de
  fechas y el tratamiento de mayúsculas se documentan en `docs/architecture.md` y deben
  respetarlos todos los adaptadores.
