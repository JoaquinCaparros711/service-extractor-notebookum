"""Extraction command routes."""

from __future__ import annotations

from uuid import uuid4

from flask import Blueprint, current_app, request

from app.services.job_service import (
    BulkheadCapacityError,
    BulkheadConfig,
    extraction_jobs,
)
from app.services.rate_limit_service import rate_limiter
from app.utils.errors import problem_details

extraction_commands_bp = Blueprint("extraction_commands", __name__)


@extraction_commands_bp.post("/internal/v1/extractions")
def extract_pdf():
    rate_limit_response = _check_rate_limit()
    if rate_limit_response is not None:
        return rate_limit_response

    uploaded_file = request.files.get("file")
    if uploaded_file is None:
        return problem_details(
            400,
            "Bad Request",
            "A PDF file field named 'file' is required.",
            request.path,
        )

    if uploaded_file.content_type != "application/pdf":
        return problem_details(
            400,
            "Bad Request",
            "Only files with content-type application/pdf are supported.",
            request.path,
        )

    pdf_bytes = uploaded_file.read()
    max_upload_size = current_app.config["MAX_UPLOAD_SIZE"]
    if len(pdf_bytes) > max_upload_size:
        return problem_details(
            400,
            "Bad Request",
            "The PDF exceeds the maximum allowed size of 25MB.",
            request.path,
        )

    if not pdf_bytes.startswith(b"%PDF"):
        return problem_details(
            400,
            "Bad Request",
            "Invalid PDF file: corrupted or unsupported content.",
            request.path,
        )

    document_id = request.form.get("document_id") or str(uuid4())
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or request.form.get("correlation_id")
        or str(uuid4())
    )
    user_id = request.form.get("user_id") or request.headers.get("X-User-ID") or ""

    bulkhead_config = _select_bulkhead(len(pdf_bytes))
    try:
        job = extraction_jobs.create_job(
            pdf_bytes=pdf_bytes,
            document_id=document_id,
            correlation_id=correlation_id,
            filename=uploaded_file.filename or "",
            content_type=uploaded_file.content_type,
            bulkhead_config=bulkhead_config,
            user_id=user_id,
            idempotency_key=(
                request.headers.get("Idempotency-Key")
                or request.form.get("idempotency_key")
            ),
        )
    except BulkheadCapacityError as exc:
        return problem_details(503, "Service Unavailable", str(exc), request.path)

    return job.to_status_response(), 202


def _select_bulkhead(size_bytes):
    if size_bytes >= current_app.config["HEAVY_PDF_THRESHOLD_BYTES"]:
        return BulkheadConfig(
            name="heavy",
            max_workers=current_app.config["HEAVY_BULKHEAD_WORKERS"],
            max_active_jobs=current_app.config["HEAVY_BULKHEAD_CAPACITY"],
        )

    return BulkheadConfig(
        name="light",
        max_workers=current_app.config["LIGHT_BULKHEAD_WORKERS"],
        max_active_jobs=current_app.config["LIGHT_BULKHEAD_CAPACITY"],
    )


def _check_rate_limit():
    client_header = current_app.config["RATE_LIMIT_CLIENT_HEADER"]
    client_id = request.headers.get(client_header, "anonymous")
    decision = rate_limiter.check(
        client_id=client_id,
        limit=current_app.config["RATE_LIMIT_REQUESTS"],
        window_seconds=current_app.config["RATE_LIMIT_WINDOW_SECONDS"],
    )
    if decision.allowed:
        return None

    response = problem_details(
        429,
        "Too Many Requests",
        "Rate limit exceeded for extraction job creation.",
        request.path,
    )
    response.headers["Retry-After"] = str(decision.retry_after)
    return response
