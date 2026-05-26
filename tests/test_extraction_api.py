import io
import json
import logging
from time import sleep

from app.services.job_service import extraction_jobs


def assert_problem_details(response, expected_detail, expected_status=400):
    assert response.status_code == expected_status
    assert response.content_type == "application/problem+json"
    data = response.get_json()
    assert data["type"] == "about:blank"
    assert data["status"] == expected_status
    assert expected_detail in data["detail"].lower()
    assert data["instance"] == "/internal/v1/extractions"


def wait_for_completed_job(client, job_id, attempts=20):
    last_status = None
    for _ in range(attempts):
        response = client.get(f"/internal/v1/extractions/{job_id}")
        assert response.status_code == 200
        data = response.get_json()
        last_status = data["status"]
        assert last_status in {"accepted", "processing", "completed", "failed"}
        if last_status in {"completed", "failed"}:
            return data
        sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish. Last status: {last_status}")


def make_pdf_bytes(text="NotebookUm extractor listo"):
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] "
        b"/Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 64 >>\nstream\nBT /F1 12 Tf 20 100 Td ("
        + escaped.encode("latin-1")
        + b") Tj ET\nendstream\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )


def make_pdf_without_extractable_text():
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF"
    )


def test_extract_valid_pdf_accepts_async_job_with_correlation_id(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "document_id": "doc-123",
            "file": (io.BytesIO(make_pdf_bytes()), "sample.pdf", "application/pdf"),
        },
        headers={"X-Correlation-ID": "corr-123"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    data = response.get_json()
    assert data["job_id"]
    assert data["document_id"] == "doc-123"
    assert data["correlation_id"] == "corr-123"
    assert data["status"] == "accepted"
    assert data["event_type"] == "extraction.accepted"
    assert data["bulkhead"] == "light"
    assert data["audit_metadata"]["pdf_retained"] is False

    status = wait_for_completed_job(client, data["job_id"])
    assert status["status"] == "completed"
    assert status["event_type"] == "extraction.completed"

    result_response = client.get(f"/internal/v1/extractions/{data['job_id']}/result")
    assert result_response.status_code == 200
    result = result_response.get_json()
    assert result["job_id"] == data["job_id"]
    assert result["document_id"] == "doc-123"
    assert result["correlation_id"] == "corr-123"
    assert result["status"] == "completed"
    assert result["event_type"] == "extraction.completed"
    assert "NotebookUm extractor listo" in result["text"]
    assert result["metadata"]["filename"] == "sample.pdf"
    assert result["metadata"]["bulkhead"] == "light"
    assert result["metadata"]["pdf_retained"] is False
    assert result["metrics"]["duration_ms"] >= 0
    assert result["metrics"]["text_length"] == len(result["text"])


def test_extract_valid_pdf_generates_ids_when_missing(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("texto")),
                "sample.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    data = response.get_json()
    assert data["job_id"]
    assert data["document_id"]
    assert data["correlation_id"]
    assert data["status"] == "accepted"


def test_extract_status_returns_accepted_processing_completed_or_failed(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("estado asincrono")),
                "sample.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    job_id = response.get_json()["job_id"]

    status_response = client.get(f"/internal/v1/extractions/{job_id}")

    assert status_response.status_code == 200
    data = status_response.get_json()
    assert data["job_id"] == job_id
    assert data["status"] in {"accepted", "processing", "completed", "failed"}


def test_extract_result_does_not_require_resending_pdf(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("resultado sin reenviar")),
                "sample.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)

    result_response = client.get(f"/internal/v1/extractions/{job_id}/result")

    assert result_response.status_code == 200
    assert "resultado sin reenviar" in result_response.get_json()["text"]


def test_status_query_does_not_mutate_job_state(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("consulta no muta estado")),
                "sample.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)
    job_before = extraction_jobs.get_job(job_id)
    updated_at_before = job_before.updated_at
    query_count_before = job_before.status_query_count

    status_response = client.get(f"/internal/v1/extractions/{job_id}")

    job_after = extraction_jobs.get_job(job_id)
    assert status_response.status_code == 200
    assert job_after.status == "completed"
    assert job_after.updated_at == updated_at_before
    assert job_after.status_query_count == query_count_before + 1


def test_completed_result_query_is_idempotent(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("resultado idempotente")),
                "sample.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)
    job_before = extraction_jobs.get_job(job_id)
    updated_at_before = job_before.updated_at
    result_query_count_before = job_before.result_query_count

    first_response = client.get(f"/internal/v1/extractions/{job_id}/result")
    second_response = client.get(f"/internal/v1/extractions/{job_id}/result")

    job_after = extraction_jobs.get_job(job_id)
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.get_json() == second_response.get_json()
    assert job_after.updated_at == updated_at_before
    assert job_after.result_query_count == result_query_count_before + 2


def test_saga_completed_event_allows_orchestrator_to_continue(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("saga completada")),
                "saga.pdf",
                "application/pdf",
            )
        },
        headers={"Idempotency-Key": "saga-completed-key"},
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]

    status = wait_for_completed_job(client, job_id)
    result_response = client.get(f"/internal/v1/extractions/{job_id}/result")

    assert status["event_type"] == "extraction.completed"
    assert result_response.status_code == 200
    assert result_response.get_json()["event_type"] == "extraction.completed"


