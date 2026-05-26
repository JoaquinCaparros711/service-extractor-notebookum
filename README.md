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

### Historia de Usuario 10 - Observar y Auditar Extracciones (Prioridad: P3)

**Descripción**: Como equipo de soporte, necesitamos trazabilidad completa de cada extracción para diagnosticar errores, medir tiempos y correlacionar solicitudes entre el monolito/API gateway y el microservicio extractor.

**Criterio principal**: Todas las extracciones deben emitir registros estructurados, métricas y eventos que permitan reconstruir el flujo del trabajo sin exponer contenido del PDF.

Escenarios de aceptación:

- **Correlación**: Si una solicitud incluye `X-Correlation-ID` o `correlation_id` en el payload, todos los logs, eventos y respuestas relacionadas con ese job deben incluir ese mismo valor.
- **Métricas al finalizar**: Al completar o fallar una extracción se debe registrar `duration_ms`, `size_bytes`, `status`, `extraction_strategy` y `failure_type` (cuando aplique).
- **Auditoría técnica**: El endpoint `/internal/v1/extractions/{job_id}/audit` debe devolver metadatos técnicos y métricas sin incluir `text` ni contenido binario del PDF.

Pruebas y validación:

- Test de integración: enviar un POST con `X-Correlation-ID` y verificar que la respuesta inicial contiene `correlation_id`, luego consultar `/extractions/{job_id}/audit` y comprobar que todos los eventos contienen el mismo `correlation_id`.
- Test de logs estructurados: capturar logs del logger `service_extractor.audit` y validar esquema JSON (ver más abajo).
- Test de rendimiento: crear 100 trabajos concurrentes y verificar que las métricas de latencia y el endpoint `/health` siguen respondiendo.

Esquema recomendado de log estructurado (ejemplo):

```json
{
  "timestamp": "2026-05-26T12:00:00Z",
  "logger": "service_extractor.audit",
  "correlation_id": "corr-123",
  "job_id": "1f0e5f6a-8a2b-47fd-a902-f4e63017cf95",
  "event_type": "extraction.accepted",
  "status": "accepted",
  "document_id": "doc-123",
  "size_bytes": 12345,
  "extraction_strategy": "docling",
  "bulkhead": "light",
  "duration_ms": null,
  "failure_type": null
}
```

Métricas (Prometheus):

- `extractor_jobs_total{status="completed|failed|accepted|processing"}`
- `extractor_job_duration_seconds` (histogram) — latencias de extracción
- `extractor_jobs_in_flight` — trabajos en ejecución por bulkhead
- `extractor_circuit_open` (gauge) — estado del circuit breaker

Trazabilidad distribuida:

- Aceptar `X-Correlation-ID` y `traceparent` (W3C Trace Context) y propagar ambos a logs y eventos.
- Incluir `correlation_id` en headers de respuesta para que el monolito/orquestador pueda correlacionar fácilmente.

Retención y privacidad:

- Los logs y la API de auditoría NUNCA deben contener el texto extraído ni el PDF en bruto.
- Auditoría guarda metadatos mínimos (filename, size_bytes, strategy, status) y un ttl configurable; por defecto 30 días.

Alertas operativas recomendadas:

- Alerta si `extractor_jobs_in_flight` supera un umbral por más de 2 minutos.
- Alerta si la tasa de `failed` sobrepasa 5% en un intervalo de 5 minutos.
- Alerta si `extractor_circuit_open` permanece en `1` por más de 30s.

Endpoints relevantes (resumen):

- `POST /internal/v1/extractions` — crea job (aceptación rápida, incluye `correlation_id` en respuesta).
- `GET /internal/v1/extractions/{job_id}/audit` — devuelve auditoría técnica (sin texto).

Responsables de implementación:

- `app/services/audit_service.py` — generar y centralizar eventos de auditoría.
- `app/routes/extractions.py` — propagar `correlation_id` y exponer `audit` endpoint.
- `tests/test_extraction_api.py` — añadir pruebas de integración para logs y audit endpoint.


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
