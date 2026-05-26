"""Extraction query routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.services.job_service import extraction_jobs
from app.utils.errors import problem_details

extraction_queries_bp = Blueprint("extraction_queries", __name__)


@extraction_queries_bp.get("/internal/v1/extractions/<job_id>")
def get_extraction_status(job_id):
    status = extraction_jobs.get_status_snapshot(job_id)
    if status is None:
        return problem_details(
            404,
            "Not Found",
            "Extraction job was not found.",
            request.path,
        )

    return status, 200


@extraction_queries_bp.get("/internal/v1/extractions/<job_id>/result")
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

    result = extraction_jobs.get_result_snapshot(job_id)
    if job.status != "completed":
        return result, 202

    return result, 200


@extraction_queries_bp.get("/internal/v1/extractions/<job_id>/audit")
def get_extraction_audit(job_id):
    audit = extraction_jobs.get_audit_snapshot(job_id)
    if audit is None:
        return problem_details(
            404,
            "Not Found",
            "Extraction job was not found.",
            request.path,
        )

    return audit, 200