def test_saga_failed_event_exposes_compensation_metadata(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_without_extractable_text()),
                "without-text.pdf",
                "application/pdf",
            )
        },
        headers={"Idempotency-Key": "saga-failed-key"},
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]

    status = wait_for_completed_job(client, job_id)
    result_response = client.get(f"/internal/v1/extractions/{job_id}/result")

    assert status["status"] == "failed"
    assert status["event_type"] == "extraction.failed"
    assert status["audit_metadata"]["filename"] == "without-text.pdf"
    assert status["audit_metadata"]["pdf_retained"] is False
    assert "no extractable text" in status["error"].lower()
    assert result_response.status_code == 400
    assert result_response.content_type == "application/problem+json"


def test_idempotency_key_returns_same_job_without_duplicate_processing(client):
    headers = {"Idempotency-Key": "same-saga-command"}
    payload = {
        "file": (
            io.BytesIO(make_pdf_bytes("comando idempotente")),
            "idempotent.pdf",
            "application/pdf",
        )
    }
    first_response = client.post(
        "/internal/v1/extractions",
        data=payload,
        headers=headers,
        content_type="multipart/form-data",
    )
    second_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("contenido ignorado por idempotencia")),
                "idempotent-retry.pdf",
                "application/pdf",
            )
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    first = first_response.get_json()
    second = second_response.get_json()
    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first["job_id"] == second["job_id"]
    assert first["idempotency_key"] == "same-saga-command"
    assert second["idempotency_key"] == "same-saga-command"


def test_extract_rejects_non_pdf_with_problem_details(client):
    response = client.post(
        "/internal/v1/extractions",
        data={"file": (io.BytesIO(b"hola"), "sample.txt", "text/plain")},
        content_type="multipart/form-data",
    )

    assert_problem_details(response, "pdf")


def test_extract_rejects_file_over_max_upload_size_with_problem_details(app, client):
    app.config["MAX_UPLOAD_SIZE"] = 8

    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("archivo demasiado grande")),
                "large.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert_problem_details(response, "25mb")


def test_extract_rejects_corrupted_pdf_with_problem_details(client):
    response = client.post(
        "/internal/v1/extractions",
        data={"file": (io.BytesIO(b"not-a-real-pdf"), "broken.pdf", "application/pdf")},
        content_type="multipart/form-data",
    )

    assert_problem_details(response, "invalid pdf")


def test_heavy_bulkhead_saturation_rejects_heavy_job_with_problem_details(app, client):
    app.config["HEAVY_PDF_THRESHOLD_BYTES"] = 1
    app.config["HEAVY_BULKHEAD_CAPACITY"] = 0

    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("heavy")),
                "heavy.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert_problem_details(response, "bulkhead is saturated", expected_status=503)


def test_saturated_heavy_bulkhead_does_not_block_light_jobs(app, client):
    app.config["HEAVY_PDF_THRESHOLD_BYTES"] = 10_000
    app.config["HEAVY_BULKHEAD_CAPACITY"] = 0

    heavy_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("heavy") + b"x" * 20_000),
                "heavy.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert_problem_details(heavy_response, "bulkhead is saturated", expected_status=503)

    light_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("light")),
                "light.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )

    assert light_response.status_code == 202
    assert light_response.get_json()["bulkhead"] == "light"


def test_health_check_does_not_depend_on_saturated_extraction_bulkhead(app, client):
    app.config["LIGHT_BULKHEAD_CAPACITY"] = 0

    rejected_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("health")),
                "health.pdf",
                "application/pdf",
            )
        },
        content_type="multipart/form-data",
    )
    health_response = client.get("/health")

    assert_problem_details(rejected_response, "bulkhead is saturated", expected_status=503)
    assert health_response.status_code == 200
    assert health_response.get_json()["status"] == "ok"


