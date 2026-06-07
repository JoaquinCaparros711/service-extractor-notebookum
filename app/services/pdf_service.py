"""PDF text extraction service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import Optional

from flask import current_app, has_app_context

from app.services.circuit_breaker import docling_circuit_breaker


@dataclass(frozen=True)
class ExtractionResult:
    """Result returned by a PDF extraction strategy."""

    text: str
    strategy: str
    degraded: bool = False
    circuit_state: str = "closed"

    @property
    def text_length(self) -> int:
        return len(self.text)


class PDFExtractionService:
    """Extract text from PDF bytes, preferring Docling when available."""

    def extract_text(self, pdf_bytes: bytes) -> ExtractionResult:
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("Invalid PDF file: corrupted or unsupported content.")

        pdfplumber_text = self._extract_with_pdfplumber(pdf_bytes)
        if pdfplumber_text:
            return ExtractionResult(
                text=pdfplumber_text,
                strategy="pdfplumber",
                circuit_state=docling_circuit_breaker.state,
            )

        self._configure_docling_circuit()
        docling_text = self._extract_with_docling(pdf_bytes)
        if docling_text:
            return ExtractionResult(
                text=docling_text,
                strategy="docling",
                circuit_state=docling_circuit_breaker.state,
            )

        basic_text = self._extract_with_basic_parser(pdf_bytes)
        if basic_text:
            return ExtractionResult(
                text=basic_text,
                strategy="basic",
                degraded=True,
                circuit_state=docling_circuit_breaker.state,
            )

        raise ValueError("PDF contains no extractable text.")

    def _extract_with_pdfplumber(self, pdf_bytes: bytes) -> Optional[str]:
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages_text.append(text.strip())
            result = "\n\n".join(pages_text).strip()
            return result or None
        except Exception:
            return None

    def _extract_with_docling(self, pdf_bytes: bytes) -> Optional[str]:
        if not docling_circuit_breaker.allow_request():
            return None

        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            docling_circuit_breaker.record_failure()
            return None

        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                temp_file.write(pdf_bytes)
                temp_path = Path(temp_file.name)

            converter = DocumentConverter()
            result = converter.convert(str(temp_path))
            document = getattr(result, "document", result)

            if hasattr(document, "export_to_markdown"):
                text = document.export_to_markdown()
            elif hasattr(document, "text"):
                text = document.text
            else:
                text = getattr(result, "text", "")

            normalized = str(text).strip() if text is not None else ""
            docling_circuit_breaker.record_success()
            return normalized or None
        except (ValueError, OSError, RuntimeError):
            docling_circuit_breaker.record_failure()
            return None
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _configure_docling_circuit(self) -> None:
        if not has_app_context():
            return

        docling_circuit_breaker.configure(
            failure_threshold=current_app.config["DOCLING_CIRCUIT_FAILURE_THRESHOLD"],
            reset_seconds=current_app.config["DOCLING_CIRCUIT_RESET_SECONDS"],
        )

    def _extract_with_basic_parser(self, pdf_bytes: bytes) -> Optional[str]:
        content = pdf_bytes.decode("latin-1", errors="ignore")
        matches = re.findall(r"\((.*?)\)\s*Tj", content, flags=re.DOTALL)
        if not matches:
            return None

        text = " ".join(self._unescape_pdf_text(match).strip() for match in matches)
        normalized = " ".join(text.split())
        return normalized or None

    def _unescape_pdf_text(self, text: str) -> str:
        return text.replace(r"\(", "(").replace(r"\)", ")").replace(r"\\", "\\")
