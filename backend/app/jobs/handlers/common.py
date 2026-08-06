from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.prompting import render_template
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.registry.indicators import (
    multi_value_enum_values,
    writable_columns,
    writable_enum_values,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    read_attachment_bytes,
    read_local_text_content,
)
from backend.app.services.json_values import json_safe_dict, json_safe_value

ALLOWED_ACTION_TYPES = {
    "seller_fact_update",
    "buyer_seller_relation_update",
    "buyer_intent_target_exclusion",
    "buyer_intent_update",
    "buyer_level_blacklist_suggestion",
    "internal_note",
    "unresolved_item",
}

ALLOWED_TARGET_ENTITY_TYPES = {
    "seller_target",
    "buyer_party",
    "buyer_intent",
    "buyer_seller_relation",
}

_SKIP_FIELD = object()

MONEY_YUAN_FIELDS = {
    "market_cap_yuan",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "valuation_yuan",
    "asking_price_yuan",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "min_total_profit_yuan",
    "max_valuation_yuan",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
}

_MONEY_UNIT_YI = chr(0x4EBF)

_MONEY_UNIT_WAN = chr(0x4E07)

_MONEY_UNIT_YUAN = chr(0x5143)

_MONEY_RANGE_SEPARATORS = "-~" + chr(0x2013) + chr(0x2014) + chr(0x81F3) + chr(0x5230)

MONEY_UNIT_PATTERN = re.compile(
    "(?<![\\d.])(\\d+(?:,\\d{3})*(?:\\.\\d+)?)"
    f"(?:\\s*(?:[{re.escape(_MONEY_RANGE_SEPARATORS)}])\\s*(\\d+(?:,\\d{{3}})*(?:\\.\\d+)?))?"
    f"\\s*({_MONEY_UNIT_YI}{_MONEY_UNIT_YUAN}|{_MONEY_UNIT_YI}|"
    f"{_MONEY_UNIT_WAN}{_MONEY_UNIT_YUAN}|{_MONEY_UNIT_WAN}|{_MONEY_UNIT_YUAN})"
)

# 派生自指标注册表（唯一事实源）：哪些 seller_target 列允许解析写入。
# lifecycle_status is a named system-fact exception: it is not an information
# page indicator, but explicit sold/off-market evidence may safely stop a deal.
SELLER_TARGET_SYSTEM_FACT_FIELDS = {"lifecycle_status"}
SELLER_TARGET_CHANGE_FIELDS = writable_columns("parse") | SELLER_TARGET_SYSTEM_FACT_FIELDS

SELLER_TARGET_FIELD_ALIASES = {
    "summary": "business_summary",
    "target_summary": "business_summary",
    "business": "business_summary",
    "subject": "target_subject_name",
    "subject_name": "target_subject_name",
    "target_subject": "target_subject_name",
    "target_subject_name": "target_subject_name",
    "owner_company": "target_subject_name",
    "company_name": "target_subject_name",
    "industry": "industry_secondary",
    "location": "location_city",
    "province": "location_province",
    "city": "location_city",
    "district": "location_district",
    "revenue": "current_revenue_yuan",
    "profit": "current_net_profit_yuan",
    "net_profit": "current_net_profit_yuan",
    "valuation": "valuation_yuan",
    "valuation_time": "valuation_date",
    "valuation_date": "valuation_date",
    "asking_price": "asking_price_yuan",
    "asking_price_time": "asking_price_date",
    "asking_price_date": "asking_price_date",
    "price_date": "asking_price_date",
    "pe": "pe_ratio",
    "pe_multiple": "pe_ratio",
}

# 派生自指标注册表（唯一事实源）：哪些 buyer_intent 列允许解析写入。
BUYER_INTENT_CHANGE_FIELDS = writable_columns("parse", "buyer_intent")