def test_rate_limit_rejects_same_client_after_quota(app, client):
    app.config["RATE_LIMIT_REQUESTS"] = 1
    app.config["RATE_LIMIT_WINDOW_SECONDS"] = 60
    headers = {"X-Client-ID": "rate-limited-client"}

    first_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("primer intento")),
                "first.pdf",
                "application/pdf",
            )
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    second_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("segundo intento")),
                "second.pdf",
                "application/pdf",
            )
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert first_response.status_code == 202
    assert_problem_details(second_response, "rate limit", expected_status=429)
    assert int(second_response.headers["Retry-After"]) > 0


def test_rate_limit_allows_different_client_within_own_quota(app, client):
    app.config["RATE_LIMIT_REQUESTS"] = 1
    app.config["RATE_LIMIT_WINDOW_SECONDS"] = 60

    first_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("cliente a")),
                "a.pdf",
                "application/pdf",
            )
        },
        headers={"X-Client-ID": "client-a"},
        content_type="multipart/form-data",
    )
    second_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("cliente b")),
                "b.pdf",
                "application/pdf",
            )
        },
        headers={"X-Client-ID": "client-b"},
        content_type="multipart/form-data",
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202


def test_rate_limit_uses_configured_client_header(app, client):
    app.config["RATE_LIMIT_REQUESTS"] = 1
    app.config["RATE_LIMIT_WINDOW_SECONDS"] = 60
    app.config["RATE_LIMIT_CLIENT_HEADER"] = "X-Service-Client"
    headers = {"X-Service-Client": "custom-client"}

    first_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("custom uno")),
                "one.pdf",
                "application/pdf",
            )
        },
        headers=headers,
        content_type="multipart/form-data",
    )
    second_response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("custom dos")),
                "two.pdf",
                "application/pdf",
            )
        },
        headers=headers,
        content_type="multipart/form-data",
    )

    assert first_response.status_code == 202
    assert_problem_details(second_response, "rate limit", expected_status=429)
    assert "Retry-After" in second_response.headers


def test_structured_logs_include_correlation_id(client, caplog):
    caplog.set_level(logging.INFO, logger="service_extractor.audit")

    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("logs correlacionados")),
                "logs.pdf",
                "application/pdf",
            )
        },
        headers={"X-Correlation-ID": "corr-logs-123"},
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)

    audit_logs = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "service_extractor.audit"
    ]

    assert audit_logs
    assert all(event["correlation_id"] == "corr-logs-123" for event in audit_logs)
    assert {event["event_type"] for event in audit_logs} >= {
        "extraction.accepted",
        "extraction.completed",
    }


def test_audit_endpoint_exposes_metrics_without_pdf_content(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_bytes("contenido sensible auditado")),
                "audit.pdf",
                "application/pdf",
            )
        },
        headers={"X-Correlation-ID": "corr-audit-123"},
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)

    audit_response = client.get(f"/internal/v1/extractions/{job_id}/audit")

    assert audit_response.status_code == 200
    audit = audit_response.get_json()
    assert audit["correlation_id"] == "corr-audit-123"
    assert audit["status"] == "completed"
    assert audit["metrics"]["duration_ms"] >= 0
    assert audit["metrics"]["size_bytes"] > 0
    assert audit["metrics"]["extraction_strategy"] in {"basic", "docling"}
    assert audit["audit_metadata"]["pdf_retained"] is False
    assert "text" not in audit
    assert "contenido sensible auditado" not in json.dumps(audit)


def test_audit_endpoint_exposes_failure_type_without_pdf_content(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "file": (
                io.BytesIO(make_pdf_without_extractable_text()),
                "failed-audit.pdf",
                "application/pdf",
            )
        },
        headers={"X-Correlation-ID": "corr-failed-audit"},
        content_type="multipart/form-data",
    )
    job_id = response.get_json()["job_id"]
    wait_for_completed_job(client, job_id)

    audit_response = client.get(f"/internal/v1/extractions/{job_id}/audit")

    assert audit_response.status_code == 200
    audit = audit_response.get_json()
    assert audit["status"] == "failed"
    assert audit["event_type"] == "extraction.failed"
    assert audit["failure"]["type"] == "ValueError"
    assert "no extractable text" in audit["failure"]["message"].lower()
    assert "text" not in audit
