from io import BytesIO
from uuid import UUID

import pytest

from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    AttachmentTooLargeError,
    read_local_text_content,
    resolve_storage_uri,
    save_upload_file,
)

ATTACHMENT_ID = UUID("00000000-0000-0000-0000-000000000101")


def test_save_upload_file_stores_local_text_and_hash(tmp_path) -> None:
    content = "???? storage abstraction".encode("utf-8")

    stored = save_upload_file(
        BytesIO(content),
        attachment_id=ATTACHMENT_ID,
        original_file_name="../foo bar.txt",
        content_type="text/plain; charset=utf-8",
        storage_dir=str(tmp_path),
        storage_backend="local",
        max_bytes=1024,
        text_capture_max_bytes=200_000,
    )

    assert stored.safe_file_name == "foo_bar.txt"
    assert stored.file_type == "txt"
    assert stored.file_size == len(content)
    assert stored.storage_backend == "local"
    assert stored.storage_uri == f"local://attachments/{ATTACHMENT_ID}/foo_bar.txt"
    assert stored.local_path is not None and stored.local_path.exists()
    assert stored.local_path.read_bytes() == content
    assert stored.content_sha256 == "a38e0f8810dd3669bb13e54fe85b5fcd1f718280b3f934f1b128b78222c88709"
    assert stored.uploaded_text_content == "???? storage abstraction"
    assert stored.uploaded_text_truncated is False
    assert stored.metadata_json()["storage_contract_version"] == "v0.1"


def test_save_upload_file_decodes_gb18030_text(tmp_path) -> None:
    content = "??GBK??".encode("gb18030")

    stored = save_upload_file(
        BytesIO(content),
        attachment_id=ATTACHMENT_ID,
        original_file_name="memo.log",
        content_type="application/octet-stream",
        storage_dir=str(tmp_path),
        storage_backend="local",
        max_bytes=1024,
        text_capture_max_bytes=200_000,
    )

    assert stored.uploaded_text_content == "??GBK??"
    assert stored.text_capture_source == "uploaded_text_content"


def test_save_upload_file_does_not_capture_binary_text(tmp_path) -> None:
    stored = save_upload_file(
        BytesIO(b"\x00\x01binary"),
        attachment_id=ATTACHMENT_ID,
        original_file_name="file.bin",
        content_type="application/octet-stream",
        storage_dir=str(tmp_path),
        storage_backend="local",
        max_bytes=1024,
        text_capture_max_bytes=200_000,
    )

    assert stored.uploaded_text_content is None
    assert stored.text_capture_source == "not_text_upload"
    assert "uploaded_text_content" not in stored.metadata_json()


def test_save_upload_file_raises_and_cleans_up_when_too_large(tmp_path) -> None:
    with pytest.raises(AttachmentTooLargeError):
        save_upload_file(
            BytesIO(b"a" * 11),
            attachment_id=ATTACHMENT_ID,
            original_file_name="large.txt",
            content_type="text/plain",
            storage_dir=str(tmp_path),
            storage_backend="local",
            max_bytes=10,
            text_capture_max_bytes=200_000,
        )

    assert not (tmp_path / str(ATTACHMENT_ID) / "large.txt").exists()


def test_save_upload_file_rejects_unimplemented_backend(tmp_path) -> None:
    with pytest.raises(AttachmentStorageError):
        save_upload_file(
            BytesIO(b"abc"),
            attachment_id=ATTACHMENT_ID,
            original_file_name="a.txt",
            content_type="text/plain",
            storage_dir=str(tmp_path),
            storage_backend="oss",
            max_bytes=1024,
            text_capture_max_bytes=200_000,
        )


def test_resolve_storage_uri_and_read_local_text_content(tmp_path) -> None:
    stored = save_upload_file(
        BytesIO("fallback text".encode("utf-8")),
        attachment_id=ATTACHMENT_ID,
        original_file_name="note.txt",
        content_type="text/plain",
        storage_dir=str(tmp_path),
        storage_backend="local",
        max_bytes=1024,
        text_capture_max_bytes=1,
    )

    assert resolve_storage_uri(stored.storage_uri, storage_dir=str(tmp_path)) == stored.local_path
    assert resolve_storage_uri("local://attachments/../../x", storage_dir=str(tmp_path)) is None
    assert read_local_text_content({"storage_path": stored.storage_uri}, storage_dir=str(tmp_path), max_bytes=100) == "fallback text"
