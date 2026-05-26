"""In-memory extraction job processing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Dict, Optional
from uuid import uuid4

from app.services.pdf_service import PDFExtractionService


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
    result: Optional[dict] = None
    error: Optional[str] = None
    status_query_count: int = 0
    result_query_count: int = 0

    def to_status_response(self) -> dict:
        response = {
            "job_id": self.job_id,
            "document_id": self.document_id,
            "correlation_id": self.correlation_id,
            "status": self.status,
            "bulkhead": self.bulkhead,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.error:
            response["error"] = self.error
        return response

    def to_result_response(self) -> Optional[dict]:
        if self.result is None:
            return None
        return dict(self.result)


class ExtractionJobStore:
    """Small in-memory job store for the first async extractor iteration."""

    def __init__(self):
        self._jobs: Dict[str, ExtractionJob] = {}
        self._lock = Lock()
        self._executors: Dict[str, ThreadPoolExecutor] = {}
        self._active_jobs: Dict[str, int] = {}

    def create_job(
        self,
        pdf_bytes: bytes,
        document_id: str,
        correlation_id: str,
        filename: str,
        content_type: str,
        bulkhead_config: BulkheadConfig,
    ) -> ExtractionJob:
        now = self._now()
        with self._lock:
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
            )
            self._jobs[job.job_id] = job
            self._active_jobs[bulkhead_config.name] = active_jobs + 1

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

    def _process_job(self, job_id: str, pdf_bytes: bytes) -> None:
        self._update_job(job_id, status="processing")
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
                "text": extraction.text,
                "metadata": {
                    "filename": job.filename,
                    "content_type": job.content_type,
                    "size_bytes": job.size_bytes,
                    "bulkhead": job.bulkhead,
                    "extraction_strategy": extraction.strategy,
                },
                "metrics": {
                    "duration_ms": duration_ms,
                    "text_length": extraction.text_length,
                },
            }
            self._update_job(job_id, status="completed", result=result, error=None)
        except ValueError as exc:
            self._update_job(job_id, status="failed", error=str(exc))
        finally:
            self._release_bulkhead(job_id)

    def _update_job(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.updated_at = self._now()
            if result is not None:
                job.result = result
            if error is not None:
                job.error = error

    def _release_bulkhead(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return

            active_jobs = self._active_jobs.get(job.bulkhead, 0)
            self._active_jobs[job.bulkhead] = max(0, active_jobs - 1)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()


extraction_jobs = ExtractionJobStore()
