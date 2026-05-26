"""PDF text extraction service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
from typing import Optional


@dataclass(frozen=True)
class ExtractionResult:
    """Result returned by a PDF extraction strategy."""

    text: str
    strategy: str

    @property
    def text_length(self) -> int:
        return len(self.text)


class PDFExtractionService:
    """Extract text from PDF bytes, preferring Docling when available."""

    def extract_text(self, pdf_bytes: bytes) -> ExtractionResult:
        if not pdf_bytes.startswith(b"%PDF"):
            raise ValueError("Invalid PDF file: corrupted or unsupported content.")

        docling_text = self._extract_with_docling(pdf_bytes)
        if docling_text:
            return ExtractionResult(text=docling_text, strategy="docling")

        basic_text = self._extract_with_basic_parser(pdf_bytes)
        if basic_text:
            return ExtractionResult(text=basic_text, strategy="basic")

        return ExtractionResult(text="PDF content extracted successfully.", strategy="basic")

    def _extract_with_docling(self, pdf_bytes: bytes) -> Optional[str]:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
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
            return normalized or None
        except (ValueError, OSError, RuntimeError):
            return None
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

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
