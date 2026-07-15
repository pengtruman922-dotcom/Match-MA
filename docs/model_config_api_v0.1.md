# Model Config API v0.1

This document records the backend API for the future Settings -> Model and Prompt management page.

## Design rules

- One `model_provider_config` row represents one callable model configuration: display name, API model name, Base URL, and secret settings. The legacy table name is retained for compatibility.
- A model key can use a Railway environment reference or encrypted database storage. Direct keys are encrypted and are never returned by an API.
- `model_node_config` stores node-level bindings and optional sampling settings. The model name is synchronized from the selected model configuration.
- `prompt_template` stores prompt versions only for prompt-capable nodes.
- Prompt editing is enabled only for `node_type in ('llm', 'parser', 'research')`.
- Prompt editing is disabled for `embedding`, `rerank`, and `ocr` nodes.

## Capability endpoint

`GET /api/v1/model-config/capabilities`

Returns allowed provider types, auth types, output modes, template engines, and per-node-type edit capabilities.

## Settings page aggregate

`GET /api/v1/model-config/settings-page`

This is the recommended entry for the frontend Settings -> Model and Prompt page. It returns one payload with:

- `capabilities`: provider/node/prompt capability metadata.
- `providers`: model configs; includes a safe `key_display`, never raw keys or ciphertext.
- `nodes`: enriched node configs with prompt edit flags, test support, queue name, prompt versions, default prompt, latest test summary, and UI hints.
- `prompts`: flat prompt list.
- `prompts_by_node_name`: prompt versions grouped by node name.
- `node_test_records`: recent worker test jobs grouped by node id.
- `overview`: provider/node/prompt/test counts and node type counts.
- `quick_actions`: suggested frontend actions for creating providers/nodes and filtering failed tests.

Query parameters:

- `include_inactive`: default `true`; settings page should show inactive records so admins can reactivate or inspect them.
- `tests_per_node`: default `3`, max `10`; set to `0` to skip recent test records.

## Model endpoints

- `GET /api/v1/model-config/models`
- `POST /api/v1/model-config/models`
- `GET /api/v1/model-config/models/{model_id}`
- `PATCH /api/v1/model-config/models/{model_id}`
- `DELETE /api/v1/model-config/models/{model_id}`
- `POST /api/v1/model-config/models/{model_id}/test`

The legacy `/providers` paths remain aliases. `DELETE` deactivates the model, rejects models bound to active business nodes, and always keeps at least one active model.

Direct-key mode requires the same valid Fernet `MODEL_SECRET_ENCRYPTION_KEY` on the API and LLM worker services. Environment-reference mode does not require this variable.

## Legacy provider aliases

- `GET /api/v1/model-config/providers`
- `POST /api/v1/model-config/providers`
- `GET /api/v1/model-config/providers/{provider_id}`
- `PATCH /api/v1/model-config/providers/{provider_id}`
- `DELETE /api/v1/model-config/providers/{provider_id}`

These endpoints behave the same as `/models` and remain for existing integrations.

## Node endpoints

- `GET /api/v1/model-config/nodes`
- `POST /api/v1/model-config/nodes`
- `GET /api/v1/model-config/nodes/{node_id}`
- `POST /api/v1/model-config/nodes/{node_id}/test`
- `POST /api/v1/model-config/nodes/{node_id}/test-jobs`
- `GET /api/v1/model-config/nodes/{node_id}/test-jobs`
- `GET /api/v1/model-config/node-test-jobs/{job_id}`
- `PATCH /api/v1/model-config/nodes/{node_id}`
- `DELETE /api/v1/model-config/nodes/{node_id}`

Each node response includes `prompt_editable` so the frontend can decide whether to show the prompt editor.
The capability endpoint also includes `test_supported` so the frontend can decide whether to show a "test node" action.

Current important LLM nodes:

- `business_update_extractor`: LLM node, prompt editable.
- `seller_target_parser`: LLM node, prompt editable.
- `seller_target_update_parser`: LLM node, prompt editable.
- `buyer_intent_parser`: LLM node, prompt editable.
- `buyer_intent_update_parser`: LLM node, prompt editable.
- `recommendation_deep_eval`: LLM node, prompt editable.
- `recommendation_report_writer`: LLM node, prompt editable.

The generic embedding and rerank recommendation nodes are retired. Recommendation now uses SQL filtering, Python scoring, and LLM deep evaluation.

`POST /nodes/{node_id}/test` runs a lightweight synchronous connectivity test in the API service and writes an `ai_trace` row with `metadata_json.source = model_config_node_test`.

`POST /nodes/{node_id}/test-jobs` is the production-preferred test path. It creates a `model_node_test` background job and routes it to the right worker queue:

- LLM / parser / research -> `llm`
- Embedding -> `embedding`
- Rerank -> `rerank`
- OCR -> `ocr`

- LLM / parser / research nodes call the chat endpoint with the provided `messages` or `input_text`.
- Embedding nodes call the embedding endpoint and return dimension plus a short vector preview.
- Rerank nodes call the rerank endpoint and return sorted relevance results.
- OCR node tests route through the `ocr` worker. v0.1 records a skipped trace for direct node tests because real OCR execution is not implemented yet.
- Raw API keys are accepted only by model create/update requests in direct-key mode. They are encrypted before commit and never returned. Model connectivity tests run through `POST /models/{model_id}/test`; node-level test controls are no longer exposed in the Settings UI.

For Settings UI, prefer these model-config scoped record endpoints:

- `GET /nodes/{node_id}/test-jobs`: recent tests for one node.
- `GET /node-test-jobs/{job_id}`: one test record with job summary and traces.

Each record includes `job_status`, `queue_name`, `node_name`, `node_type`, `provider_name`, `model_name`, `latency_ms`, `output_json`, `error_code`, `error_message`, `latest_trace`, and `traces`.

## Prompt endpoints

- `GET /api/v1/model-config/prompts`
- `POST /api/v1/model-config/prompts`
- `GET /api/v1/model-config/prompts/{prompt_id}`
- `PATCH /api/v1/model-config/prompts/{prompt_id}`
- `DELETE /api/v1/model-config/prompts/{prompt_id}`

Creating or updating a prompt for `embedding`, `rerank`, or `ocr` nodes is rejected when that node exists as the default node.

## Security note

The frontend may collect a direct key only in a password input during model create/update. It must never prefill or display that value again. API responses expose only `secret_configured` and `key_display`; they never expose raw keys or encrypted ciphertext.

## Default prompt versions

Current default Prompt baseline:

- `business_update_extractor`: `v0.3.0`, JSON action extraction for business updates.
- `buyer_intent_parser`: `v0.2.0`, JSON field extraction for buyer intent parsing.
- `seller_target_parser`: `v0.1.0`, JSON field extraction for seller target parsing.
- `recommendation_report_writer`: `v0.1.0`, Markdown report writing.

`buyer_intent_parser` is an LLM node with editable prompt. It expects `raw_requirement_text` and `buyer_profile_json`, and returns a top-level `fields` object. The worker auto-applies supported fields to `buyer_intent` and records field-level logs.


`seller_target_parser` is an LLM node with editable prompt. It expects `raw_target_text` and `target_context_json`, returns a top-level `fields` object, auto-applies supported fields to `seller_target`, records field-level logs, and triggers seller search_doc / embedding rebuild.

`ocr_attachment_parser` is an OCR node with no prompt editor. It is used by `attachment_ocr_parse` jobs and can later be pointed to a real OCR/document parser provider without changing the attachment status API.
