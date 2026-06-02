
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.embedding_client import EmbeddingCallError, call_openai_compatible_embedding
from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.rerank_client import RerankCallError, call_dashscope_compatible_rerank
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/model-config", tags=["model-config"])

PROVIDER_TYPES = {"openai_compatible", "dashscope", "deepseek", "azure_openai", "ocr", "embedding", "custom"}
AUTH_TYPES = {"none", "bearer", "api_key_header", "custom"}
NODE_TYPES = {"llm", "embedding", "ocr", "rerank", "research", "parser"}
OUTPUT_MODES = {"text", "json", "embedding", "file", "mixed"}
TEMPLATE_ENGINES = {"jinja", "plain", "custom"}
PROMPT_EDITABLE_NODE_TYPES = {"llm", "parser", "research"}
TESTABLE_NODE_TYPES = {"llm", "parser", "research", "embedding", "rerank"}
CHAT_NODE_TYPES = {"llm", "parser", "research"}


class ProviderCreate(BaseModel):
    provider_name: str = Field(min_length=1, max_length=120)
    provider_type: str = Field(default="custom")
    base_url: str | None = None
    api_key_secret_ref: str | None = None
    auth_type: str = Field(default="bearer")
    extra_headers_json: dict[str, Any] = Field(default_factory=dict)
    extra_config_json: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    is_default: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class ProviderUpdate(BaseModel):
    provider_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_type: str | None = None
    base_url: str | None = None
    api_key_secret_ref: str | None = None
    auth_type: str | None = None
    extra_headers_json: dict[str, Any] | None = None
    extra_config_json: dict[str, Any] | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    metadata_json: dict[str, Any] | None = None


class ProviderOut(BaseModel):
    id: UUID
    provider_name: str
    provider_type: str
    base_url: str | None
    api_key_secret_ref: str | None
    auth_type: str
    extra_headers_json: dict[str, Any]
    extra_config_json: dict[str, Any]
    is_active: bool
    is_default: bool
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class NodeCreate(BaseModel):
    node_name: str = Field(min_length=1, max_length=120)
    node_type: str
    provider_config_id: UUID
    model_name: str = Field(min_length=1, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)
    response_format: str | None = None
    output_mode: str = Field(default="text")
    embedding_dimension: int | None = Field(default=None, ge=1)
    is_active: bool = True
    is_default: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    node_name: str | None = Field(default=None, min_length=1, max_length=120)
    node_type: str | None = None
    provider_config_id: UUID | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=160)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    response_format: str | None = None
    output_mode: str | None = None
    embedding_dimension: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    is_default: bool | None = None
    metadata_json: dict[str, Any] | None = None


class NodeOut(BaseModel):
    id: UUID
    node_name: str
    node_type: str
    provider_config_id: UUID
    provider_name: str | None
    provider_type: str | None
    base_url: str | None
    api_key_secret_ref: str | None
    model_name: str
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    timeout_seconds: int
    response_format: str | None
    output_mode: str
    embedding_dimension: int | None
    is_active: bool
    is_default: bool
    prompt_editable: bool
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class PromptCreate(BaseModel):
    node_name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    output_schema_json: dict[str, Any] = Field(default_factory=dict)
    few_shot_examples_json: list[Any] = Field(default_factory=list)
    template_engine: str = Field(default="jinja")
    variables_json: list[Any] = Field(default_factory=list)
    is_active: bool = True
    is_default: bool = False
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class PromptUpdate(BaseModel):
    version: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    output_schema_json: dict[str, Any] | None = None
    few_shot_examples_json: list[Any] | None = None
    template_engine: str | None = None
    variables_json: list[Any] | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    metadata_json: dict[str, Any] | None = None


class PromptOut(BaseModel):
    id: UUID
    node_name: str
    node_type: str | None = None
    version: str
    name: str | None
    description: str | None
    system_prompt: str | None
    user_prompt_template: str | None
    output_schema_json: dict[str, Any]
    few_shot_examples_json: list[Any]
    template_engine: str
    variables_json: list[Any]
    is_active: bool
    is_default: bool
    prompt_editable: bool
    created_at: str
    updated_at: str
    metadata_json: dict[str, Any]


