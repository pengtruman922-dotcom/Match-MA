from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Match-MA API"
    app_env: str = "development"
    debug: bool = True
    database_url: str | None = None
    cors_origins: str = "*"
    railway_git_commit_sha: str | None = None
    railway_git_branch: str | None = None
    railway_service_name: str | None = None
    railway_environment_name: str | None = None
    attachment_storage_backend: str = "local"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
