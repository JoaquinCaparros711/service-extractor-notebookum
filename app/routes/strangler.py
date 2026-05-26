"""Strangler migration contract routes."""

from __future__ import annotations

from flask import Blueprint, current_app

strangler_bp = Blueprint("strangler", __name__)


@strangler_bp.get("/internal/v1/strangler/contract")
def get_strangler_contract():
    """Expose the extractor contract expected by the monolith migration adapter."""
    return {
        "service": "service-extractor-notebookum",
        "status": "ready",
        "pattern": "strangler",
        "contract_version": current_app.config["STRANGLER_CONTRACT_VERSION"],
        "recommended_client_id": current_app.config["STRANGLER_MONOLITH_CLIENT_ID"],
        "fallback_owner": "notebookum-monolith",
        "endpoints": {
            "create_extraction": {
                "method": "POST",
                "path": "/internal/v1/extractions",
                "success_status": 202,
            },
            "get_status": {
                "method": "GET",
                "path": "/internal/v1/extractions/{job_id}",
                "success_status": 200,
            },
            "get_result": {
                "method": "GET",
                "path": "/internal/v1/extractions/{job_id}/result",
                "success_status": 200,
                "pending_status": 202,
            },
        },
        "required_headers": [
            "X-Correlation-ID",
            current_app.config["RATE_LIMIT_CLIENT_HEADER"],
        ],
        "job_statuses": ["accepted", "processing", "completed", "failed"],
        "error_content_type": "application/problem+json",
        "limits": {
            "max_upload_size": current_app.config["MAX_UPLOAD_SIZE"],
            "rate_limit_requests": current_app.config["RATE_LIMIT_REQUESTS"],
            "rate_limit_window_seconds": current_app.config["RATE_LIMIT_WINDOW_SECONDS"],
            "heavy_pdf_threshold_bytes": current_app.config["HEAVY_PDF_THRESHOLD_BYTES"],
        },
    }, 200