class NodeTestCreate(BaseModel):
    input_text: str | None = Field(default=None, max_length=4000)
    messages: list[dict[str, str]] | None = None
    query: str | None = Field(default=None, max_length=2000)
    documents: list[str] | None = None
    top_n: int | None = Field(default=None, ge=1, le=20)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


class NodeTestOut(BaseModel):
    node_id: UUID
    node_name: str
    node_type: str
    provider_name: str | None
    model_name: str
    status: str
    trace_id: UUID | None
    latency_ms: int | None
    output_json: dict[str, Any]
    raw_output_text: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class NodeTestJobOut(BaseModel):
    job_id: UUID
    job_status: str
    queue_name: str
    node_id: UUID
    node_name: str
    node_type: str


@router.get("/capabilities")
def get_model_config_capabilities() -> dict[str, Any]:
    return {
        "node_types": {
            node_type: {
                "prompt_editable": node_type in PROMPT_EDITABLE_NODE_TYPES,
                "provider_editable": True,
                "model_editable": True,
                "key_ref_editable": True,
                "test_supported": node_type in TESTABLE_NODE_TYPES,
            }
            for node_type in sorted(NODE_TYPES)
        },
        "prompt_editable_node_types": sorted(PROMPT_EDITABLE_NODE_TYPES),
        "testable_node_types": sorted(TESTABLE_NODE_TYPES),
        "provider_types": sorted(PROVIDER_TYPES),
        "auth_types": sorted(AUTH_TYPES),
        "output_modes": sorted(OUTPUT_MODES),
        "template_engines": sorted(TEMPLATE_ENGINES),
        "security_note": "api_key_secret_ref stores the environment variable name, not the secret value.",
    }


