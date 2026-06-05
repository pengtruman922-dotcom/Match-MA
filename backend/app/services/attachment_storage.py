import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID


TEXT_FILE_EXTENSIONS = {".csv", ".json", ".log", ".md", ".txt", ".tsv", ".xml", ".yaml", ".yml"}
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/csv",
    "application/json",
    "application/xml",
    "application/x-ndjson",
    "application/yaml",
}


class AttachmentStorageError(Exception):
    """Base error for attachment storage failures."""


class AttachmentTooLargeError(AttachmentStorageError):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"Attachment exceeds max upload size of {max_bytes} bytes.")


class AttachmentNotFoundError(AttachmentStorageError):
    pass


@dataclass(frozen=True)
class StoredAttachment:
    attachment_id: UUID
    original_file_name: str
    safe_file_name: str
    file_type: str | None
    content_type: str | None
    file_size: int
    storage_backend: str
    storage_uri: str
    local_path: Path | None
    content_sha256: str
    uploaded_text_content: str | None
    uploaded_text_truncated: bool
    text_capture_source: str

    def metadata_json(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "uploaded_via": "multipart_upload",
            "storage_contract_version": "v0.1",
            "original_file_name": self.original_file_name,
            "safe_file_name": self.safe_file_name,
            "storage_backend": self.storage_backend,
            "storage_uri": self.storage_uri,
            "content_sha256": self.content_sha256,
            "text_capture_source": self.text_capture_source,
            "uploaded_text_truncated": self.uploaded_text_truncated,
        }
        if self.local_path is not None:
            metadata["local_path"] = str(self.local_path)
        if self.uploaded_text_content is not None:
            metadata["uploaded_text_content"] = self.uploaded_text_content
        return metadata


def save_upload_file(
    stream: BinaryIO,
    *,
    attachment_id: UUID,
    original_file_name: str,
    content_type: str | None,
    storage_dir: str,
    storage_backend: str,
    max_bytes: int,
    text_capture_max_bytes: int,
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_force_path_style: bool = True,
) -> StoredAttachment:
    backend = (storage_backend or "local").strip().lower()
    safe_file_name = safe_upload_filename(original_file_name)

    if backend in {"s3", "railway_s3"}:
        return _save_s3_upload_file(
            stream,
            attachment_id=attachment_id,
            original_file_name=original_file_name,
            safe_file_name=safe_file_name,
            content_type=content_type,
            max_bytes=max_bytes,
            text_capture_max_bytes=text_capture_max_bytes,
            endpoint_url=s3_endpoint_url,
            region=s3_region,
            bucket=s3_bucket,
            access_key_id=s3_access_key_id,
            secret_access_key=s3_secret_access_key,
            force_path_style=s3_force_path_style,
        )

    if backend != "local":
        raise AttachmentStorageError(f"Attachment storage backend '{storage_backend}' is not supported.")

    target_dir = attachment_storage_root(storage_dir) / str(attachment_id)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise AttachmentStorageError(f"Failed to create local attachment directory: {exc}") from exc
    target_path = target_dir / safe_file_name
    storage_uri = f"local://attachments/{attachment_id}/{safe_file_name}"
    capture_text = is_text_upload(safe_file_name, content_type)
    written = _write_local_file(
        stream,
        target_path,
        max_bytes=max_bytes,
        capture_text=capture_text,
        text_capture_max_bytes=text_capture_max_bytes,
    )

    text_content = None
    text_capture_source = "not_text_upload"
    if capture_text:
        if text_capture_max_bytes <= 0:
            text_capture_source = "disabled"
        elif not written["captured_bytes"]:
            text_capture_source = "empty_upload"
        else:
            text_content = decode_text_bytes(written["captured_bytes"])
            text_capture_source = "uploaded_text_content" if text_content else "decode_failed"

    return StoredAttachment(
        attachment_id=attachment_id,
        original_file_name=original_file_name,
        safe_file_name=safe_file_name,
        file_type=file_type_from_name(safe_file_name),
        content_type=content_type,
        file_size=written["file_size"],
        storage_backend=backend,
        storage_uri=storage_uri,
        local_path=target_path,
        content_sha256=written["content_sha256"],
        uploaded_text_content=text_content,
        uploaded_text_truncated=bool(
            capture_text
            and text_capture_max_bytes > 0
            and written["file_size"] > len(written["captured_bytes"])
        ),
        text_capture_source=text_capture_source,
    )