BUYER_INTENT_FIELD_ALIASES = {
    "requirement": "intent_summary",
    "summary": "intent_summary",
    "region": "region_scope_summary",
    "min_profit": "min_net_profit_yuan",
    "profit_min": "min_net_profit_yuan",
    "min_valuation": "min_valuation_yuan",
    "max_valuation": "max_valuation_yuan",
    "ps": "max_ps",
    "ps_multiple": "max_ps",
    "net_margin": "min_net_margin",
    "gross_margin": "min_gross_margin",
    "min_market_cap": "min_market_cap_yuan",
    "max_market_cap": "max_market_cap_yuan",
    "market_cap": "market_cap_range_summary",
    "control": "requires_control",
    "consolidation": "requires_consolidation",
    "listing_status_requirement": "preferred_listed_status",
    "listed_status_requirement": "preferred_listed_status",
    "listing_board": "listing_board_requirement_summary",
    "listing_board_requirement": "listing_board_requirement_summary",
    "financing_stage": "financing_stage_requirement_summary",
    "listing_stage": "financing_stage_requirement_summary",
    "transaction_types": "transaction_types_json",
    "deal_types": "transaction_types_json",
    "premium": "premium_tolerance_summary",
    "premium_tolerance": "premium_tolerance_summary",
    "debt_ratio": "debt_ratio_requirement_summary",
    "max_debt": "max_debt_ratio",
    "major_risk_tolerance": "major_risk_tolerance_summary",
    "risk_tolerance": "major_risk_tolerance_summary",
    "buyer_advantage": "buyer_industry_advantage_summary",
    "regional_industry_advantage": "buyer_industry_advantage_summary",
}

BUYER_SELLER_RELATION_CHANGE_FIELDS = {
    "buyer_intent_id",
    "buyer_party_id",
    "seller_target_id",
    "status",
    "status_reason",
    "first_recommended_at",
    "last_contact_at",
    "last_event_at",
    "last_event_summary",
    "event_type",
    "event_title",
    "event_content",
    "next_step",
    "buyer_name",
    "seller_target_name",
    "feedback",
    "recommendation_date",
}

BUYER_SELLER_RELATION_FIELD_ALIASES = {
    "feedback": "last_event_summary",
    "recommendation_date": "first_recommended_at",
    "recommended_at": "first_recommended_at",
    "event_summary": "last_event_summary",
    "title": "event_title",
    "content": "event_content",
}

# 派生自指标注册表：可写枚举列的合法取值。
SELLER_TARGET_ENUM_FIELDS = writable_enum_values()

SELLER_TARGET_POST_PARSE_STATUSES = {"parsing", "pending_review", "insufficient", "parse_failed"}

# 派生自指标注册表：买家意向可写枚举列的合法取值。
BUYER_INTENT_ENUM_FIELDS = writable_enum_values("buyer_intent")

BUYER_SELLER_RELATION_ENUM_FIELDS = {
    "status": {
        "recommended",
        "interested",
        "in_discussion",
        "due_diligence",
        "agreement",
        "deal_closed",
        "not_interested",
        "paused",
        "lost",
    },
    "event_type": {
        "recommended",
        "buyer_interested",
        "buyer_not_interested",
        "meeting",
        "call",
        "message",
        "email",
        "material_sent",
        "quote_update",
        "nda_signed",
        "management_meeting",
        "due_diligence_started",
        "due_diligence_progress",
        "agreement_discussion",
        "exclusivity",
        "deal_closed",
        "paused",
        "internal_note",
        "other",
    },
}

ENUM_VALUE_ALIASES = {
    "是": "yes",
    "否": "no",
    "可": "yes",
    "不可": "no",
    "可以": "yes",
    "不可以": "no",
    "可能": "likely",
    "不确定": "unknown",
    "未知": "unknown",
    "非上市": "unlisted",
    "未上市": "unlisted",
    "上市": "listed",
    "推荐": "recommended",
    "已推荐": "recommended",
    "recommendation": "recommended",
    "interested": "interested",
    "初步感兴趣": "interested",
    "感兴趣": "interested",
    "in_talk": "in_discussion",
    "沟通中": "in_discussion",
    "初步沟通": "in_discussion",
    "推进中": "in_discussion",
    "尽调": "due_diligence",
    "due_diligence_started": "due_diligence_started",
    "不感兴趣": "not_interested",
    "暂停": "paused",
    "暂不推进": "paused",
    "已结束": "closed",
    "结束": "closed",
    "终止": "closed",
    "已终止": "closed",
    "失败": "lost",
    "已成交": "deal_closed",
    "推荐反馈": "other",
    "recommendation_feedback": "other",
    "recommendation_negotiation": "other",
}

