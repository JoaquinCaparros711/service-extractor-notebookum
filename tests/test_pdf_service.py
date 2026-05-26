from app.services.circuit_breaker import docling_circuit_breaker
from app.services.pdf_service import PDFExtractionService


def reset_docling_circuit():
    docling_circuit_breaker.failure_count = 0
    docling_circuit_breaker.opened_at = None
    docling_circuit_breaker.half_open = False


def test_pdf_service_extracts_basic_pdf_text():
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
        b"stream\nBT (Hola NotebookUm) Tj ET\nendstream\n%%EOF"
    )

    result = PDFExtractionService().extract_text(pdf_bytes)

    assert result.text == "Hola NotebookUm"
    assert result.strategy in {"basic", "docling"}
    assert result.text_length == len(result.text)


def test_pdf_service_rejects_invalid_pdf_signature():
    service = PDFExtractionService()

    try:
        service.extract_text(b"not-pdf")
    except ValueError as exc:
        assert "pdf" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for invalid PDF")


def test_docling_circuit_opens_after_repeated_primary_engine_failures(app, monkeypatch):
    reset_docling_circuit()
    app.config["DOCLING_CIRCUIT_FAILURE_THRESHOLD"] = 2
    service = PDFExtractionService()
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"stream\nBT (fallback disponible) Tj ET\nendstream\n%%EOF"
    )

    def failing_docling(_pdf_bytes):
        docling_circuit_breaker.record_failure()
        return None

    monkeypatch.setattr(service, "_extract_with_docling", failing_docling)

    with app.app_context():
        first = service.extract_text(pdf_bytes)
        second = service.extract_text(pdf_bytes)

    assert first.strategy == "basic"
    assert first.degraded is True
    assert second.strategy == "basic"
    assert second.degraded is True
    assert docling_circuit_breaker.state == "open"


def test_open_docling_circuit_uses_degraded_basic_fallback(app):
    reset_docling_circuit()
    app.config["DOCLING_CIRCUIT_FAILURE_THRESHOLD"] = 1
    docling_circuit_breaker.record_failure()
    service = PDFExtractionService()
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"stream\nBT (fallback por circuito abierto) Tj ET\nendstream\n%%EOF"
    )

    with app.app_context():
        result = service.extract_text(pdf_bytes)

    assert result.text == "fallback por circuito abierto"
    assert result.strategy == "basic"
    assert result.degraded is True
    assert result.circuit_state == "open"


def test_docling_circuit_recovers_after_reset_window(app, monkeypatch):
    reset_docling_circuit()
    app.config["DOCLING_CIRCUIT_FAILURE_THRESHOLD"] = 1
    app.config["DOCLING_CIRCUIT_RESET_SECONDS"] = 0
    docling_circuit_breaker.record_failure()
    service = PDFExtractionService()

    def successful_docling(_pdf_bytes):
        assert docling_circuit_breaker.allow_request() is True
        docling_circuit_breaker.record_success()
        return "texto recuperado"

    monkeypatch.setattr(service, "_extract_with_docling", successful_docling)

    with app.app_context():
        result = service.extract_text(b"%PDF-1.4\n%%EOF")

    assert result.text == "texto recuperado"
    assert result.strategy == "docling"
    assert result.degraded is False
    assert docling_circuit_breaker.state == "closed"
