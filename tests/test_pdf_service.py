from app.services.pdf_service import PDFExtractionService


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
