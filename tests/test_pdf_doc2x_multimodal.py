from io import BytesIO
from uuid import UUID

from PIL import Image

from backend.app.ai.doc2x_client import poll_doc2x_status
from backend.app.jobs.handlers import _attach_multimodal_images, _safe_prompt_messages_for_trace
from backend.app.services.image_inputs import prepare_image_for_multimodal
from backend.app.services.pdf_inspection import inspect_pdf_text_layer


def test_pdf_inspection_marks_blank_pdf_as_scanned() -> None:
    from pypdf import PdfWriter

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)

    result = inspect_pdf_text_layer(output.getvalue(), page_limit=5, min_total_chars=200)

    assert result.pdf_kind == "scanned_pdf"
    assert result.extracted_char_count == 0


def test_pdf_inspection_uses_total_text_threshold(monkeypatch) -> None:
    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _Reader:
        pages = [_Page("封面"), _Page("x" * 199)]

        def __init__(self, _stream) -> None:
            pass

    monkeypatch.setattr("pypdf.PdfReader", _Reader)

    result = inspect_pdf_text_layer(b"%PDF", page_limit=5, min_total_chars=200)

    assert result.pdf_kind == "text_pdf"
    assert result.extracted_char_count >= 200


def test_doc2x_status_extracts_markdown(monkeypatch) -> None:
    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return (
                b'{"code":"success","data":{"status":"success","progress":100,'
                b'"result":{"pages":[{"md":"# A"},{"md":"B"}]}}}'
            )

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _Response())

    result = poll_doc2x_status(base_url="https://example.test", api_key="sk-test", uid="uid")

    assert result.status == "success"
    assert result.progress == 100
    assert result.markdown_text == "# A\n\nB"
    assert result.page_count == 2


def test_prepare_image_for_multimodal_compresses_to_data_url() -> None:
    image = Image.new("RGB", (2400, 1200), color=(255, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")

    prepared = prepare_image_for_multimodal(
        output.getvalue(),
        attachment_id=str(UUID("00000000-0000-0000-0000-000000000001")),
        file_name="chat.png",
        mime_type="image/png",
        max_side=1600,
        jpeg_quality=80,
        target_bytes=1_500_000,
    )

    assert prepared.data_url.startswith("data:image/jpeg;base64,")
    assert prepared.width <= 1600
    assert prepared.height <= 1600
    assert prepared.compressed_bytes <= 1_500_000


def test_multimodal_prompt_trace_redacts_data_url() -> None:
    messages = [{"role": "user", "content": "hello"}]
    updated = _attach_multimodal_images(
        messages,
        [
            {
                "attachment_id": "a1",
                "file_name": "x.jpg",
                "data_url": "data:image/jpeg;base64," + "a" * 100,
            }
        ],
    )
    safe = _safe_prompt_messages_for_trace(updated)

    assert isinstance(updated[0]["content"], list)
    assert safe[0]["content"][-1]["image_url"]["url"].startswith("<redacted data url")
    assert "base64" not in safe[0]["content"][-1]["image_url"]["url"]


def test_multimodal_prompt_supports_node_specific_instruction() -> None:
    messages = [{"role": "user", "content": "整理跟进"}]
    instruction = "Only return content and next_step; never return raw_evidence_text."

    updated = _attach_multimodal_images(
        messages,
        [{"attachment_id": "a1", "file_name": "chat.jpg", "data_url": "data:image/jpeg;base64,YQ=="}],
        instruction=instruction,
    )

    assert updated[0]["content"][1] == {"type": "text", "text": instruction}
    assert updated[0]["content"][2]["type"] == "image_url"
