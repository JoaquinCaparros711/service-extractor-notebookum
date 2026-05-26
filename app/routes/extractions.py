"""Extraction command routes."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from flask import Blueprint, current_app, request

from app.services.pdf_service import PDFExtractionService
from app.utils.errors import problem_details

extractions_bp = Blueprint("extractions", __name__)


@extractions_bp.post("/internal/v1/extractions")
def extract_pdf():
    started_at = perf_counter()
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

    document_id = request.form.get("document_id") or str(uuid4())
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or request.form.get("correlation_id")
        or str(uuid4())
    )

    try:
        result = PDFExtractionService().extract_text(pdf_bytes)
    except ValueError as exc:
        return problem_details(400, "Bad Request", str(exc), request.path)

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    return {
        "document_id": document_id,
        "correlation_id": correlation_id,
        "status": "completed",
        "text": result.text,
        "metadata": {
            "filename": uploaded_file.filename,
            "content_type": uploaded_file.content_type,
            "size_bytes": len(pdf_bytes),
            "extraction_strategy": result.strategy,
        },
        "metrics": {
            "duration_ms": duration_ms,
            "text_length": result.text_length,
        },
    }, 200
