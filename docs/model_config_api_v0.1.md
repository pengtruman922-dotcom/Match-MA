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
- `PATCH /api/v1/model-config/nodes/{node_id}`
- `DELETE /api/v1/model-config/nodes/{node_id}`

Each node response includes `prompt_editable` so the frontend can decide whether to show the prompt editor.

Current important nodes:

- `business_update_extractor`: LLM node, prompt editable.
- `recommendation_report_writer`: LLM node, prompt editable.
- `recommendation_reranker`: rerank node, prompt not editable, model `qwen3-rerank`.
- `embedding_seller_doc`: embedding node, prompt not editable.
- `embedding_buyer_intent`: embedding node, prompt not editable.

## Prompt endpoints

- `GET /api/v1/model-config/prompts`
- `POST /api/v1/model-config/prompts`
- `GET /api/v1/model-config/prompts/{prompt_id}`
- `PATCH /api/v1/model-config/prompts/{prompt_id}`
- `DELETE /api/v1/model-config/prompts/{prompt_id}`

Creating or updating a prompt for `embedding`, `rerank`, or `ocr` nodes is rejected when that node exists as the default node.

## Security note

The frontend must never collect or display raw provider keys in this version. Users should configure real keys in Railway variables and use `api_key_secret_ref` such as `ALIYUN_API_KEY` in this API.
