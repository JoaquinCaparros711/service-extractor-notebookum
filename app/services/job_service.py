"""In-memory extraction job processing."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Dict, Optional
from uuid import uuid4

from app.services.audit_service import emit_audit_event
from app.services.pdf_service import PDFExtractionService

logger = logging.getLogger(__name__)


class BulkheadCapacityError(RuntimeError):
    """Raised when a bulkhead partition has no available capacity."""


@dataclass(frozen=True)
class BulkheadConfig:
    """Runtime limits for a bulkhead partition."""

    name: str
    max_workers: int
    max_active_jobs: int


@dataclass
class ExtractionJob:
    """State for an asynchronous extraction job."""

    job_id: str
    document_id: str
    correlation_id: str
    status: str
    filename: str
    content_type: str
    size_bytes: int
    bulkhead: str
    created_at: str
    updated_at: str
    user_id: str = ""
    idempotency_key: Optional[str] = None
    event_type: str = "extraction.accepted"
    result: Optional[dict] = None
    error: Optional[str] = None
    completed_at: Optional[str] = None
    failure_type: Optional[str] = None
    duration_ms: Optional[float] = None
    extraction_strategy: Optional[str] = None
    degraded: bool = False
    circuit_breaker_state: Optional[str] = None
    status_query_count: int = 0
    result_query_count: int = 0

    def to_status_response(self) -> dict:
        response = {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "event_type": self.event_type,
            "bulkhead": self.bulkhead,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "audit_metadata": self.audit_metadata(),
        }
        if self.idempotency_key:
            response["idempotency_key"] = self.idempotency_key
        if self.error:
            response["error"] = self.error
        return response

    def to_result_response(self) -> Optional[dict]:
        if self.result is None:
            return None
        return {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "status": self.status,
            "text": self.result.get("text", ""),
            "text_length": self.result.get("metrics", {}).get("text_length", 0),
            "strategy": self.result.get("metadata", {}).get("extraction_strategy", ""),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    def audit_metadata(self) -> dict:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "bulkhead": self.bulkhead,
            "pdf_retained": False,
        }

    def to_audit_response(self) -> dict:
        response = {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "event_type": self.event_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "audit_metadata": self.audit_metadata(),
            "metrics": {
                "duration_ms": self.duration_ms,
                "size_bytes": self.size_bytes,
                "status": self.status,
                "extraction_strategy": self.extraction_strategy,
                "degraded": self.degraded,
                "circuit_breaker_state": self.circuit_breaker_state,
            },
            "failure": None,
        }
        if self.error:
            response["failure"] = {
                "type": self.failure_type or "extraction_error",
                "message": self.error,
            }
        return response


class ExtractionJobStore:
    """Small in-memory job store for the first async extractor iteration."""

    def __init__(self):
        self._jobs: Dict[str, ExtractionJob] = {}
        self._lock = Lock()
        self._executors: Dict[str, ThreadPoolExecutor] = {}
        self._active_jobs: Dict[str, int] = {}
        self._idempotency_index: Dict[str, str] = {}

    def create_job(
        self,
        pdf_bytes: bytes,
        document_id: str,
        correlation_id: str,
        filename: str,
        content_type: str,
        bulkhead_config: BulkheadConfig,
        user_id: str = "",
        idempotency_key: Optional[str] = None,
    ) -> ExtractionJob:
        now = self._now()
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency_index:
                existing_job_id = self._idempotency_index[idempotency_key]
                return self._jobs[existing_job_id]

            active_jobs = self._active_jobs.get(bulkhead_config.name, 0)
            if active_jobs >= bulkhead_config.max_active_jobs:
                raise BulkheadCapacityError(
                    f"The {bulkhead_config.name} extraction bulkhead is saturated."
                )

            executor = self._executors.get(bulkhead_config.name)
            if executor is None:
                executor = ThreadPoolExecutor(max_workers=bulkhead_config.max_workers)
                self._executors[bulkhead_config.name] = executor

            job = ExtractionJob(
                job_id=str(uuid4()),
                document_id=document_id,
                correlation_id=correlation_id,
                status="accepted",
                filename=filename,
                content_type=content_type,
                size_bytes=len(pdf_bytes),
                bulkhead=bulkhead_config.name,
                created_at=now,
                updated_at=now,
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            self._jobs[job.job_id] = job
            if idempotency_key:
                self._idempotency_index[idempotency_key] = job.job_id
            self._active_jobs[bulkhead_config.name] = active_jobs + 1

        self._emit_job_event(job, "extraction.accepted")
        executor.submit(self._process_job, job.job_id, pdf_bytes)
        return job

    def get_job(self, job_id: str) -> Optional[ExtractionJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_status_snapshot(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status_query_count += 1
            return job.to_status_response()

    def get_result_snapshot(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.result_query_count += 1
            if job.status == "completed":
                return job.to_result_response()
            return job.to_status_response()

    def get_audit_snapshot(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.to_audit_response()

    def _process_job(self, job_id: str, pdf_bytes: bytes) -> None:
        self._update_job(job_id, status="processing", event_type="extraction.processing")
        started_at = perf_counter()

        try:
            job = self.get_job(job_id)
            if job is None:
                return

            extraction = PDFExtractionService().extract_text(pdf_bytes)
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            result = {
                "job_id": job.job_id,
                "document_id": job.document_id,
                "correlation_id": job.correlation_id,
                "status": "completed",
                "event_type": "extraction.completed",
                "text": extraction.text,
                "metadata": {
                    "filename": job.filename,
                    "content_type": job.content_type,
                    "size_bytes": job.size_bytes,
                    "bulkhead": job.bulkhead,
                    "extraction_strategy": extraction.strategy,
                    "degraded": extraction.degraded,
                    "circuit_breaker_state": extraction.circuit_state,
                    "pdf_retained": False,
                },
                "metrics": {
                    "duration_ms": duration_ms,
                    "text_length": extraction.text_length,
                },
            }
            self._update_job(
                job_id,
                status="completed",
                event_type="extraction.completed",
                result=result,
                error=None,
                duration_ms=duration_ms,
                extraction_strategy=extraction.strategy,
                degraded=extraction.degraded,
                circuit_breaker_state=extraction.circuit_state,
            )
            self._save_to_redis(job.document_id, job, extraction.text)
        except ValueError as exc:
            self._update_job(
                job_id,
                status="failed",
                event_type="extraction.failed",
                error=str(exc),
                failure_type=exc.__class__.__name__,
            )
        finally:
            self._release_bulkhead(job_id)

    def _update_job(
        self,
        job_id: str,
        status: str,
        event_type: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        failure_type: Optional[str] = None,
        duration_ms: Optional[float] = None,
        extraction_strategy: Optional[str] = None,
        degraded: Optional[bool] = None,
        circuit_breaker_state: Optional[str] = None,
    ) -> None:
        event_job = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.event_type = event_type
            job.updated_at = self._now()
            if status in {"completed", "failed"}:
                job.completed_at = job.updated_at
            if result is not None:
                job.result = result
            if error is None:
                job.error = None
            if error is not None:
                job.error = error
            if failure_type is not None:
                job.failure_type = failure_type
            if duration_ms is not None:
                job.duration_ms = duration_ms
            if extraction_strategy is not None:
                job.extraction_strategy = extraction_strategy
            if degraded is not None:
                job.degraded = degraded
            if circuit_breaker_state is not None:
                job.circuit_breaker_state = circuit_breaker_state
            event_job = job

        self._emit_job_event(event_job, event_type)

    def _release_bulkhead(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return

            active_jobs = self._active_jobs.get(job.bulkhead, 0)
            self._active_jobs[job.bulkhead] = max(0, active_jobs - 1)

    def _save_to_redis(self, document_id: str, job: "ExtractionJob", text: str) -> None:
        try:
            import redis as redis_lib
            r = redis_lib.Redis(
                host=os.environ.get("REDIS_HOST", "redis"),
                port=int(os.environ.get("REDIS_PORT", 6379)),
                password=os.environ.get("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
            ttl = int(os.environ.get("EXTRACTION_TTL", 3600))
            payload = json.dumps({
                "document_id": document_id,
                "text": text,
                "filename": job.filename,
                "content_type": job.content_type,
                "job_id": job.job_id,
                "user_id": job.user_id,
            })
            r.setex(f"extraction:{document_id}", ttl, payload)
            logger.info("Extraction saved to Redis: extraction:%s", document_id)
        except Exception as exc:
            logger.warning("Failed to save extraction to Redis: %s", exc)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _emit_job_event(self, job: ExtractionJob, event_type: str) -> None:
        emit_audit_event(
            {
                "event_type": event_type,
                "job_id": job.job_id,
                "document_id": job.document_id,
                "correlation_id": job.correlation_id,
                "status": job.status,
                "size_bytes": job.size_bytes,
                "duration_ms": job.duration_ms,
                "extraction_strategy": job.extraction_strategy,
                "degraded": job.degraded,
                "circuit_breaker_state": job.circuit_breaker_state,
                "failure_type": job.failure_type,
                "pdf_retained": False,
            }
        )


extraction_jobs = ExtractionJobStore()