NESTED_FIELD_ALIASES = {
    ("finance", "profit"): "current_net_profit_yuan",
    ("finance", "net_profit"): "current_net_profit_yuan",
    ("finance", "revenue"): "current_revenue_yuan",
    ("finance", "valuation"): "valuation_yuan",
    ("finance", "asking_price"): "asking_price_yuan",
    ("finance", "pe"): "pe_ratio",
    ("deal", "can_control"): "can_control",
    ("deal", "can_consolidate"): "can_consolidate",
    ("deal", "is_for_sale"): "is_for_sale",
    ("deal", "transfer_ratio_min"): "transfer_ratio_min",
    ("deal", "transfer_ratio_max"): "transfer_ratio_max",
    ("deal", "transfer_ratio_text"): "transfer_ratio_text",
    ("risk", "summary"): "risk_summary",
    ("risk", "risk_summary"): "risk_summary",
}

def _resolve_entity_id(job: JobClaim, *, expected_entity_type: str) -> UUID | None:
    if job.entity_type == expected_entity_type and job.entity_id is not None:
        return job.entity_id
    payload_value = job.payload_json.get(f"{expected_entity_type}_id") or job.payload_json.get("entity_id")
    if not payload_value:
        return None
    return UUID(str(payload_value))

def _is_pdf_attachment(attachment: dict[str, Any]) -> bool:
    file_type = str(attachment.get("file_type") or "").lower()
    mime_type = str(attachment.get("mime_type") or "").split(";")[0].strip().lower()
    return file_type == "pdf" or mime_type == "application/pdf"

def _attachment_local_text_content(attachment: dict[str, Any], *, max_chars: int = 200_000) -> str | None:
    settings = get_settings()
    return read_local_text_content(
        attachment,
        storage_dir=settings.attachment_storage_dir,
        max_bytes=max_chars,
    )

def _attachment_file_bytes(attachment: dict[str, Any], *, max_bytes: int | None = None) -> bytes:
    settings = get_settings()
    data = read_attachment_bytes(
        attachment,
        storage_dir=settings.attachment_storage_dir,
        max_bytes=max_bytes or settings.attachment_max_upload_bytes,
        s3_endpoint_url=settings.effective_attachment_s3_endpoint_url,
        s3_region=settings.effective_attachment_s3_region,
        s3_bucket=settings.effective_attachment_s3_bucket,
        s3_access_key_id=settings.effective_attachment_s3_access_key_id,
        s3_secret_access_key=settings.effective_attachment_s3_secret_access_key,
        s3_force_path_style=settings.attachment_s3_force_path_style,
    )
    if data is None:
        raise AttachmentStorageError("Attachment file bytes are not available from configured storage.")
    return data

def _parse_source_context(
    job: JobClaim,
    *,
    default_source_type: str,
    default_source_label: str,
) -> dict[str, Any]:
    evidence_id = _optional_uuid(job.payload_json.get("evidence_id"))
    attachment_id = _optional_uuid(job.payload_json.get("attachment_id"))
    parsed_document_id = _optional_uuid(job.payload_json.get("parsed_document_id"))
    return {
        "source_type": str(job.payload_json.get("source_type") or default_source_type),
        "source_id": _optional_uuid(job.payload_json.get("source_id")) or job.id,
        "source_label": str(job.payload_json.get("source_label") or default_source_label),
        "evidence_id": evidence_id,
        "attachment_id": attachment_id,
        "parsed_document_id": parsed_document_id,
    }

def _get_default_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.temperature,
              node.top_p,
              node.max_tokens,
              node.timeout_seconds,
              node.response_format,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref, provider.api_key_encrypted,
              prompt.id as prompt_template_id,
              prompt.version as prompt_version,
              prompt.system_prompt,
              prompt.user_prompt_template,
              prompt.output_schema_json
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            left join prompt_template prompt
              on prompt.team_id = node.team_id
             and prompt.workspace_id = node.workspace_id
             and prompt.node_name = node.node_name
             and prompt.is_default = true
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Default model node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    if not config.get("prompt_template_id"):
        raise ValueError(f"Default prompt template is not configured for node: {node_name}")
    return config

def _get_default_embedding_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.embedding_dimension,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref, provider.api_key_encrypted
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'embedding'
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Default embedding node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    if not config.get("embedding_dimension"):
        raise ValueError(f"Embedding dimension is not configured for node: {node_name}")
    return config

