import io


def assert_problem_details(response, expected_detail):
    assert response.status_code == 400
    assert response.content_type == "application/problem+json"
    data = response.get_json()
    assert data["type"] == "about:blank"
    assert data["title"] == "Bad Request"
    assert data["status"] == 400
    assert expected_detail in data["detail"].lower()
    assert data["instance"] == "/internal/v1/extractions"


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


def test_extract_valid_pdf_returns_text_metadata_and_correlation_id(client):
    response = client.post(
        "/internal/v1/extractions",
        data={
            "document_id": "doc-123",
            "file": (io.BytesIO(make_pdf_bytes()), "sample.pdf", "application/pdf"),
        },
        headers={"X-Correlation-ID": "corr-123"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["document_id"] == "doc-123"
    assert data["correlation_id"] == "corr-123"
    assert data["status"] == "completed"
    assert "NotebookUm extractor listo" in data["text"]
    assert data["metadata"]["filename"] == "sample.pdf"
    assert data["metrics"]["duration_ms"] >= 0
    assert data["metrics"]["text_length"] == len(data["text"])


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

    assert response.status_code == 200
    data = response.get_json()
    assert data["document_id"]
    assert data["correlation_id"]
    assert data["status"] == "completed"


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
