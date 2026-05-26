import io
from time import sleep


def assert_problem_details(response, expected_detail):
    assert response.status_code == 400
    assert response.content_type == "application/problem+json"
    data = response.get_json()
    assert data["type"] == "about:blank"
    assert data["title"] == "Bad Request"
    assert data["status"] == 400
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

    status = wait_for_completed_job(client, data["job_id"])
    assert status["status"] == "completed"

    result_response = client.get(f"/internal/v1/extractions/{data['job_id']}/result")
    assert result_response.status_code == 200
    result = result_response.get_json()
    assert result["job_id"] == data["job_id"]
    assert result["document_id"] == "doc-123"
    assert result["correlation_id"] == "corr-123"
    assert result["status"] == "completed"
    assert "NotebookUm extractor listo" in result["text"]
    assert result["metadata"]["filename"] == "sample.pdf"
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
