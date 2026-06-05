from backend.app.config import Settings


def test_attachment_storage_auto_uses_s3_when_bucket_aliases_are_configured(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "bucket-a")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-a")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret-a")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.example.test")

    settings = Settings()

    assert settings.effective_attachment_storage_backend == "s3"
    assert settings.attachment_s3_configured is True
    assert settings.effective_attachment_s3_bucket == "bucket-a"
    assert settings.effective_attachment_s3_access_key_id == "access-a"
    assert settings.effective_attachment_s3_secret_access_key == "secret-a"
    assert settings.effective_attachment_s3_endpoint_url == "https://s3.example.test"


def test_attachment_storage_auto_falls_back_to_local_without_s3(monkeypatch) -> None:
    for key in (
        "S3_BUCKET",
        "S3_BUCKET_NAME",
        "AWS_S3_BUCKET",
        "BUCKET_NAME",
        "S3_ACCESS_KEY_ID",
        "AWS_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings()

    assert settings.effective_attachment_storage_backend == "local"
    assert settings.attachment_s3_configured is False


def test_explicit_attachment_storage_backend_wins(monkeypatch) -> None:
    monkeypatch.setenv("S3_BUCKET", "bucket-a")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access-a")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret-a")

    settings = Settings(attachment_storage_backend="local")

    assert settings.effective_attachment_storage_backend == "local"


def test_attachment_s3_region_normalizes_railway_placeholder() -> None:
    settings = Settings(attachment_s3_region="<auto>")

    assert settings.effective_attachment_s3_region == "auto"
