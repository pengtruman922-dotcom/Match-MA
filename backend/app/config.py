import os
import hashlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Match-MA API"
    app_env: str = "development"
    debug: bool = True
    database_url: str | None = None
    cors_origins: str = "*"
    auth_enabled: bool = False
    admin_username: str = "admin"
    admin_password: str = "match-ma-admin"
    admin_token: str | None = None
    railway_git_commit_sha: str | None = None
    railway_git_branch: str | None = None
    railway_service_name: str | None = None
    railway_environment_name: str | None = None
    attachment_storage_backend: str = "auto"
    attachment_storage_dir: str = "storage/attachments"
    attachment_max_upload_bytes: int = 25 * 1024 * 1024
    attachment_text_capture_max_bytes: int = 200_000
    attachment_s3_endpoint_url: str | None = None
    attachment_s3_region: str = "auto"
    attachment_s3_bucket: str | None = None
    attachment_s3_access_key_id: str | None = None
    attachment_s3_secret_access_key: str | None = None
    attachment_s3_force_path_style: bool = True
    ocr_provider: str = "skeleton"
    doc2x_base_url: str = "https://v2.doc2x.noedgeai.com"
    doc2x_api_key: str | None = None
    doc2x_model: str = "v3-2026"
    doc2x_poll_interval_seconds: int = 5
    doc2x_max_wait_seconds: int = 900
    pdf_text_detection_page_limit: int = 5
    pdf_text_detection_min_chars: int = 200
    image_multimodal_max_count: int = 5
    image_multimodal_max_upload_bytes: int = 10 * 1024 * 1024
    image_multimodal_max_side: int = 1600
    image_multimodal_jpeg_quality: int = 80
    image_multimodal_target_bytes: int = 1_500_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str | None:
        if not self.database_url:
            return None
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url

    @property
    def effective_attachment_storage_backend(self) -> str:
        backend = (self.attachment_storage_backend or "auto").strip().lower()
        if backend and backend != "auto":
            return backend
        return "s3" if self.attachment_s3_configured else "local"

    @property
    def attachment_s3_configured(self) -> bool:
        return bool(
            self.effective_attachment_s3_bucket
            and self.effective_attachment_s3_access_key_id
            and self.effective_attachment_s3_secret_access_key
        )

    @property
    def effective_attachment_s3_endpoint_url(self) -> str | None:
        return _normalize_s3_text(
            self.attachment_s3_endpoint_url
            or _first_env(
                "S3_ENDPOINT_URL",
                "S3_ENDPOINT",
                "AWS_ENDPOINT_URL",
                "AWS_S3_ENDPOINT_URL",
                "AWS_S3_ENDPOINT",
                "BUCKET_ENDPOINT_URL",
                "RAILWAY_S3_ENDPOINT_URL",
                "R2_ENDPOINT_URL",
                "MINIO_ENDPOINT",
            )
        )

    @property
    def effective_attachment_s3_region(self) -> str:
        return _normalize_s3_region(
            self.attachment_s3_region
            or _first_env("S3_REGION", "AWS_REGION", "AWS_DEFAULT_REGION", "BUCKET_REGION")
            or "auto"
        )

    @property
    def effective_attachment_s3_bucket(self) -> str | None:
        return _normalize_s3_text(
            self.attachment_s3_bucket
            or _first_env(
                "S3_BUCKET",
                "S3_BUCKET_NAME",
                "AWS_BUCKET_NAME",
                "AWS_S3_BUCKET",
                "AWS_S3_BUCKET_NAME",
                "BUCKET_NAME",
                "RAILWAY_S3_BUCKET",
                "R2_BUCKET_NAME",
                "MINIO_BUCKET",
            )
        )

    @property
    def effective_attachment_s3_access_key_id(self) -> str | None:
        return _normalize_s3_text(
            self.attachment_s3_access_key_id
            or _first_env(
                "S3_ACCESS_KEY_ID",
                "AWS_ACCESS_KEY_ID",
                "AWS_S3_ACCESS_KEY_ID",
                "BUCKET_ACCESS_KEY_ID",
                "RAILWAY_S3_ACCESS_KEY_ID",
                "R2_ACCESS_KEY_ID",
                "MINIO_ACCESS_KEY",
            )
        )

    @property
    def effective_attachment_s3_secret_access_key(self) -> str | None:
        return _normalize_s3_text(
            self.attachment_s3_secret_access_key
            or _first_env(
                "S3_SECRET_ACCESS_KEY",
                "AWS_SECRET_ACCESS_KEY",
                "AWS_S3_SECRET_ACCESS_KEY",
                "BUCKET_SECRET_ACCESS_KEY",
                "RAILWAY_S3_SECRET_ACCESS_KEY",
                "R2_SECRET_ACCESS_KEY",
                "MINIO_SECRET_KEY",
            )
        )

    @property
    def effective_doc2x_api_key(self) -> str | None:
        return _normalize_secret_text(self.doc2x_api_key or _first_env("DOC2X_SECRET", "DOC2X_TOKEN"))

    @property
    def effective_admin_token(self) -> str:
        token = _normalize_secret_text(
            self.admin_token
            or _first_env("MATCH_MA_ADMIN_TOKEN", "MATCH_MA_ACCESS_TOKEN", "ADMIN_TOKEN")
        )
        if token:
            return token
        seed = f"{self.admin_username}:{self.admin_password}:{self.app_name}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


def _normalize_s3_region(value: str | None) -> str:
    region = (value or "auto").strip().strip("<>").strip()
    return region or "auto"


def _normalize_s3_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().strip("<>").strip()
    return normalized or None


def _normalize_secret_text(value: str | None) -> str | None:
    normalized = value.strip() if value is not None else None
    if not normalized:
        return None

    # Railway variable values are often pasted with surrounding angle brackets,
    # quotes, or a full Authorization header; normalize those without logging.
    for _ in range(3):
        previous = normalized
        normalized = normalized.strip().strip("<>").strip()
        if (
            (normalized.startswith('"') and normalized.endswith('"'))
            or (normalized.startswith("'") and normalized.endswith("'"))
        ):
            normalized = normalized[1:-1].strip()
        lowered = normalized.lower()
        if lowered.startswith("authorization:"):
            normalized = normalized.split(":", 1)[1].strip()
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        if normalized == previous:
            break
    return normalized or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
