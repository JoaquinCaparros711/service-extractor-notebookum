# Service Extractor NotebookUm

Este microservicio se encarga de **Extraer el texto de los documentos PDF** para el sistema NotebookUm.

## Responsabilidades
- Recibe archivos PDF.
- Utiliza la librería `docling` para leer y estructurar el texto.
- Devuelve el contenido extraído en formato JSON.

## Endpoint implementado

El servicio separa comandos y consultas siguiendo CQRS:

- Comando: crea trabajos de extracción y modifica el estado interno.
- Consultas: leen estado o resultado sin disparar una nueva extracción.

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

### GET `/internal/v1/extractions/{job_id}/audit`

Devuelve auditoría técnica sin exponer el texto extraído ni contenido del PDF.

```json
{
  "job_id": "1f0e5f6a-8a2b-47fd-a902-f4e63017cf95",
  "correlation_id": "corr-123",
  "status": "completed",
  "event_type": "extraction.completed",
  "audit_metadata": {
    "filename": "documento.pdf",
    "content_type": "application/pdf",
    "size_bytes": 12345,
    "bulkhead": "light",
    "pdf_retained": false
  },
  "metrics": {
    "duration_ms": 120.5,
    "size_bytes": 12345,
    "status": "completed",
    "extraction_strategy": "docling"
  },
  "failure": null
}
```

Los errores de validación se devuelven como `application/problem+json`.

Casos rechazados con HTTP 400:

- El campo `file` no está presente.
- El archivo no declara `content-type: application/pdf`.
- El PDF supera el límite configurado de 25MB.
- El archivo declara ser PDF pero el contenido está corrupto o no tiene firma PDF válida.

## Saga

El extractor participa en la saga documental exponiendo eventos de estado en las respuestas de job:

- `extraction.accepted`: el comando fue aceptado.
- `extraction.processing`: el trabajo está en ejecución.
- `extraction.completed`: el orquestador puede continuar con generación de resumen.
- `extraction.failed`: el orquestador debe marcar el documento como fallido o ejecutar compensación.

Para reintentos seguros, el comando acepta `Idempotency-Key` como header o `idempotency_key` como campo de formulario. Repetir el mismo comando con la misma clave devuelve el mismo `job_id` sin duplicar procesamiento.

Las respuestas incluyen `audit_metadata` con `pdf_retained: false`; el servicio no conserva el PDF original después de aceptar el trabajo.

## Circuit Breaker

El motor principal de extracción (`docling`) está protegido con Circuit Breaker:

- Si Docling falla repetidamente, el circuito pasa a `open`.
- Con el circuito abierto, el servicio evita invocar Docling y responde rápido usando el parser básico cuando el PDF lo permite.
- Las extracciones por fallback básico se marcan con `degraded: true`.
- Después de la ventana de recuperación, el circuito permite una prueba en estado `half_open`; si funciona, vuelve a `closed`.

Variables relevantes:

```bash
DOCLING_CIRCUIT_FAILURE_THRESHOLD=3
DOCLING_CIRCUIT_RESET_SECONDS=30
```

## Observabilidad

Cada transición relevante del job emite un log estructurado JSON en el logger `service_extractor.audit`. Los eventos incluyen `correlation_id`, `job_id`, `event_type`, `status`, `size_bytes`, estrategia de extracción, duración cuando aplica y tipo de falla cuando existe.

El endpoint de auditoría permite diagnosticar fallos y revisar métricas sin devolver el contenido textual extraído.

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

## Rate Limit

El ingreso de trabajos se limita por consumidor interno. Por defecto, la identidad del consumidor se lee desde `X-Client-ID`; si no se envía, se usa `anonymous`.

Cuando un consumidor supera su cuota, el servicio responde HTTP 429 con `application/problem+json` e incluye `Retry-After` para indicar cuándo reintentar.

Variables relevantes:

```bash
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_CLIENT_HEADER=X-Client-ID
```

## Strangler Pattern

El microservicio expone un contrato interno para que el monolito pueda validar que la extracción externa está lista antes de redirigir tráfico desde el extractor local.

### GET `/internal/v1/strangler/contract`

Devuelve el contrato operativo que debe consumir el adaptador del monolito:

```json
{
  "service": "service-extractor-notebookum",
  "status": "ready",
  "pattern": "strangler",
  "contract_version": "v1",
  "recommended_client_id": "notebookum-monolith",
  "fallback_owner": "notebookum-monolith",
  "endpoints": {
    "create_extraction": {
      "method": "POST",
      "path": "/internal/v1/extractions",
      "success_status": 202
    },
    "get_status": {
      "method": "GET",
      "path": "/internal/v1/extractions/{job_id}",
      "success_status": 200
    },
    "get_result": {
      "method": "GET",
      "path": "/internal/v1/extractions/{job_id}/result",
      "success_status": 200,
      "pending_status": 202
    }
  }
}
```

Durante la migración, el fallback local y el circuit breaker pertenecen al consumidor (`notebookum-monolith`). Este servicio mantiene estable el contrato de extracción, rate limit, estados de job y errores `application/problem+json`.

Variables relevantes:

```bash
STRANGLER_CONTRACT_VERSION=v1
STRANGLER_MONOLITH_CLIENT_ID=notebookum-monolith
```

## Ejecución con Docker
```bash
docker-compose up -d --build
```
El servicio estará disponible internamente en el puerto `5001`.