@router.get("/providers", response_model=list[ProviderOut])
def list_providers(
    db: Session = Depends(get_db),
    include_inactive: bool = Query(default=False),
) -> list[dict[str, Any]]:
    where = ["team_id = :team_id", "workspace_id = :workspace_id"]
    if not include_inactive:
        where.append("is_active = true")
    rows = db.execute(
        text(
            f"""
            select {_provider_select_columns()}
            from model_provider_config
            where {' and '.join(where)}
            order by is_default desc, provider_name asc
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_choice("provider_type", payload.provider_type, PROVIDER_TYPES)
    _validate_choice("auth_type", payload.auth_type, AUTH_TYPES)
    if payload.is_default:
        _clear_default_provider(db)
    row = db.execute(
        _provider_returning_statement(
            """
            insert into model_provider_config (
              team_id, workspace_id, provider_name, provider_type, base_url,
              api_key_secret_ref, auth_type, extra_headers_json, extra_config_json,
              is_active, is_default, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :provider_name, :provider_type, :base_url,
              :api_key_secret_ref, :auth_type, :extra_headers_json, :extra_config_json,
              :is_active, :is_default, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("extra_headers_json", type_=JSONB),
            bindparam("extra_config_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            **payload.model_dump(),
            "created_by": DEFAULT_ADMIN_USER_ID,
        },
    ).mappings().one()
    db.commit()
    return dict(row)


@router.get("/providers/{provider_id}", response_model=ProviderOut)
def get_provider(provider_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_provider_or_404(db, provider_id)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: UUID, payload: ProviderUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _get_provider_or_404(db, provider_id)
    data = payload.model_dump(exclude_unset=True)
    if "provider_type" in data:
        _validate_choice("provider_type", data["provider_type"], PROVIDER_TYPES)
    if "auth_type" in data:
        _validate_choice("auth_type", data["auth_type"], AUTH_TYPES)
    if data.get("is_default") is True:
        _clear_default_provider(db)
    row = _update_row(
        db,
        table_name="model_provider_config",
        row_id=provider_id,
        data=data,
        select_columns=_provider_select_columns(),
        json_fields={"extra_headers_json", "extra_config_json", "metadata_json"},
    )
    db.commit()
    return row


@router.delete("/providers/{provider_id}", response_model=ProviderOut)
def deactivate_provider(provider_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    _get_provider_or_404(db, provider_id)
    row = _update_row(
        db,
        table_name="model_provider_config",
        row_id=provider_id,
        data={"is_active": False, "is_default": False},
        select_columns=_provider_select_columns(),
        json_fields=set(),
    )
    db.commit()
    return row


@router.get("/nodes", response_model=list[NodeOut])
def list_nodes(
    db: Session = Depends(get_db),
    node_type: str | None = None,
    include_inactive: bool = Query(default=False),
) -> list[dict[str, Any]]:
    where = ["node.team_id = :team_id", "node.workspace_id = :workspace_id"]
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if node_type:
        _validate_choice("node_type", node_type, NODE_TYPES)
        where.append("node.node_type = :node_type")
        params["node_type"] = node_type
    if not include_inactive:
        where.append("node.is_active = true")
    rows = db.execute(
        text(
            f"""
            select {_node_select_columns()}
            from model_node_config node
            left join model_provider_config provider on provider.id = node.provider_config_id
            where {' and '.join(where)}
            order by node.node_name asc, node.is_default desc, node.created_at desc
            """
        ),
        params,
    ).mappings().all()
    return [_with_prompt_capability(row) for row in rows]


@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(payload: NodeCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_node_payload(payload.model_dump())
    _get_provider_or_404(db, payload.provider_config_id)
    if payload.is_default:
        _clear_default_node(db, payload.node_name)
    row = db.execute(
        _node_returning_statement(
            """
            insert into model_node_config (
              team_id, workspace_id, node_name, node_type, provider_config_id,
              model_name, temperature, top_p, max_tokens, timeout_seconds,
              response_format, output_mode, embedding_dimension,
              is_active, is_default, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :node_name, :node_type, :provider_config_id,
              :model_name, :temperature, :top_p, :max_tokens, :timeout_seconds,
              :response_format, :output_mode, :embedding_dimension,
              :is_active, :is_default, :created_by, :metadata_json
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, **payload.model_dump(), "created_by": DEFAULT_ADMIN_USER_ID},
    ).mappings().one()
    db.commit()
    return _with_prompt_capability(row)


@router.get("/nodes/{node_id}", response_model=NodeOut)
def get_node(node_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_node_or_404(db, node_id)


@router.post("/nodes/{node_id}/test", response_model=NodeTestOut)
def test_node(node_id: UUID, payload: NodeTestCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    node = _get_node_or_404(db, node_id)
    result = _run_node_test(db, node=node, payload=payload)
    db.commit()
    return result


@router.post("/nodes/{node_id}/test-jobs", response_model=NodeTestJobOut, status_code=status.HTTP_201_CREATED)
def create_node_test_job(
    node_id: UUID,
    payload: NodeTestCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    node = _get_node_or_404(db, node_id)
    queue_name = _queue_name_for_node_test(str(node["node_type"]))
    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              max_attempts, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, 'model_node_test', 90, :queue_name,
              'model_node_config', :node_id, :idempotency_key, :payload_json,
              1, :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "queue_name": queue_name,
            "node_id": node_id,
            "idempotency_key": f"model_node_test:{node_id}:{uuid4()}",
            "payload_json": {
                **payload.model_dump(exclude_none=True),
                "node_id": str(node_id),
                "node_name": node["node_name"],
                "node_type": node["node_type"],
            },
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {
                "source": "model_config_node_test_job_api",
                "node_name": node["node_name"],
                "node_type": node["node_type"],
            },
        },
    ).mappings().one()
    db.commit()
    return {
        "job_id": row["id"],
        "job_status": "queued",
        "queue_name": queue_name,
        "node_id": node_id,
        "node_name": node["node_name"],
        "node_type": node["node_type"],
    }


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: UUID, payload: NodeUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_node_or_404(db, node_id)
    data = payload.model_dump(exclude_unset=True)
    merged = {**current, **data}
    _validate_node_payload(merged)
    if "provider_config_id" in data:
        _get_provider_or_404(db, data["provider_config_id"])
    if data.get("is_default") is True:
        _clear_default_node(db, str(merged["node_name"]))
    row = _update_node_row(db, node_id=node_id, data=data)
    db.commit()
    return row


@router.delete("/nodes/{node_id}", response_model=NodeOut)
def deactivate_node(node_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    _get_node_or_404(db, node_id)
    row = _update_node_row(db, node_id=node_id, data={"is_active": False, "is_default": False})
    db.commit()
    return row


@router.get("/prompts", response_model=list[PromptOut])
def list_prompts(
    db: Session = Depends(get_db),
    node_name: str | None = None,
    include_inactive: bool = Query(default=False),
) -> list[dict[str, Any]]:
    where = ["prompt.team_id = :team_id", "prompt.workspace_id = :workspace_id"]
    params: dict[str, Any] = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    if node_name:
        where.append("prompt.node_name = :node_name")
        params["node_name"] = node_name
    if not include_inactive:
        where.append("prompt.is_active = true")
    rows = db.execute(
        text(
            f"""
            select {_prompt_select_columns()}
            from prompt_template prompt
            left join model_node_config node
              on node.team_id = prompt.team_id
             and node.workspace_id = prompt.workspace_id
             and node.node_name = prompt.node_name
             and node.is_default = true
            where {' and '.join(where)}
            order by prompt.node_name asc, prompt.is_default desc, prompt.created_at desc
            """
        ),
        params,
    ).mappings().all()
    return [_with_prompt_capability(row) for row in rows]


@router.post("/prompts", response_model=PromptOut, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    _validate_prompt_payload(db, payload.node_name, payload.template_engine)
    if payload.is_default:
        _clear_default_prompt(db, payload.node_name)
    row = db.execute(
        _prompt_returning_statement(
            """
            insert into prompt_template (
              team_id, workspace_id, node_name, version, name, description,
              system_prompt, user_prompt_template, output_schema_json,
              few_shot_examples_json, template_engine, variables_json,
              is_active, is_default, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :node_name, :version, :name, :description,
              :system_prompt, :user_prompt_template, :output_schema_json,
              :few_shot_examples_json, :template_engine, :variables_json,
              :is_active, :is_default, :created_by, :metadata_json
            )
            """
        ).bindparams(
            bindparam("output_schema_json", type_=JSONB),
            bindparam("few_shot_examples_json", type_=JSONB),
            bindparam("variables_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, **payload.model_dump(), "created_by": DEFAULT_ADMIN_USER_ID},
    ).mappings().one()
    db.commit()
    return _with_prompt_capability(row)


@router.get("/prompts/{prompt_id}", response_model=PromptOut)
def get_prompt(prompt_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _get_prompt_or_404(db, prompt_id)


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: UUID, payload: PromptUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    current = _get_prompt_or_404(db, prompt_id)
    data = payload.model_dump(exclude_unset=True)
    if "template_engine" in data:
        _validate_choice("template_engine", data["template_engine"], TEMPLATE_ENGINES)
    _validate_prompt_payload(db, current["node_name"], data.get("template_engine") or current["template_engine"])
    if data.get("is_default") is True:
        _clear_default_prompt(db, str(current["node_name"]))
    row = _update_prompt_row(db, prompt_id=prompt_id, data=data)
    db.commit()
    return row


@router.delete("/prompts/{prompt_id}", response_model=PromptOut)
def deactivate_prompt(prompt_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    _get_prompt_or_404(db, prompt_id)
    row = _update_prompt_row(db, prompt_id=prompt_id, data={"is_active": False, "is_default": False})
    db.commit()
    return row


def _validate_choice(field_name: str, value: str | None, allowed: set[str]) -> None:
    if value is not None and value not in allowed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid {field_name}: {value}")


def _validate_node_payload(data: dict[str, Any]) -> None:
    _validate_choice("node_type", data.get("node_type"), NODE_TYPES)
    _validate_choice("output_mode", data.get("output_mode"), OUTPUT_MODES)
    if data.get("node_type") == "embedding" and data.get("embedding_dimension") is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="embedding_dimension is required for embedding nodes.")


def _validate_prompt_payload(db: Session, node_name: str, template_engine: str | None) -> None:
    _validate_choice("template_engine", template_engine, TEMPLATE_ENGINES)
    node = _get_default_node_by_name(db, node_name)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Default model node not found for prompt.")
    if node["node_type"] not in PROMPT_EDITABLE_NODE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Prompt editing is disabled for node_type={node['node_type']}.")


def _queue_name_for_node_test(node_type: str) -> str:
    if node_type in CHAT_NODE_TYPES:
        return "llm"
    if node_type == "embedding":
        return "embedding"
    if node_type == "rerank":
        return "rerank"
    if node_type == "ocr":
        return "ocr"
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Node test job is not supported for node_type={node_type}.",
    )


def _clear_default_provider(db: Session) -> None:
    db.execute(text("update model_provider_config set is_default = false where team_id = :team_id and workspace_id = :workspace_id"), {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID})


def _clear_default_node(db: Session, node_name: str) -> None:
    db.execute(text("update model_node_config set is_default = false where team_id = :team_id and workspace_id = :workspace_id and node_name = :node_name"), {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "node_name": node_name})


def _clear_default_prompt(db: Session, node_name: str) -> None:
    db.execute(text("update prompt_template set is_default = false where team_id = :team_id and workspace_id = :workspace_id and node_name = :node_name"), {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "node_name": node_name})


def _run_node_test(db: Session, *, node: dict[str, Any], payload: NodeTestCreate) -> dict[str, Any]:
    node_type = str(node["node_type"])
    if node_type == "ocr":
        return _skipped_node_test(node, reason="OCR node test is not implemented in v0.1.")
    if node_type not in TESTABLE_NODE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Node test is not supported for node_type={node_type}.",
        )
    if not node.get("is_active"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive nodes cannot be tested.")
    if not node.get("base_url"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provider base_url is required.")

    if node_type in CHAT_NODE_TYPES:
        return _run_chat_node_test(db, node=node, payload=payload)
    if node_type == "embedding":
        return _run_embedding_node_test(db, node=node, payload=payload)
    if node_type == "rerank":
        return _run_rerank_node_test(db, node=node, payload=payload)

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported node_type={node_type}.")


def _run_chat_node_test(
    db: Session,
    *,
    node: dict[str, Any],
    payload: NodeTestCreate,
) -> dict[str, Any]:
    trace_type = "llm" if node["node_type"] == "llm" else str(node["node_type"])
    messages = payload.messages or _default_chat_test_messages(node, payload.input_text)
    input_json = {
        "node_id": str(node["id"]),
        "node_name": node["node_name"],
        "node_type": node["node_type"],
        "messages": _redact_message_text(messages),
    }
    try:
        result = call_openai_compatible_chat(
            base_url=str(node["base_url"]),
            api_key_secret_ref=node.get("api_key_secret_ref"),
            model_name=str(node["model_name"]),
            messages=messages,
            temperature=node.get("temperature"),
            top_p=node.get("top_p"),
            max_tokens=int(node["max_tokens"]) if node.get("max_tokens") is not None else 64,
            timeout_seconds=payload.timeout_seconds or int(node["timeout_seconds"]),
            response_format=node.get("response_format"),
        )
    except LlmCallError as exc:
        trace_id = _insert_node_test_trace(
            db,
            node=node,
            trace_type=trace_type,
            status_value="failed",
            input_json=input_json,
            prompt_messages_json=messages,
            raw_output_text=None,
            parsed_output_json=None,
            latency_ms=None,
            error_code="llm_test_failed",
            error_message=str(exc),
        )
        return _node_test_response(
            node,
            status_value="failed",
            trace_id=trace_id,
            latency_ms=None,
            output_json={},
            error_code="llm_test_failed",
            error_message=str(exc),
        )

    output_json = {
        "parsed_output_json": result.parsed_output_json,
        "raw_output_preview": result.raw_output_text[:1000],
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
    }
    trace_id = _insert_node_test_trace(
        db,
        node=node,
        trace_type=trace_type,
        status_value="succeeded",
        input_json=input_json,
        prompt_messages_json=messages,
        raw_output_text=result.raw_output_text,
        parsed_output_json=result.parsed_output_json,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
    )
    return _node_test_response(
        node,
        status_value="succeeded",
        trace_id=trace_id,
        latency_ms=result.latency_ms,
        output_json=output_json,
        raw_output_text=result.raw_output_text,
    )


def _run_embedding_node_test(
    db: Session,
    *,
    node: dict[str, Any],
    payload: NodeTestCreate,
) -> dict[str, Any]:
    input_text = payload.input_text or "Match-MA embedding connectivity test."
    input_json = {
        "node_id": str(node["id"]),
        "node_name": node["node_name"],
        "node_type": node["node_type"],
        "input_preview": input_text[:500],
    }
    try:
        result = call_openai_compatible_embedding(
            base_url=str(node["base_url"]),
            api_key_secret_ref=node.get("api_key_secret_ref"),
            model_name=str(node["model_name"]),
            input_text=input_text,
            dimensions=node.get("embedding_dimension"),
            timeout_seconds=payload.timeout_seconds or int(node["timeout_seconds"]),
        )
    except EmbeddingCallError as exc:
        trace_id = _insert_node_test_trace(
            db,
            node=node,
            trace_type="embedding",
            status_value="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=None,
            error_code="embedding_test_failed",
            error_message=str(exc),
        )
        return _node_test_response(
            node,
            status_value="failed",
            trace_id=trace_id,
            latency_ms=None,
            output_json={},
            error_code="embedding_test_failed",
            error_message=str(exc),
        )

    output_json = {
        "embedding_dimension": len(result.embedding),
        "embedding_preview": result.embedding[:8],
        "prompt_tokens": result.prompt_tokens,
        "total_tokens": result.total_tokens,
    }
    trace_id = _insert_node_test_trace(
        db,
        node=node,
        trace_type="embedding",
        status_value="succeeded",
        input_json=input_json,
        parsed_output_json=output_json,
        latency_ms=result.latency_ms,
        prompt_tokens=result.prompt_tokens,
        total_tokens=result.total_tokens,
    )
    return _node_test_response(
        node,
        status_value="succeeded",
        trace_id=trace_id,
        latency_ms=result.latency_ms,
        output_json=output_json,
    )


def _run_rerank_node_test(
    db: Session,
    *,
    node: dict[str, Any],
    payload: NodeTestCreate,
) -> dict[str, Any]:
    query = payload.query or payload.input_text or "Which target best matches healthcare growth capital?"
    documents = payload.documents or [
        "Healthcare target with stable net profit and consolidation potential.",
        "Consumer retail business with limited strategic fit.",
    ]
    input_json = {
        "node_id": str(node["id"]),
        "node_name": node["node_name"],
        "node_type": node["node_type"],
        "query_preview": query[:500],
        "document_count": len(documents),
        "document_previews": [document[:300] for document in documents[:5]],
    }
    try:
        result = call_dashscope_compatible_rerank(
            base_url=str(node["base_url"]),
            api_key_secret_ref=node.get("api_key_secret_ref"),
            model_name=str(node["model_name"]),
            query=query,
            documents=documents,
            top_n=payload.top_n or min(len(documents), 5),
            instruct="Connectivity test for Match-MA rerank node.",
            timeout_seconds=payload.timeout_seconds or int(node["timeout_seconds"]),
        )
    except RerankCallError as exc:
        trace_id = _insert_node_test_trace(
            db,
            node=node,
            trace_type="rerank",
            status_value="failed",
            input_json=input_json,
            parsed_output_json=None,
            latency_ms=None,
            error_code="rerank_test_failed",
            error_message=str(exc),
        )
        return _node_test_response(
            node,
            status_value="failed",
            trace_id=trace_id,
            latency_ms=None,
            output_json={},
            error_code="rerank_test_failed",
            error_message=str(exc),
        )

    output_json = {
        "model": result.model_name,
        "results": [
            {"index": item.index, "relevance_score": item.relevance_score}
            for item in result.results
        ],
        "total_tokens": result.total_tokens,
    }
    trace_id = _insert_node_test_trace(
        db,
        node=node,
        trace_type="rerank",
        status_value="succeeded",
        input_json=input_json,
        parsed_output_json=output_json,
        latency_ms=result.latency_ms,
        total_tokens=result.total_tokens,
    )
    return _node_test_response(
        node,
        status_value="succeeded",
        trace_id=trace_id,
        latency_ms=result.latency_ms,
        output_json=output_json,
    )


def _insert_node_test_trace(
    db: Session,
    *,
    node: dict[str, Any],
    trace_type: str,
    status_value: str,
    input_json: dict[str, Any],
    prompt_messages_json: list[dict[str, str]] | None = None,
    raw_output_text: str | None = None,
    parsed_output_json: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> UUID:
    row = db.execute(
        text(
            """
            insert into ai_trace (
              team_id, workspace_id, trace_type, node_name,
              provider_config_id, node_config_id, provider_name, model_name,
              status, input_json, prompt_messages_json, raw_output_text,
              parsed_output_json, schema_validation_json,
              error_code, error_message, latency_ms, prompt_tokens,
              completion_tokens, total_tokens, finished_at, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :trace_type, :node_name,
              :provider_config_id, :node_config_id, :provider_name, :model_name,
              :status_value, :input_json, :prompt_messages_json, :raw_output_text,
              :parsed_output_json, :schema_validation_json,
              :error_code, :error_message, :latency_ms, :prompt_tokens,
              :completion_tokens, :total_tokens, now(), :created_by, :metadata_json
            )
            returning id
            """
        ).bindparams(
            bindparam("input_json", type_=JSONB),
            bindparam("prompt_messages_json", type_=JSONB),
            bindparam("parsed_output_json", type_=JSONB),
            bindparam("schema_validation_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "trace_type": trace_type,
            "node_name": node["node_name"],
            "provider_config_id": node.get("provider_config_id"),
            "node_config_id": node["id"],
            "provider_name": node.get("provider_name"),
            "model_name": node["model_name"],
            "status_value": status_value,
            "input_json": input_json,
            "prompt_messages_json": prompt_messages_json or [],
            "raw_output_text": raw_output_text,
            "parsed_output_json": parsed_output_json,
            "schema_validation_json": {"valid": status_value == "succeeded"},
            "error_code": error_code,
            "error_message": error_message,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": "model_config_node_test"},
        },
    ).mappings().one()
    return row["id"]


def _node_test_response(
    node: dict[str, Any],
    *,
    status_value: str,
    trace_id: UUID | None,
    latency_ms: int | None,
    output_json: dict[str, Any],
    raw_output_text: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "node_id": node["id"],
        "node_name": node["node_name"],
        "node_type": node["node_type"],
        "provider_name": node.get("provider_name"),
        "model_name": node["model_name"],
        "status": status_value,
        "trace_id": trace_id,
        "latency_ms": latency_ms,
        "output_json": output_json,
        "raw_output_text": raw_output_text,
        "error_code": error_code,
        "error_message": error_message,
    }


def _skipped_node_test(node: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return _node_test_response(
        node,
        status_value="skipped",
        trace_id=None,
        latency_ms=None,
        output_json={"reason": reason},
    )


def _default_chat_test_messages(node: dict[str, Any], input_text: str | None) -> list[dict[str, str]]:
    if node.get("response_format") == "json_object":
        return [
            {"role": "system", "content": "You are a concise API connectivity tester. Output JSON only."},
            {"role": "user", "content": input_text or 'Return {"status":"ok"}.'},
        ]
    return [
        {"role": "system", "content": "You are a concise API connectivity tester."},
        {"role": "user", "content": input_text or "Return exactly: ok"},
    ]


def _redact_message_text(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role") or ""),
            "content_preview": str(message.get("content") or "")[:300],
        }
        for message in messages
    ]


def _get_provider_or_404(db: Session, provider_id: UUID) -> dict[str, Any]:
    row = db.execute(text(f"select {_provider_select_columns()} from model_provider_config where id = :id and team_id = :team_id and workspace_id = :workspace_id"), {"id": provider_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider config not found.")
    return dict(row)


def _get_node_or_404(db: Session, node_id: UUID) -> dict[str, Any]:
    row = db.execute(text(f"select {_node_select_columns()} from model_node_config node left join model_provider_config provider on provider.id = node.provider_config_id where node.id = :id and node.team_id = :team_id and node.workspace_id = :workspace_id"), {"id": node_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model node config not found.")
    return _with_prompt_capability(row)


def _get_default_node_by_name(db: Session, node_name: str) -> dict[str, Any] | None:
    row = db.execute(text("select id, node_name, node_type from model_node_config where team_id = :team_id and workspace_id = :workspace_id and node_name = :node_name and is_default = true limit 1"), {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "node_name": node_name}).mappings().one_or_none()
    return dict(row) if row else None


def _get_prompt_or_404(db: Session, prompt_id: UUID) -> dict[str, Any]:
    row = db.execute(text(f"select {_prompt_select_columns()} from prompt_template prompt left join model_node_config node on node.team_id = prompt.team_id and node.workspace_id = prompt.workspace_id and node.node_name = prompt.node_name and node.is_default = true where prompt.id = :id and prompt.team_id = :team_id and prompt.workspace_id = :workspace_id"), {"id": prompt_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt template not found.")
    return _with_prompt_capability(row)


def _update_row(db: Session, *, table_name: str, row_id: UUID, data: dict[str, Any], select_columns: str, json_fields: set[str]) -> dict[str, Any]:
    if not data:
        row = db.execute(text(f"select {select_columns} from {table_name} where id = :id and team_id = :team_id and workspace_id = :workspace_id"), {"id": row_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}).mappings().one()
        return dict(row)
    assignments = [f"{field} = :{field}" for field in data]
    assignments.append("updated_at = now()")
    stmt = text(f"update {table_name} set {', '.join(assignments)} where id = :id and team_id = :team_id and workspace_id = :workspace_id returning {select_columns}")
    for field in json_fields.intersection(data):
        stmt = stmt.bindparams(bindparam(field, type_=JSONB))
    params = {"id": row_id, "team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, **data}
    row = db.execute(stmt, params).mappings().one()
    return dict(row)


def _update_node_row(db: Session, *, node_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    row = _update_row(db, table_name="model_node_config", row_id=node_id, data=data, select_columns="*", json_fields={"metadata_json"})
    return _get_node_or_404(db, row["id"])


def _update_prompt_row(db: Session, *, prompt_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
    row = _update_row(db, table_name="prompt_template", row_id=prompt_id, data=data, select_columns="*", json_fields={"output_schema_json", "few_shot_examples_json", "variables_json", "metadata_json"})
    return _get_prompt_or_404(db, row["id"])


def _with_prompt_capability(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["prompt_editable"] = result.get("node_type") in PROMPT_EDITABLE_NODE_TYPES
    return result


def _provider_select_columns() -> str:
    return """
      id, provider_name, provider_type, base_url, api_key_secret_ref, auth_type,
      extra_headers_json, extra_config_json, is_active, is_default,
      created_at::text as created_at, updated_at::text as updated_at, metadata_json
    """


def _provider_returning_statement(prefix_sql: str):
    return text(f"{prefix_sql} returning {_provider_select_columns()}")


def _node_select_columns() -> str:
    return """
      node.id, node.node_name, node.node_type, node.provider_config_id,
      provider.provider_name, provider.provider_type, provider.base_url, provider.api_key_secret_ref,
      node.model_name, node.temperature, node.top_p, node.max_tokens,
      node.timeout_seconds, node.response_format, node.output_mode,
      node.embedding_dimension, node.is_active, node.is_default,
      node.created_at::text as created_at, node.updated_at::text as updated_at,
      node.metadata_json
    """


def _node_returning_statement(prefix_sql: str):
    return text(
        f"""
        with changed as ({prefix_sql} returning *)
        select {_node_select_columns()}
        from changed node
        left join model_provider_config provider on provider.id = node.provider_config_id
        """
    )


def _prompt_select_columns() -> str:
    return """
      prompt.id, prompt.node_name, node.node_type, prompt.version, prompt.name,
      prompt.description, prompt.system_prompt, prompt.user_prompt_template,
      prompt.output_schema_json, prompt.few_shot_examples_json,
      prompt.template_engine, prompt.variables_json, prompt.is_active,
      prompt.is_default, prompt.created_at::text as created_at,
      prompt.updated_at::text as updated_at, prompt.metadata_json
    """


def _prompt_returning_statement(prefix_sql: str):
    return text(
        f"""
        with changed as ({prefix_sql} returning *)
        select {_prompt_select_columns()}
        from changed prompt
        left join model_node_config node
          on node.team_id = prompt.team_id
         and node.workspace_id = prompt.workspace_id
         and node.node_name = prompt.node_name
         and node.is_default = true
        """
    )
