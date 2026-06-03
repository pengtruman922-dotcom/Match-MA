# Attachment OCR API v0.1

This document records the first backend skeleton for attachments and OCR parsing.

## Scope

v0.1 provides a verifiable backend chain:

```text
attachment record -> attachment_link -> OCR background_job -> worker -> parsed_document -> evidence_span -> ai_trace -> status/debug APIs
```

It does not upload binary files yet and does not call a real OCR engine yet. The API accepts JSON metadata plus `storage_path`. For testing, the worker can use `mock_extracted_text` from the OCR request or `attachment.metadata_json.mock_extracted_text`.

## Endpoints

### Create attachment

```text
POST /api/v1/attachments
```

Request:

```json
{
  "file_name": "target-teaser.pdf",
  "file_type": "pdf",
  "mime_type": "application/pdf",
  "file_size": 12345,
  "storage_path": "mock://target-teaser.pdf",
  "metadata_json": {
    "mock_extracted_text": "OCR mock text for debug and evidence testing."
  },
  "links": [
    {
      "entity_type": "seller_target",
      "entity_id": "uuid",
      "link_type": "source_document"
    }
  ]
}
```

The API validates supported linked entity types:

- `seller_target`
- `buyer_party`
- `buyer_intent`
- `business_update`
- `recommendation_session`
- `recommendation_report`

### List and get attachments

```text
GET /api/v1/attachments
GET /api/v1/attachments?parse_status=parsed
GET /api/v1/attachments?entity_type=seller_target&entity_id={id}
GET /api/v1/attachments/{attachment_id}
```

### Start OCR job

```text
POST /api/v1/attachments/{attachment_id}/ocr
```

Request:

```json
{
  "force": false,
  "mock_extracted_text": "Optional mock OCR text for v0.1 testing."
}
```

Behavior:

- Creates `background_job` with `job_type=attachment_ocr_parse`.
- Routes the job to `queue_name=ocr`.
- Uses `entity_type=attachment` and `entity_id={attachment_id}`.
- Reuses an existing queued/running/retry_waiting OCR job unless `force=true`.
- Sets `attachment.parse_status=parsing` while the job is queued/running.

### OCR status

```text
GET /api/v1/attachments/{attachment_id}/ocr-status
```

Returns:

- `attachment`
- `linked_entities`
- `latest_job`
- `latest_trace`
- `latest_parsed_document`
- `evidence_spans`
- `debug_ref`

## Worker behavior

`attachment_ocr_parse` runs in the OCR worker:

```text
python -m backend.app.worker --queue ocr --sleep 2
```

v0.1 terminal statuses:

- If mock text exists, `attachment.parse_status=parsed`, `parsed_document.parse_status=parsed`, one `evidence_span` is created, and OCR trace status is `succeeded`.
- If no mock text exists, `attachment.parse_status=skipped`, `parsed_document.parse_status=skipped`, no evidence is created, and OCR trace status is `skipped`.

The worker uses the default model node:

```text
ocr_attachment_parser
```

This node is `node_type=ocr`, prompt editing is disabled, and model config is managed independently like embedding/rerank nodes.

## Debug

Use:

```text
GET /api/v1/debug/entities/attachment/{attachment_id}
```

Debug payload includes:

- attachment metadata
- links
- jobs
- traces
- parsed documents
- evidence spans
- summary counts

## Next step after v0.1

When binary upload/storage is added, `storage_path` should point to a real object storage path. The OCR worker can then replace the skeleton branch with actual parser/OCR execution while keeping the same public API and status/debug contract.
