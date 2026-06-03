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
  "mock_extracted_text": "Optional mock OCR text for v0.1 testing.",
  "auto_parse_linked_objects": false,
  "parse_entity_types": ["seller_target"]
}
```

Behavior:

- Creates `background_job` with `job_type=attachment_ocr_parse`.
- Routes the job to `queue_name=ocr`.
- Uses `entity_type=attachment` and `entity_id={attachment_id}`.
- Reuses an existing queued/running/retry_waiting OCR job unless `force=true`.
- Sets `attachment.parse_status=parsing` while the job is queued/running.
- If `auto_parse_linked_objects=true`, after OCR succeeds the worker creates child parse jobs for linked `seller_target` and/or `buyer_intent` objects.
- `parse_entity_types` is optional. Empty means both `seller_target` and `buyer_intent`; otherwise it can contain `seller_target` and/or `buyer_intent`.

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
- `child_parse_jobs`
- `debug_ref`

### Business update attachment ingest

Business updates can now create/link attachments directly, so the frontend does
not have to call the generic attachment API first.

```text
POST /api/v1/business-updates
POST /api/v1/business-updates/{business_update_id}/attachments
```

Request fields on `POST /business-updates`:

```json
{
  "raw_text": "Manual update text",
  "bound_seller_target_ids": ["uuid"],
  "attachments": [
    {
      "file_name": "target-teaser.pdf",
      "file_type": "pdf",
      "mime_type": "application/pdf",
      "storage_path": "mock://target-teaser.pdf",
      "mock_extracted_text": "OCR text used by the v0.1 worker."
    }
  ],
  "auto_start_ocr": true,
  "process_after_ocr": true,
  "include_attachment_text": true
}
```

Behavior:

- `attachments` creates attachment rows; `attachment_ids` links existing rows.
- All linked attachments get an `attachment_link` to the business update.
- By default, attachments are also linked to bound seller targets, buyer parties,
  and buyer intents with `link_type=business_update_context`.
- `auto_start_ocr=true` creates `attachment_ocr_parse` jobs in the `ocr` queue.
- `process_after_ocr=true` lets the OCR worker enqueue a follow-up
  `business_update_extract_actions` job in the `llm` queue after OCR evidence is
  created.
- `include_attachment_text=true` makes the business update extractor append OCR
  evidence text to the LLM input and include attachment evidence in
  `context_json.attachments`.

`GET /api/v1/business-updates/{id}/review-page` now returns an `attachments`
array with the latest OCR job, latest parsed document, latest evidence snippet,
and debug refs for the review UI.

## Worker behavior

`attachment_ocr_parse` runs in the OCR worker:

```text
python -m backend.app.worker --queue ocr --sleep 2
```

v0.1 terminal statuses:

- If mock text exists, `attachment.parse_status=parsed`, `parsed_document.parse_status=parsed`, one `evidence_span` is created, and OCR trace status is `succeeded`.
- If no mock text exists, `attachment.parse_status=skipped`, `parsed_document.parse_status=skipped`, no evidence is created, and OCR trace status is `skipped`.
- If auto-parse is enabled, the OCR worker creates child `seller_target_parse` / `buyer_intent_parse` jobs with `parent_job_id` pointing to the OCR job.
- Child parse jobs carry `attachment_id`, `parsed_document_id`, and `evidence_id` in `payload_json`, so applied fields can write source records.
- If the OCR job payload has `business_update_id` and
  `process_business_update_after_ocr=true`, the worker also creates a child
  `business_update_extract_actions` job. That child job carries
  `trigger_attachment_id` and `trigger_evidence_id`, so the extractor can use the
  relevant OCR evidence span and attach it to extracted actions when unambiguous.

## Field Sources

Parser-applied fields now write lightweight `field_value_source` rows:

```text
GET /api/v1/field-sources?entity_type=seller_target&entity_id={id}
GET /api/v1/field-sources?entity_type=seller_target&entity_id={id}&field_path=business_summary
```

Each source row includes:

- field path and current value snapshot
- source type / source id
- evidence id and evidence span when available
- source label
- review status
- debug ref

For OCR-driven parsing, `source_type=attachment_ocr_parse`, `source_id={ocr_job_id}`, and `evidence_id` points to the OCR evidence span.

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

### Upload attachment

```text
POST /api/v1/attachments/upload
Content-Type: multipart/form-data
```

Form fields:

- `file`: required uploaded file.
- `visibility`: optional, defaults to `workspace`.
- `entity_type`, `entity_id`, `link_type`: optional direct link to a business object.
- `auto_start_ocr`: optional boolean. If true, creates an OCR job immediately.
- `auto_parse_linked_objects`: optional boolean for OCR-driven seller/buyer parsing.
- `parse_entity_types`: optional JSON array or comma-separated string, e.g. `["seller_target"]` or `seller_target,buyer_intent`.
- `metadata_json`: optional JSON object string.

Response:

```json
{
  "attachment": { "id": "uuid", "storage_path": "local://attachments/...", "links": [] },
  "ocr_job": { "job_id": "uuid", "status": "queued" }
}
```

Important v0.1 storage note:

- The API writes the file to `ATTACHMENT_STORAGE_DIR`, default `storage/attachments`.
- Railway workers do not share a durable filesystem with the API service, so text-like uploads also store the first 200KB of decoded text in `attachment.metadata_json.uploaded_text_content`.
- The OCR skeleton reads text in this priority order: job `mock_extracted_text`, attachment `mock_extracted_text`, uploaded text metadata, then local file path if available.
- Binary files are persisted as attachment records but still need a real object storage + OCR provider before they can be parsed across services.
- Max upload size is controlled by `ATTACHMENT_MAX_UPLOAD_BYTES`, default 25MB.
