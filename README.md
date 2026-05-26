# Service Extractor NotebookUm

Este microservicio se encarga de **Extraer el texto de los documentos PDF** para el sistema NotebookUm.

## Responsabilidades
- Recibe archivos PDF.
- Utiliza la librería `docling` para leer y estructurar el texto.
- Devuelve el contenido extraído en formato JSON.

## Endpoint implementado

### POST `/internal/v1/extractions`

Acepta un trabajo asíncrono de extracción para un PDF válido menor o igual a 25MB.

```bash
curl -X POST http://localhost:5001/internal/v1/extractions \
  -H "X-Correlation-ID: corr-123" \
  -F "document_id=doc-123" \
  -F "file=@documento.pdf;type=application/pdf"
```

Respuesta exitosa:

```json
{
  "job_id": "1f0e5f6a-8a2b-47fd-a902-f4e63017cf95",
  "document_id": "doc-123",
  "correlation_id": "corr-123",
  "status": "accepted",
  "bulkhead": "light",
  "created_at": "2026-05-26T12:00:00+00:00",
  "updated_at": "2026-05-26T12:00:00+00:00"
}
```

### GET `/internal/v1/extractions/{job_id}`

Consulta el estado del trabajo. Los estados posibles son `accepted`, `processing`, `completed` y `failed`.

### GET `/internal/v1/extractions/{job_id}/result`

Devuelve el resultado cuando el trabajo está `completed`. Si todavía está pendiente, devuelve HTTP 202 con el estado actual.

```json
{
  "job_id": "1f0e5f6a-8a2b-47fd-a902-f4e63017cf95",
  "document_id": "doc-123",
  "correlation_id": "corr-123",
  "status": "completed",
  "text": "...",
  "metadata": {
    "filename": "documento.pdf",
    "content_type": "application/pdf",
    "size_bytes": 12345,
    "bulkhead": "light",
    "extraction_strategy": "docling"
  },
  "metrics": {
    "duration_ms": 120.5,
    "text_length": 4321
  }
}
```

Los errores de validación se devuelven como `application/problem+json`.

Casos rechazados con HTTP 400:

- El campo `file` no está presente.
- El archivo no declara `content-type: application/pdf`.
- El PDF supera el límite configurado de 25MB.
- El archivo declara ser PDF pero el contenido está corrupto o no tiene firma PDF válida.

## Bulkhead

El servicio separa trabajos de extracción en dos particiones:

- `light`: PDFs menores al umbral `HEAVY_PDF_THRESHOLD_BYTES`.
- `heavy`: PDFs mayores o iguales al umbral `HEAVY_PDF_THRESHOLD_BYTES`.

Cada partición tiene workers y capacidad independiente. Si una partición se satura, el servicio devuelve HTTP 503 con `application/problem+json` sin bloquear `/health` ni la otra partición.

Variables relevantes:

```bash
HEAVY_PDF_THRESHOLD_BYTES=5242880
LIGHT_BULKHEAD_WORKERS=2
HEAVY_BULKHEAD_WORKERS=2
LIGHT_BULKHEAD_CAPACITY=20
HEAVY_BULKHEAD_CAPACITY=5
```

## Ejecución con Docker
```bash
docker-compose up -d --build
```
El servicio estará disponible internamente en el puerto `5001`.
