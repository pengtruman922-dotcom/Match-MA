# Recommendation API v0.1

This document records the first backend API surface for the recommendation workflow.

## Scope

- Candidate generation remains `rule_sql_embedding_v0.2`: structured rule recall plus embedding similarity when both sides have search documents.
- Candidate generation supports asynchronous qwen3-rerank reranking and LLM report writing.
- Selected recommendation items are persisted and synchronized to `buyer_seller_relation` / `relation_event`.
- Recommendation reports support deterministic Markdown generation and asynchronous LLM generation through `recommendation_report_writer`.

## Endpoints

### Candidate generation

`POST /api/v1/recommendations/candidates`

Creates an optional `recommendation_session`, stores user/tool messages, and returns ranked candidates.

### Session history

- `GET /api/v1/recommendations/sessions`
- `GET /api/v1/recommendations/sessions/{session_id}`
- `GET /api/v1/recommendations/sessions/{session_id}/bundle`
- `GET /api/v1/recommendations/sessions/{session_id}/messages`
- `POST /api/v1/recommendations/sessions/{session_id}/messages`

Use these for frontend session replay and recommendation chat history.

The bundle endpoint returns:

- `initial_candidates`: the first rule/embedding candidate list written by candidate generation.
- `reranked_candidates`: the latest async rerank candidate list written by `match-ma-worker-rerank`.
- `latest_candidates`: frontend-ready candidate list; uses `reranked_candidates` when available, otherwise falls back to `initial_candidates`.
- `candidate_source`: `reranked_candidates`, `initial_candidates`, or `none`.
- `rerank_status`: job status, job id, queue name, timestamps, candidate count, and rerank error details.
- `selected_items` plus candidate-level `selected`, `selected_item_id`, and `selected_at`.
- `messages`, `reports`, and debug counters.

Frontend recommendation cards should render `latest_candidates` and poll this bundle until `rerank_status.status` is `succeeded`, `failed`, or `cancelled`.

Each candidate includes frontend-ready card fields:

- `primary_entity_type`, `primary_entity_id`: the entity represented by the card.
- `counterpart_entity_type`, `counterpart_entity_id`: the anchor/counterparty entity for this recommendation.
- `display_title`, `display_subtitle`: direct card title/subtitle.
- `display_meta`, `display_badges`: compact labels for score, level, embedding, rerank, and selection state.
- `score_breakdown`: rule score, embedding similarity/boost, rerank score/boost/model, and final score.
- `card_json`: compact one-object summary for quick rendering.
- `selected`, `selected_item_id`, `selected_at`: active recommendation-list selection state.

### Selected items

- `POST /api/v1/recommendations/sessions/{session_id}/selected-items`
- `GET /api/v1/recommendations/sessions/{session_id}/selected-items`
- `GET /api/v1/recommendations/selected-items`
- `POST /api/v1/recommendations/selected-items/{selected_item_id}/cancel`

Selecting the same active buyer-intent / seller-target pair within the same session is idempotent and returns the existing active selected item.

### Rerank

`POST /api/v1/recommendations/candidates` supports `enable_rerank` with default `true`. The API returns the rule plus embedding ranking immediately and, when a session is created, enqueues `recommendation_rerank` on the `rerank` queue. `match-ma-worker-rerank` consumes this queue and calls `recommendation_reranker` with model `qwen3-rerank`. The initial result is appended to `recommendation_message` as an `initial_candidates` tool message. The reranked result is appended as a `reranked_candidates` tool message and recorded in `ai_trace`.

`POST /api/v1/recommendations/sessions/{session_id}/rerank-jobs` creates a new async rerank job for an existing session. If the request body does not provide `candidates`, the backend uses the session's `initial_candidates`; this is intended for "rerun after model config changed" and "retry failed rerank" flows. The response returns `job_id`, `queue_name = rerank`, `candidate_count`, and candidate source.

Rerank nodes have no prompt template. Future admin settings should edit provider URL, key reference, model name, timeout, active/default flags, and metadata, but should not show prompt editing for `node_type = rerank`.

### Reports

- `POST /api/v1/recommendations/sessions/{session_id}/reports`
- `POST /api/v1/recommendations/sessions/{session_id}/reports/jobs`
- `GET /api/v1/recommendations/sessions/{session_id}/reports`
- `GET /api/v1/recommendations/reports/{report_id}`

Report v0 supports two modes: the synchronous endpoint creates a deterministic Markdown report; the job endpoint creates a `generating` report and queues `recommendation_report_generate` on the `llm` queue. The worker calls `recommendation_report_writer` and falls back to the deterministic template if the LLM call fails.

## Debug Mode

`GET /api/v1/debug/recommendation-sessions/{session_id}`

Returns the session, jobs, traces, messages, selected items, reports, relations, relation events, and debug counters. Use this endpoint in frontend Debug Mode to inspect why a recommendation session produced a given shortlist/report and how selected items were synced to buyer-seller relations.

## Next Backlog

- Add frontend session drawer/history and report preview/download.
