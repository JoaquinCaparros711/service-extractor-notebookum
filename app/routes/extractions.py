"""Extraction command and query routes."""

from __future__ import annotations

from uuid import uuid4

from flask import Blueprint, current_app, request

from app.services.job_service import (
    BulkheadCapacityError,
    BulkheadConfig,
    extraction_jobs,
)
from app.utils.errors import problem_details

extractions_bp = Blueprint("extractions", __name__)


@extractions_bp.post("/internal/v1/extractions")
def extract_pdf():
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

    bulkhead_config = _select_bulkhead(len(pdf_bytes))
    try:
        job = extraction_jobs.create_job(
            pdf_bytes=pdf_bytes,
            document_id=document_id,
            correlation_id=correlation_id,
            filename=uploaded_file.filename or "",
            content_type=uploaded_file.content_type,
            bulkhead_config=bulkhead_config,
        )
    except BulkheadCapacityError as exc:
        return problem_details(503, "Service Unavailable", str(exc), request.path)

    return job.to_status_response(), 202


@extractions_bp.get("/internal/v1/extractions/<job_id>")
def get_extraction_status(job_id):
    job = extraction_jobs.get_job(job_id)
    if job is None:
        return problem_details(
            404,
            "Not Found",
            "Extraction job was not found.",
            request.path,
        )

    return job.to_status_response(), 200


@extractions_bp.get("/internal/v1/extractions/<job_id>/result")
def get_extraction_result(job_id):
    job = extraction_jobs.get_job(job_id)
    if job is None:
        return problem_details(
            404,
            "Not Found",
            "Extraction job was not found.",
            request.path,
        )

    if job.status == "failed":
        return problem_details(
            400,
            "Bad Request",
            job.error or "Extraction failed.",
            request.path,
        )

    if job.status != "completed":
        return job.to_status_response(), 202

    return job.result, 200


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
