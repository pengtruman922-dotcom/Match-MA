# Model Config API v0.1

This document records the backend API for the future Settings -> Model and Prompt management page.

## Design rules

- `model_provider_config` stores provider URL and key reference. It stores `api_key_secret_ref`, not the secret value.
- `model_node_config` stores node-level model settings: node type, provider, model name, timeout, output mode, and activation/default flags.
- `prompt_template` stores prompt versions only for prompt-capable nodes.
- Prompt editing is enabled only for `node_type in ('llm', 'parser', 'research')`.
- Prompt editing is disabled for `embedding`, `rerank`, and `ocr` nodes.

## Capability endpoint

`GET /api/v1/model-config/capabilities`

Returns allowed provider types, auth types, output modes, template engines, and per-node-type edit capabilities.

## Provider endpoints

- `GET /api/v1/model-config/providers`
- `POST /api/v1/model-config/providers`
- `GET /api/v1/model-config/providers/{provider_id}`
- `PATCH /api/v1/model-config/providers/{provider_id}`
- `DELETE /api/v1/model-config/providers/{provider_id}`

`DELETE` deactivates the provider instead of physically deleting it.

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

Current important nodes:

- `business_update_extractor`: LLM node, prompt editable.
- `recommendation_report_writer`: LLM node, prompt editable.
- `recommendation_reranker`: rerank node, prompt not editable, model `qwen3-rerank`.
- `embedding_seller_doc`: embedding node, prompt not editable.
- `embedding_buyer_intent`: embedding node, prompt not editable.

`POST /nodes/{node_id}/test` runs a lightweight synchronous connectivity test in the API service and writes an `ai_trace` row with `metadata_json.source = model_config_node_test`.

`POST /nodes/{node_id}/test-jobs` is the production-preferred test path. It creates a `model_node_test` background job and routes it to the right worker queue:

- LLM / parser / research -> `llm`
- Embedding -> `embedding`
- Rerank -> `rerank`
- OCR -> `ocr`

- LLM / parser / research nodes call the chat endpoint with the provided `messages` or `input_text`.
- Embedding nodes call the embedding endpoint and return dimension plus a short vector preview.
- Rerank nodes call the rerank endpoint and return sorted relevance results.
- OCR nodes return `skipped` in v0.1 because OCR execution is not implemented yet.
- Raw API keys are never accepted or returned; tests use `api_key_secret_ref` to read server-side environment variables. Because production keys are configured on worker services, frontend should call `test-jobs`, then poll `/api/v1/background-jobs/{job_id}` and `/api/v1/background-jobs/{job_id}/traces`.

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

The frontend must never collect or display raw provider keys in this version. Users should configure real keys in Railway variables and use `api_key_secret_ref` such as `ALIYUN_API_KEY` in this API.
