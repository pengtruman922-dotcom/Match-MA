import hashlib
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
) -> StoredAttachment:
    backend = (storage_backend or "local").strip().lower()
    if backend != "local":
        raise AttachmentStorageError(
            f"Attachment storage backend '{storage_backend}' is configured but not implemented."
        )

    safe_file_name = safe_upload_filename(original_file_name)
    target_dir = attachment_storage_root(storage_dir) / str(attachment_id)
    target_dir.mkdir(parents=True, exist_ok=True)
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

    return {
        "file_size": total,
        "captured_bytes": bytes(captured),
        "content_sha256": digest.hexdigest(),
    }


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
    metadata_json = attachment.get("metadata_json") if isinstance(attachment.get("metadata_json"), dict) else {}
    local_path = metadata_json.get("local_path")
    paths: list[Path] = []
    if local_path:
        paths.append(Path(str(local_path)))
    storage_uri_path = resolve_storage_uri(
        str(attachment.get("storage_path") or ""),
        storage_dir=storage_dir,
    )
    if storage_uri_path is not None:
        paths.append(storage_uri_path)

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            with path.open("rb") as file:
                data = file.read(max_bytes)
        except OSError:
            continue
        return decode_text_bytes(data)
    return None
