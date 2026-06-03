from backend.app.ai.ocr_client import OcrInput, build_attachment_ocr_input_json, call_attachment_ocr


def _node_config(model_name: str = "ocr-skeleton-v0") -> dict:
    return {
        "node_config_id": "node-1",
        "node_name": "ocr_attachment_parser",
        "provider_name": "aliyun_dashscope",
        "model_name": model_name,
        "metadata_json": {"execution_mode": "skeleton"},
    }


def _ocr_input(*, text: str = "", file_name: str = "note.txt", mime_type: str = "text/plain") -> OcrInput:
    return OcrInput(
        attachment_id="att-1",
        file_name=file_name,
        file_type=file_name.rsplit(".", 1)[-1] if "." in file_name else None,
        mime_type=mime_type,
        file_size=len(text.encode("utf-8")) if text else None,
        storage_path="local://attachments/att-1/note.txt",
        metadata_json={
            "storage_backend": "local",
            "storage_uri": "local://attachments/att-1/note.txt",
            "content_sha256": "abc",
            "text_capture_source": "uploaded_text_content" if text else None,
            "uploaded_text_truncated": False,
        },
        extracted_text_hint=text,
    )


def test_call_attachment_ocr_uses_text_hint_as_successful_output() -> None:
    result = call_attachment_ocr(node_config=_node_config(), ocr_input=_ocr_input(text="OCR??"))

    assert result.terminal_parse_status == "parsed"
    assert result.trace_status == "succeeded"
    assert result.execution_mode == "mock_text"
    assert result.extracted_text == "OCR??"
    assert result.raw_output_text == "OCR??"
    assert result.parsed_output_json["evidence_created"] is True
    assert result.error_message is None


def test_call_attachment_ocr_skips_when_no_text_hint() -> None:
    result = call_attachment_ocr(node_config=_node_config(), ocr_input=_ocr_input(text=""))

    assert result.terminal_parse_status == "skipped"
    assert result.trace_status == "skipped"
    assert result.extracted_text == ""
    assert "provide mock_extracted_text" in (result.error_message or "")
    assert result.parsed_output_json["evidence_created"] is False


def test_call_attachment_ocr_binary_message_mentions_object_storage() -> None:
    result = call_attachment_ocr(
        node_config=_node_config("aliyun-ocr-placeholder"),
        ocr_input=_ocr_input(text="", file_name="teaser.pdf", mime_type="application/pdf"),
    )

    assert result.terminal_parse_status == "skipped"
    assert "durable object storage" in (result.error_message or "")
    assert "real OCR provider" in (result.error_message or "")


def test_build_attachment_ocr_input_json_exposes_storage_contract() -> None:
    input_json = build_attachment_ocr_input_json(node_config=_node_config(), ocr_input=_ocr_input(text="abc"))

    assert input_json["attachment_id"] == "att-1"
    assert input_json["storage_backend"] == "local"
    assert input_json["storage_uri"] == "local://attachments/att-1/note.txt"
    assert input_json["content_sha256"] == "abc"
    assert input_json["has_text_hint"] is True
    assert input_json["node_execution_mode"] == "skeleton"