def read_attachment_bytes(
    attachment: dict[str, Any],
    *,
    storage_dir: str,
    max_bytes: int,
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_force_path_style: bool = True,
) -> bytes | None:
    metadata_json = attachment.get("metadata_json") if isinstance(attachment.get("metadata_json"), dict) else {}
    storage_uri = str(metadata_json.get("storage_uri") or attachment.get("storage_path") or "")
    backend = str(metadata_json.get("storage_backend") or _storage_backend_from_uri(storage_uri) or "local").lower()

    if backend in {"s3", "railway_s3"} or storage_uri.startswith("s3://"):
        return _read_s3_bytes(
            storage_uri,
            max_bytes=max_bytes,
            endpoint_url=s3_endpoint_url,
            region=s3_region,
            bucket=s3_bucket,
            access_key_id=s3_access_key_id,
            secret_access_key=s3_secret_access_key,
            force_path_style=s3_force_path_style,
        )

    paths = _local_attachment_paths(attachment, storage_dir=storage_dir)
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("rb") as file:
                data = file.read(max_bytes + 1)
        except OSError:
            continue
        if len(data) > max_bytes:
            raise AttachmentTooLargeError(max_bytes)
        return data
    return None


def save_generated_text(
    content: str,
    *,
    storage_backend: str,
    storage_dir: str,
    key_prefix: str,
    file_name: str,
    content_type: str = "text/plain; charset=utf-8",
    s3_endpoint_url: str | None = None,
    s3_region: str | None = None,
    s3_bucket: str | None = None,
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_force_path_style: bool = True,
) -> str:
    backend = (storage_backend or "local").strip().lower()
    safe_prefix = "/".join(_safe_s3_key_part(part) for part in key_prefix.split("/") if part)
    safe_file_name = safe_upload_filename(file_name)
    data = content.encode("utf-8")

    if backend in {"s3", "railway_s3"}:
        bucket = _required_s3_bucket(s3_bucket)
        key = f"{safe_prefix}/{safe_file_name}" if safe_prefix else safe_file_name
        client = _s3_client(
            endpoint_url=s3_endpoint_url,
            region=s3_region,
            access_key_id=s3_access_key_id,
            secret_access_key=s3_secret_access_key,
            force_path_style=s3_force_path_style,
        )
        try:
            client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        except Exception as exc:  # pragma: no cover - exercised only with real S3
            raise AttachmentStorageError(f"Failed to write generated text to S3: {exc}") from exc
        return f"s3://{bucket}/{key}"

    if backend != "local":
        raise AttachmentStorageError(f"Attachment storage backend '{storage_backend}' is not supported.")

    root = attachment_storage_root(storage_dir)
    target_path = (root / safe_prefix / safe_file_name).resolve()
    try:
        target_path.relative_to(root.resolve())
    except ValueError as exc:
        raise AttachmentStorageError("Generated text path escapes the attachment storage root.") from exc
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    return f"local://attachments/{safe_prefix}/{safe_file_name}" if safe_prefix else f"local://attachments/{safe_file_name}"


