from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.main import create_app


def test_attachment_upload_policy_endpoint_returns_frontend_rules(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("OCR_PROVIDER", "doc2x")
    monkeypatch.setenv("DOC2X_API_KEY", "sk-test")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/api/v1/attachments/upload-policy")

    try:
        assert response.status_code == 200
        data = response.json()
        assert data["pdf_policy"]["text_detection"]["sample_page_limit"] == 5
        assert data["pdf_policy"]["scanned_pdf"]["strategy"] == "doc2x_async_ocr"
        assert data["image_policy"]["strategy"] == "multimodal_llm_direct"
        assert data["upload_form_defaults"]["process_after_ocr"] is True
    finally:
        get_settings.cache_clear()
