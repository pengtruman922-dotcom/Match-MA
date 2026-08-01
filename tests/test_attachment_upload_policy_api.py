from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.main import create_app


class _NoOcrRowDb:
    """OCR 配置行不存在时的最小 db 替身：解析器会回落到环境变量。"""

    def execute(self, *args, **kwargs):
        class _Result:
            def mappings(self):
                return self

            def one_or_none(self):
                return None

        return _Result()


def test_attachment_upload_policy_endpoint_returns_frontend_rules(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("OCR_PROVIDER", "doc2x")
    monkeypatch.setenv("DOC2X_API_KEY", "sk-test")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: _NoOcrRowDb()
    client = TestClient(app)

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