def _write_local_file(
    stream: BinaryIO,
    target_path: Path,
    *,
    max_bytes: int,
    capture_text: bool,
    text_capture_max_bytes: int,
) -> dict[str, Any]:
    total = 0
    captured = bytearray()
    digest = hashlib.sha256()
    capture_limit = max(text_capture_max_bytes, 0)

    try:
        with target_path.open("wb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise AttachmentTooLargeError(max_bytes)
                output.write(chunk)
                digest.update(chunk)
                if capture_text and capture_limit > 0 and len(captured) < capture_limit:
                    remaining = capture_limit - len(captured)
                    captured.extend(chunk[:remaining])
    except AttachmentTooLargeError:
        target_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        target_path.unlink(missing_ok=True)
        raise AttachmentStorageError(f"Failed to write local attachment file: {exc}") from exc

    return {
        "file_size": total,
        "captured_bytes": bytes(captured),
        "content_sha256": digest.hexdigest(),
    }


def _save_s3_upload_file(
    stream: BinaryIO,
    *,
    attachment_id: UUID,
    original_file_name: str,
    safe_file_name: str,
    content_type: str | None,
    max_bytes: int,
    text_capture_max_bytes: int,
    endpoint_url: str | None,
    region: str | None,
    bucket: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    force_path_style: bool,
) -> StoredAttachment:
    file_data = _read_stream_limited(stream, max_bytes=max_bytes)
    content_sha256 = hashlib.sha256(file_data).hexdigest()
    bucket_name = _required_s3_bucket(bucket)
    key = f"attachments/{attachment_id}/{safe_file_name}"
    client = _s3_client(
        endpoint_url=endpoint_url,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        force_path_style=force_path_style,
    )
    try:
        client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=file_data,
            ContentType=content_type or "application/octet-stream",
        )
    except Exception as exc:  # pragma: no cover - exercised only with real S3
        raise AttachmentStorageError(f"Failed to upload attachment to S3: {exc}") from exc

    capture_text = is_text_upload(safe_file_name, content_type)
    text_content = None
    text_capture_source = "not_text_upload"
    if capture_text:
        if text_capture_max_bytes <= 0:
            text_capture_source = "disabled"
        elif not file_data:
            text_capture_source = "empty_upload"
        else:
            text_content = decode_text_bytes(file_data[:text_capture_max_bytes])
            text_capture_source = "uploaded_text_content" if text_content else "decode_failed"

    return StoredAttachment(
        attachment_id=attachment_id,
        original_file_name=original_file_name,
        safe_file_name=safe_file_name,
        file_type=file_type_from_name(safe_file_name),
        content_type=content_type,
        file_size=len(file_data),
        storage_backend="s3",
        storage_uri=f"s3://{bucket_name}/{key}",
        local_path=None,
        content_sha256=content_sha256,
        uploaded_text_content=text_content,
        uploaded_text_truncated=bool(
            capture_text and text_capture_max_bytes > 0 and len(file_data) > text_capture_max_bytes
        ),
        text_capture_source=text_capture_source,
    )


def _read_stream_limited(stream: BinaryIO, *, max_bytes: int) -> bytes:
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = stream.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AttachmentTooLargeError(max_bytes)
        chunks.append(chunk)
    return b"".join(chunks)


