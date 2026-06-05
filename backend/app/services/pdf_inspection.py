from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO


class PdfInspectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfInspectionResult:
    pdf_kind: str
    page_count: int | None
    sampled_page_count: int
    extracted_text: str
    extracted_char_count: int
    threshold_chars: int
    error_message: str | None = None

    @property
    def is_text_pdf(self) -> bool:
        return self.pdf_kind == "text_pdf"


def inspect_pdf_text_layer(
    file_bytes: bytes,
    *,
    page_limit: int = 5,
    min_total_chars: int = 200,
    max_chars: int = 200_000,
) -> PdfInspectionResult:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise PdfInspectionError("pypdf is required for PDF text-layer inspection.") from exc

    try:
        reader = PdfReader(BytesIO(file_bytes))
        page_count = len(reader.pages)
        sampled_pages = min(max(page_limit, 1), page_count)
        parts: list[str] = []
        for page in reader.pages[:sampled_pages]:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text.strip())
            if sum(len(item) for item in parts) >= max_chars:
                break
    except Exception as exc:
        return PdfInspectionResult(
            pdf_kind="unknown_pdf",
            page_count=None,
            sampled_page_count=0,
            extracted_text="",
            extracted_char_count=0,
            threshold_chars=min_total_chars,
            error_message=str(exc),
        )

    extracted_text = "\n\n".join(parts).strip()
    if len(extracted_text) > max_chars:
        extracted_text = extracted_text[:max_chars]
    char_count = len(extracted_text)
    pdf_kind = "text_pdf" if char_count >= min_total_chars else "scanned_pdf"
    return PdfInspectionResult(
        pdf_kind=pdf_kind,
        page_count=page_count,
        sampled_page_count=sampled_pages,
        extracted_text=extracted_text,
        extracted_char_count=char_count,
        threshold_chars=min_total_chars,
    )