def _get_default_rerank_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref, provider.api_key_encrypted
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'rerank'
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Default rerank node is not configured: {node_name}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {node_name}")
    return config

def _get_default_ocr_node_config(db: Session, node_name: str) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.model_name,
              node.timeout_seconds,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref, provider.api_key_encrypted
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.node_name = :node_name
              and node.node_type = 'ocr'
              and node.is_default = true
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Default OCR node is not configured: {node_name}")
    return dict(row)

def _get_model_node_config_by_id(db: Session, node_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.node_name,
              node.node_type,
              node.model_name,
              node.temperature,
              node.top_p,
              node.max_tokens,
              node.timeout_seconds,
              node.response_format,
              node.embedding_dimension,
              node.metadata_json,
              provider.id as provider_config_id,
              provider.provider_name,
              provider.base_url,
              provider.api_key_secret_ref, provider.api_key_encrypted,
              prompt.version as prompt_version,
              prompt.system_prompt,
              prompt.user_prompt_template,
              prompt.variables_json,
              prompt.output_schema_json
            from model_node_config node
            join model_provider_config provider
              on provider.id = node.provider_config_id
            left join prompt_template prompt
              on prompt.team_id = node.team_id
             and prompt.workspace_id = node.workspace_id
             and prompt.node_name = node.node_name
             and prompt.is_default = true
             and prompt.is_active = true
            where node.team_id = :team_id
              and node.workspace_id = :workspace_id
              and node.id = :node_id
              and node.is_active = true
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "node_id": node_id,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Model node is not configured or inactive: {node_id}")
    config = dict(row)
    if not config.get("base_url"):
        raise ValueError(f"Provider base_url is not configured for node: {config['node_name']}")
    if config.get("node_type") == "embedding" and not config.get("embedding_dimension"):
        raise ValueError(f"Embedding dimension is not configured for node: {config['node_name']}")
    return config

def _render_prompt_messages(
    node_config: dict[str, Any],
    variables: dict[str, Any],
) -> list[dict[str, str]]:
    system_prompt = render_template(node_config.get("system_prompt"), variables)
    user_prompt = render_template(node_config.get("user_prompt_template"), variables)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

def _attach_multimodal_images(
    messages: list[dict[str, Any]],
    images: list[dict[str, Any]],
    *,
    instruction: str | None = None,
) -> list[dict[str, Any]]:
    if not messages or not images:
        return messages
    updated = [dict(message) for message in messages]
    user_index = next((idx for idx in range(len(updated) - 1, -1, -1) if updated[idx].get("role") == "user"), len(updated) - 1)
    user_message = dict(updated[user_index])
    content = user_message.get("content")
    parts: list[dict[str, Any]]
    if isinstance(content, list):
        parts = list(content)
    else:
        parts = [{"type": "text", "text": str(content or "")}]
    parts.append(
        {
            "type": "text",
            "text": instruction or (
                "The following images are business update attachments. "
                "Read them directly, extract only business facts visible in the images, "
                "and cite the attachment id in raw_evidence_text when relevant."
            ),
        }
    )
    for image in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": image["data_url"]},
            }
        )
    user_message["content"] = parts
    updated[user_index] = user_message
    return updated

def _safe_prompt_messages_for_trace(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_messages: list[dict[str, Any]] = []
    for message in messages:
        safe_message = dict(message)
        content = safe_message.get("content")
        if isinstance(content, list):
            safe_parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    image_url = part.get("image_url") if isinstance(part.get("image_url"), dict) else {}
                    url = str(image_url.get("url") or "")
                    safe_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"<redacted data url: {len(url)} chars>",
                            },
                        }
                    )
                else:
                    safe_parts.append(part if isinstance(part, dict) else {"type": "text", "text": str(part)})
            safe_message["content"] = safe_parts
        safe_messages.append(safe_message)
    return safe_messages

# 模型看得见但改不了的列：给它当前值做判断，写回要走别的字段。
_SELLER_CONTEXT_READ_ONLY_COLUMNS = (
    "id",
    "target_name",
    "target_type",
    # 兼容投影列，真正的写入口是 industry_pairs_json。
    "industry_l1",
    "industry_l2",
)
# parse 可写但**故意**不给模型看的列，每条都要有理由。
_SELLER_CONTEXT_EXCLUDED_COLUMNS = frozenset(
    {
        # 由 mark_parse_completed 按解析结果自己维护，模型不该提议。
        "information_status",
    }
)