def attachment_storage_root(storage_dir: str) -> Path:
    root = Path(storage_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    return root


def safe_upload_filename(file_name: str) -> str:
    name = Path(file_name or "upload.bin").name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe[:180] or "upload.bin"


def file_type_from_name(file_name: str) -> str | None:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    return suffix or None


def is_text_upload(file_name: str, content_type: str | None) -> bool:
    suffix = Path(file_name).suffix.lower()
    mime_type = (content_type or "").split(";")[0].strip().lower()
    return suffix in TEXT_FILE_EXTENSIONS or mime_type in TEXT_MIME_TYPES or mime_type.startswith(TEXT_MIME_PREFIXES)


def decode_text_bytes(value: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return value.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="ignore").strip() or None


def resolve_storage_uri(storage_uri: str | None, *, storage_dir: str) -> Path | None:
    if not storage_uri or not storage_uri.startswith("local://attachments/"):
        return None
    root = attachment_storage_root(storage_dir).resolve()
    relative = storage_uri.removeprefix("local://attachments/")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def read_local_text_content(
    attachment: dict[str, Any],
    *,
    storage_dir: str,
    max_bytes: int,
) -> str | None:
    for path in _local_attachment_paths(attachment, storage_dir=storage_dir):
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("rb") as file:
                data = file.read(max_bytes)
        except OSError:
            continue
        return decode_text_bytes(data)
    return None


def _local_attachment_paths(attachment: dict[str, Any], *, storage_dir: str) -> list[Path]:
    metadata_json = attachment.get("metadata_json") if isinstance(attachment.get("metadata_json"), dict) else {}
    local_path = metadata_json.get("local_path")
    paths: list[Path] = []
    if local_path:
        paths.append(Path(str(local_path)))
    storage_uri_path = resolve_storage_uri(
        str(metadata_json.get("storage_uri") or attachment.get("storage_path") or ""),
        storage_dir=storage_dir,
    )
    if storage_uri_path is not None:
        paths.append(storage_uri_path)
    return paths


def _read_s3_bytes(
    storage_uri: str,
    *,
    max_bytes: int,
    endpoint_url: str | None,
    region: str | None,
    bucket: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    force_path_style: bool,
) -> bytes | None:
    bucket_name, key = _parse_s3_uri(storage_uri, fallback_bucket=bucket)
    if not bucket_name or not key:
        return None
    client = _s3_client(
        endpoint_url=endpoint_url,
        region=region,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        force_path_style=force_path_style,
    )
    try:
        response = client.get_object(Bucket=bucket_name, Key=key)
        data = response["Body"].read(max_bytes + 1)
    except Exception as exc:  # pragma: no cover - exercised only with real S3
        raise AttachmentNotFoundError(f"Failed to read attachment from S3: {exc}") from exc
    if len(data) > max_bytes:
        raise AttachmentTooLargeError(max_bytes)
    return data


def _parse_s3_uri(storage_uri: str, *, fallback_bucket: str | None = None) -> tuple[str | None, str | None]:
    if not storage_uri:
        return None, None
    if storage_uri.startswith("s3://"):
        rest = storage_uri.removeprefix("s3://")
        bucket, _, key = rest.partition("/")
        return (bucket or fallback_bucket), key or None
    return fallback_bucket, storage_uri.lstrip("/") or None


def _storage_backend_from_uri(storage_uri: str) -> str | None:
    if storage_uri.startswith("s3://"):
        return "s3"
    if storage_uri.startswith("local://"):
        return "local"
    return None


def _required_s3_bucket(bucket: str | None) -> str:
    bucket_name = bucket or os.getenv("ATTACHMENT_S3_BUCKET")
    if not bucket_name:
        raise AttachmentStorageError("ATTACHMENT_S3_BUCKET is required for S3 attachment storage.")
    return bucket_name


def _s3_client(
    *,
    endpoint_url: str | None,
    region: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
    force_path_style: bool,
) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise AttachmentStorageError("boto3 is required for S3 attachment storage.") from exc

    config = Config(s3={"addressing_style": "path" if force_path_style else "auto"})
    try:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url or os.getenv("ATTACHMENT_S3_ENDPOINT_URL"),
            region_name=region or os.getenv("ATTACHMENT_S3_REGION") or "auto",
            aws_access_key_id=access_key_id or os.getenv("ATTACHMENT_S3_ACCESS_KEY_ID"),
            aws_secret_access_key=secret_access_key or os.getenv("ATTACHMENT_S3_SECRET_ACCESS_KEY"),
            config=config,
        )
    except Exception as exc:  # pragma: no cover - exercised only with real S3 config
        raise AttachmentStorageError(f"Failed to create S3 attachment client: {exc}") from exc


def _safe_s3_key_part(value: str) -> str:
    return safe_upload_filename(value).replace("\\", "_").replace("/", "_")
