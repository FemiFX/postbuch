from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image
from pdf2image import convert_from_bytes
from pypdf import PdfReader

from postbuch.core.config import get_settings

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None


@dataclass
class OCRResult:
    text: str | None
    status: str
    method: str | None = None
    page_count: int | None = None
    confidence: int | None = None
    text_layer_present: bool = False
    error: str | None = None


class OCRService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def extract(self, content: bytes, mime_type: str) -> OCRResult:
        try:
            if mime_type == "application/pdf":
                return self._extract_pdf(content)
            if mime_type.startswith("image/"):
                return self._extract_image(content)
            return OCRResult(text=None, status="not_applicable")
        except Exception as exc:  # pragma: no cover
            return OCRResult(text=None, status="failed", error=str(exc))

    def _extract_pdf(self, content: bytes) -> OCRResult:
        reader = PdfReader(io.BytesIO(content))
        texts = [page.extract_text() or "" for page in reader.pages]
        combined = "\n".join(texts).strip()
        if len(combined) >= self.settings.ocr_min_text_length:
            return OCRResult(
                text=combined,
                status="completed",
                method="pdf_text",
                page_count=len(reader.pages),
                text_layer_present=True,
            )
        if pytesseract is None:
            return OCRResult(text=combined or None, status="failed", method="pdf_text", page_count=len(reader.pages), error="pytesseract unavailable")
        images = convert_from_bytes(content)
        rendered_text = "\n".join(
            pytesseract.image_to_string(image, lang=self.settings.ocr_language).strip()
            for image in images
        ).strip()
        return OCRResult(
            text=rendered_text or combined or None,
            status="completed" if rendered_text else "failed",
            method="pdf_ocr",
            page_count=len(reader.pages),
            text_layer_present=False,
            error=None if rendered_text else "OCR returned no text",
        )

    def _extract_image(self, content: bytes) -> OCRResult:
        if pytesseract is None:
            return OCRResult(text=None, status="failed", error="pytesseract unavailable")
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image, lang=self.settings.ocr_language).strip()
        return OCRResult(text=text or None, status="completed", method="image_ocr", page_count=1)