def seller_target_context_columns() -> list[str]:
    """模型的字段词汇表。

    提示词说的是 "use canonical seller_target fields from context" —— 没出现在
    这份清单里的字段，模型就当它不存在。所以这里必须从注册表派生而不是手写：
    手写过一次，42 个 parse 可写列漏了 21 个，财务几项全在漏的里面，年报摆在
    面前也只写得出行业和地区。新增可写指标现在会自动进来。
    """
    writable = writable_columns("parse") - _SELLER_CONTEXT_EXCLUDED_COLUMNS
    extra = sorted(writable - set(_SELLER_CONTEXT_READ_ONLY_COLUMNS))
    return [*_SELLER_CONTEXT_READ_ONLY_COLUMNS, *extra]


def _fetch_seller_targets(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    # 列名来自指标注册表，不是外部输入，可以安全拼接（同 field_writer._load_current）。
    projection = ", ".join(seller_target_context_columns())
    rows = db.execute(
        text(
            f"""
            select {projection}
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]

def _fetch_buyer_parties(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = db.execute(
        text(
            """
            select
              id, buyer_name, aliases_json, industries_json, industry_l2_json,
              region_province, region_city, contact_name, contact_info_json, notes
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]

_BUYER_INTENT_CONTEXT_READ_ONLY_COLUMNS = (
    "id",
    "buyer_party_id",
    "intent_name",
    "raw_requirement_text",
)
# parse 可写但**故意**不给模型看的列，每条都要有理由。
_BUYER_INTENT_CONTEXT_EXCLUDED_COLUMNS = frozenset(
    {
        # 需求的启停由人操作，不是从材料里读出来的。
        "status",
        "pause_reason",
    }
)


def buyer_intent_context_columns() -> list[str]:
    """买家侧的字段词汇表，和 seller_target_context_columns 同一个道理。"""
    writable = writable_columns("parse", "buyer_intent") - _BUYER_INTENT_CONTEXT_EXCLUDED_COLUMNS
    extra = sorted(writable - set(_BUYER_INTENT_CONTEXT_READ_ONLY_COLUMNS))
    return [*_BUYER_INTENT_CONTEXT_READ_ONLY_COLUMNS, *extra]


def _fetch_buyer_intents(db: Session, ids: list[UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    # 列名来自指标注册表，不是外部输入，可以安全拼接。
    projection = ", ".join(buyer_intent_context_columns())
    rows = db.execute(
        text(
            f"""
            select {projection}
            from buyer_intent
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and id = any(:ids)
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID, "ids": ids},
    ).mappings().all()
    return [_json_safe_dict(row) for row in rows]

def _uuid_list(values: Any) -> list[UUID]:
    if not isinstance(values, list):
        return []
    uuids: list[UUID] = []
    for value in values:
        try:
            uuids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return uuids

def _json_safe_dict(row: Any) -> dict[str, Any]:
    return json_safe_dict(row)

def _json_safe_value(value: Any) -> Any:
    return json_safe_value(value)

def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)

def _truncate_text(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if len(text_value) <= max_length:
        return text_value
    return text_value[: max_length - 3] + "..."

def _approx_token_count(value: str) -> int:
    stripped = value.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)

def _join_lines(values: Any) -> str:
    if not isinstance(values, list | tuple):
        return str(values or "").strip()
    return "\n".join(str(value).strip() for value in values if value is not None and str(value).strip())

YES_NO_LIKE_FIELDS = {
    "requires_control",
    "requires_consolidation",
    "accepts_minority_investment",
}

def _write_field_value_sources(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    source_context: dict[str, Any],
    review_status: str,
) -> None:
    for field_path in diff:
        db.execute(
            text(
                """
                insert into field_value_source (
                  team_id, workspace_id, entity_type, entity_id, field_path,
                  value_snapshot_json, source_type, source_id, evidence_id,
                  source_label, confidence, review_status, created_by
                )
                values (
                  :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
                  :value_snapshot_json, :source_type, :source_id, :evidence_id,
                  :source_label, :confidence, :review_status, :created_by
                )
                """
            ).bindparams(bindparam("value_snapshot_json", type_=JSONB)),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_path": field_path,
                "value_snapshot_json": {
                    "value": _json_safe_value(changes.get(field_path)),
                    "source_context": _json_safe_value(source_context),
                },
                "source_type": source_context.get("source_type"),
                "source_id": source_context.get("source_id"),
                "evidence_id": source_context.get("evidence_id"),
                "source_label": source_context.get("source_label"),
                "confidence": source_context.get("confidence"),
                "review_status": review_status,
                "created_by": SYSTEM_USER_ID,
            },
        )

def _diff_json_safe(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    diff: dict[str, tuple[Any, Any]] = {}
    for key, new_value in changes.items():
        old_value = original.get(key)
        if _json_safe_value(old_value) != _json_safe_value(new_value):
            diff[key] = (old_value, new_value)
    return diff

REQUIREMENT_STRENGTH_FIELDS = {
    "requires_relocation",
    "requires_return_investment",
    "requires_team_retention",
    "earnout_requirement",
}


REQUIREMENT_STRENGTH_ALIASES = {
    "required": "required",
    "require": "required",
    "must": "required",
    "yes": "required",
    "true": "required",
    "必须": "required",
    "要求": "required",
    "preferred": "preferred",
    "prefer": "preferred",
    "optional": "preferred",
    "nice_to_have": "preferred",
    "优先": "preferred",
    "加分": "preferred",
    "not_required": "not_required",
    "not required": "not_required",
    "no": "not_required",
    "false": "not_required",
    "none": "not_required",
    "不要求": "not_required",
    "不强制": "not_required",
}


def _normalize_requirement_strength(value: Any) -> str:
    """Coerce parser output onto the required/preferred/not_required enum.

    The columns carry a CHECK constraint, so an unmapped value would fail the
    whole parse job; unknown is the safe landing spot because the screening
    matrix treats it as "no requirement stated".
    """
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "required" if value else "not_required"
    text_value = str(value).strip().lower()
    if not text_value:
        return "unknown"
    return REQUIREMENT_STRENGTH_ALIASES.get(text_value, "unknown")


# 派生自指标注册表：两侧所有闭集多值列的合法元素。原来只有买家侧两项，且是
# 手写的——标的侧新增闭集列（重大风险、交易结构）时不会有人想起来补那份手写表，
# 结果是模型吐什么就存什么，DB 的 check 约束再把整条更新打回去。
CLOSED_LIST_FIELD_VALUES = {
    **multi_value_enum_values("buyer_intent"),
    **multi_value_enum_values(),
}


def _normalize_closed_list_values(field: str, value: Any) -> list[str]:
    """Drop anything outside the target-side enum this requirement mirrors."""
    allowed = CLOSED_LIST_FIELD_VALUES.get(field, set())
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text_value = str(item).strip().lower() if item is not None else ""
        if text_value in allowed and text_value not in normalized:
            normalized.append(text_value)
    return normalized


def _normalize_listing_market_region(value: Any) -> str:
    text_value = str(value or "").strip().lower()
    if text_value in {"domestic", "境内", "a股", "境内上市", "cn"}:
        return "domestic"
    if text_value in {"overseas", "境外", "海外", "港股", "美股", "境外上市"}:
        return "overseas"
    return "unknown"


def _normalize_yes_no_like(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"yes", "true", "1", "是", "需要", "要求", "必须", "可以", "可接受", "接受", "likely"}:
        return "likely" if normalized == "likely" else "yes"
    if normalized in {"no", "false", "0", "否", "不需要", "不要求", "不可以", "不可接受", "不接受"}:
        return "no"
    return "unknown"

def _normalize_allowed_enum(value: Any, allowed: set[str]) -> str | None:
    normalized = _normalize_enum_value(value)
    return normalized if normalized in allowed else None

def _normalize_seller_listed_status(value: Any) -> str:
    listed_status = _normalize_listed_status(value)
    if listed_status == "preparing_listing":
        return "pre_ipo"
    return "unknown" if listed_status == "any" else listed_status

def _normalize_listed_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized_key = normalized.replace(" ", "_").replace("-", "_")
    if normalized_key in {"listed", "public", "public_company", "yes", "true", "1"} or normalized in {
        "上市",
        "已上市",
    }:
        return "listed"
    if normalized_key in {
        "unlisted",
        "not_listed",
        "non_listed",
        "private",
        "private_company",
        "non_public",
        "not_public",
        "unquoted",
        "no",
        "false",
        "0",
    } or normalized in {"非上市", "未上市"}:
        return "unlisted"
    if normalized_key in {
        "preparing_listing",
        "preparing_to_list",
        "planned_listing",
        "ipo_candidate",
    } or normalized in {"准备上市", "拟上市", "计划上市"}:
        return "preparing_listing"
    if normalized_key in {"pre_ipo", "preipo"}:
        return "pre_ipo"
    if normalized_key in {"any", "no_preference", "all"} or normalized in {"不限", "均可"}:
        return "any"
    return "unknown"

def _normalize_equity_requirement_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    allowed = {
        "control_required",
        "consolidation_required",
        "minority_acceptable",
        "minority_only",
        "flexible",
        "specific_range",
        "unknown",
    }
    if normalized in allowed:
        return normalized
    if "并表" in normalized:
        return "consolidation_required"
    if "控股" in normalized or "控制" in normalized:
        return "control_required"
    if "参股" in normalized or "少数" in normalized:
        return "minority_acceptable"
    if "灵活" in normalized or "可谈" in normalized:
        return "flexible"
    return None

def _decimal_ratio(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        return Decimal("0")
    bigger = max(left, right)
    smaller = min(left, right)
    try:
        return bigger / smaller
    except Exception:
        return Decimal("0")

def _decimal_to_json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)

def _normalize_change_fields(
    proposed_changes: dict[str, Any],
    *,
    allowed_fields: set[str],
    aliases: dict[str, str],
    nested_aliases: dict[tuple[str, str], str] | None = None,
    enum_fields: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    normalized: dict[str, Any] = {}
    notes: list[str] = []

    for key, value in proposed_changes.items():
        if key in allowed_fields:
            normalized_value = _normalize_field_value(key, value, enum_fields, notes)
            if normalized_value is not _SKIP_FIELD:
                normalized[key] = normalized_value
            continue

        alias = aliases.get(key)
        if alias and alias in allowed_fields:
            normalized_value = _normalize_field_value(alias, value, enum_fields, notes)
            if normalized_value is not _SKIP_FIELD:
                normalized[alias] = normalized_value
            notes.append(f"{key}->{alias}")
            continue

        if isinstance(value, dict) and nested_aliases:
            for child_key, child_value in value.items():
                nested_alias = nested_aliases.get((key, child_key))
                if nested_alias and nested_alias in allowed_fields:
                    normalized_value = _normalize_field_value(
                        nested_alias,
                        child_value,
                        enum_fields,
                        notes,
                    )
                    if normalized_value is not _SKIP_FIELD:
                        normalized[nested_alias] = normalized_value
                    notes.append(f"{key}.{child_key}->{nested_alias}")

    return normalized, notes

def _normalize_field_value(
    field: str,
    value: Any,
    enum_fields: dict[str, set[str]] | None,
    notes: list[str],
) -> Any:
    if not enum_fields or field not in enum_fields:
        return value

    # 闭集多值列存的是数组：整体做标量归一会得到 "['litigation']" 这种字符串，
    # 一律落进 dropped_invalid_enum。逐元素过字典，全被丢弃时才跳过该字段——
    # 空数组在重大风险上是「未核查」，与「已核查无风险」是两回事，不能凭空写。
    if field in CLOSED_LIST_FIELD_VALUES:
        normalized_values = _normalize_closed_list_values(field, value)
        if not normalized_values:
            notes.append(f"{field}:{value}->dropped_invalid_enum")
            return _SKIP_FIELD
        if normalized_values != value:
            notes.append(f"{field}:{value}->{normalized_values}")
        return normalized_values

    if field == "listed_status":
        normalized = _normalize_seller_listed_status(value)
    elif field == "preferred_listed_status":
        normalized = _normalize_listed_status(value)
    else:
        normalized = _normalize_enum_value(value)
    allowed_values = enum_fields[field]
    if normalized in allowed_values:
        if normalized != value:
            notes.append(f"{field}:{value}->{normalized}")
        return normalized

    notes.append(f"{field}:{value}->dropped_invalid_enum")
    return _SKIP_FIELD

def _normalize_enum_value(value: Any) -> str:
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return ENUM_VALUE_ALIASES.get(normalized, ENUM_VALUE_ALIASES.get(str(value).strip(), normalized))

def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None

def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
