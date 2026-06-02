# Recommendation API v0.1

This document records the first backend API surface for the recommendation workflow.

## Scope

- Candidate generation remains `rule_sql_embedding_v0.2`: structured rule recall plus embedding similarity when both sides have search documents.
- LLM rerank and LLM report writing are not enabled yet.
- Selected recommendation items are persisted and synchronized to `buyer_seller_relation` / `relation_event`.
- Recommendation reports are generated as a deterministic Markdown skeleton first; later versions can replace this with `recommendation_report_writer`.

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

Use these for frontend session replay and recommendation chat history. The bundle endpoint returns session, messages, selected items, reports, and debug counters in one response.

### Selected items

- `POST /api/v1/recommendations/sessions/{session_id}/selected-items`
- `GET /api/v1/recommendations/sessions/{session_id}/selected-items`
- `GET /api/v1/recommendations/selected-items`
- `POST /api/v1/recommendations/selected-items/{selected_item_id}/cancel`

Selecting the same active buyer-intent / seller-target pair within the same session is idempotent and returns the existing active selected item.

### Reports

- `POST /api/v1/recommendations/sessions/{session_id}/reports`
- `GET /api/v1/recommendations/sessions/{session_id}/reports`
- `GET /api/v1/recommendations/reports/{report_id}`

Report v0 uses selected items to create a Markdown report and inserts it as an assistant message in the session history.

## Next Backlog

- Add LLM reranker node and prompt.
- Add LLM report writer job that updates `recommendation_report` from `generating` to `generated`.
- Add frontend session drawer/history and report preview/download.
