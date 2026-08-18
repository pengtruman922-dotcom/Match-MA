from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.profile_sections import load_profile_sections, render_profile_text


def rebuild_seller_target_search_doc(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    target = _get_seller_target(db, seller_target_id)

    title = target["target_name"]
    structured_summary = _join_lines(
        [
            f"标的：{target['target_name']}",
            _kv("标的主体", target.get("target_subject_name")),
            f"类型：{target['target_type']}",
            _kv("一级行业", target.get("industry_l1")),
            _kv("二级行业", target.get("industry_l2")),
            _kv("区域", _region_text(target)),
            _kv("上市状态", target.get("listed_status")),
        ]
    )
    business_text = _join_lines([target.get("business_summary")])
    financial_text = _join_lines(
        [
            _money("营收", target.get("current_revenue_yuan")),
            _money("净利润", target.get("current_net_profit_yuan")),
            _money("估值", target.get("valuation_yuan")),
            _kv("估值时间", target.get("valuation_date")),
            _money("报价", target.get("asking_price_yuan")),
            _kv("报价时间", target.get("asking_price_date")),
            _kv("PE", _decimal_text(target.get("pe_ratio"))),
        ]
    )
    transaction_text = _join_lines(
        [
            _kv("是否出售", target.get("is_for_sale")),
            _kv("可控股", target.get("can_control")),
            _kv("可并表", target.get("can_consolidate")),
            _kv("交易摘要", target.get("transaction_summary")),
        ]
    )
    risk_text = _join_lines([target.get("risk_summary")])
    gap_text = target.get("gap_summary")
    full_text = _join_lines(
        [
            structured_summary,
            business_text,
            financial_text,
            transaction_text,
            risk_text,
            gap_text,
        ]
    )

    row = db.execute(
        text(
            """
            insert into seller_target_search_doc (
              team_id, workspace_id, seller_target_id, doc_type, title,
              structured_summary, tag_text, business_text, financial_text,
              transaction_text, risk_text, gap_text, full_text, source_version,
              updated_at
            )
            values (
              :team_id, :workspace_id, :seller_target_id, 'profile', :title,
              :structured_summary, :tag_text, :business_text, :financial_text,
              :transaction_text, :risk_text, :gap_text, :full_text, 1, now()
            )
            on conflict (seller_target_id, doc_type) do update set
              title = excluded.title,
              structured_summary = excluded.structured_summary,
              tag_text = excluded.tag_text,
              business_text = excluded.business_text,
              financial_text = excluded.financial_text,
              transaction_text = excluded.transaction_text,
              risk_text = excluded.risk_text,
              gap_text = excluded.gap_text,
              full_text = excluded.full_text,
              source_version = seller_target_search_doc.source_version + 1,
              updated_at = now()
            returning id, full_text, source_version
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "seller_target_id": seller_target_id,
            "title": title,
            "structured_summary": structured_summary,
            "tag_text": "",
            "business_text": business_text,
            "financial_text": financial_text,
            "transaction_text": transaction_text,
            "risk_text": risk_text,
            "gap_text": gap_text,
            "full_text": full_text,
        },
    ).mappings().one()
    return {"search_doc_id": row["id"], "full_text": row["full_text"], "source_version": row["source_version"]}


def rebuild_buyer_intent_search_doc(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    intent = _get_buyer_intent(db, buyer_intent_id)
    requirement_summary = _join_lines(
        [
            f"意向：{intent['intent_name']}",
            intent.get("intent_summary"),
            intent.get("raw_requirement_text"),
        ]
    )
    industries = intent.get("industries_json")
    industries_text = "、".join(str(item) for item in industries if item) if isinstance(industries, list) else None
    focus_tags = intent.get("industry_focus_tags_json")
    focus_tags_text = "、".join(str(item) for item in focus_tags if item) if isinstance(focus_tags, list) else None
    constraint_text = _join_lines(
        [
            _kv("关注行业", industries_text),
            _kv("细分赛道", focus_tags_text),
            _kv("一级行业", intent.get("industry_primary")),
            _kv("二级行业", intent.get("industry_secondary")),
            _kv("区域", intent.get("region_scope_summary")),
            _kv("结构化地区", _json_text(intent.get("region_constraints_json"))),
            _money("最低营收", intent.get("min_revenue_yuan")),
            _money("最低净利润", intent.get("min_net_profit_yuan")),
            _money("最低估值", intent.get("min_valuation_yuan")),
            _money("最高估值", intent.get("max_valuation_yuan")),
            _money("最低市值", intent.get("min_market_cap_yuan")),
            _money("最高市值", intent.get("max_market_cap_yuan")),
            _kv("市值范围", intent.get("market_cap_range_summary")),
            _kv("PE上限", _decimal_text(intent.get("max_pe"))),
            _kv("PS上限", _decimal_text(intent.get("max_ps"))),
            _kv("最低净利率", _decimal_text(intent.get("min_net_margin"))),
            _kv("最低毛利率", _decimal_text(intent.get("min_gross_margin"))),
            _kv("需要控股", intent.get("requires_control")),
            _kv("需要并表", intent.get("requires_consolidation")),
            _kv("接受少数股权", intent.get("accepts_minority_investment")),
            _kv("迁址要求", intent.get("requires_relocation")),
            _kv("返投要求", intent.get("requires_return_investment")),
            _kv("团队留任要求", intent.get("requires_team_retention")),
            _kv("可接受上市状态", intent.get("acceptable_listed_status_json") or intent.get("preferred_listed_status")),
            _kv("条件作用", intent.get("condition_effects_json")),
            _kv("上市板块要求", intent.get("listing_board_requirement_summary")),
            _kv("融资/上市阶段", intent.get("financing_stage_requirement_summary")),
            _kv("交易方式原文", intent.get("transaction_type")),
            _kv("可接受交易结构", _json_text(intent.get("transaction_types_json"))),
            _kv("溢价要求", intent.get("premium_tolerance_summary")),
            _kv("溢价上限", _decimal_text(intent.get("max_premium_rate"))),
            _kv("负债率上限", _decimal_text(intent.get("max_debt_ratio"))),
            _kv("负债率要求", intent.get("debt_ratio_requirement_summary")),
            _kv("重大风险容忍", intent.get("major_risk_tolerance_summary")),
            _kv("不接受的重大风险", _json_text(intent.get("unacceptable_risk_flags_json"))),
            _kv("收购方产业优势", intent.get("buyer_industry_advantage_summary")),
        ]
    )
    # 标准化不了的说法现在住在各模块的「其他」里。搜索文档是深评实际读到的
    # 那份上下文，所以它必须把「其他」带上 —— 否则「放进其他就交给深评」这句话
    # 只对界面成立，对模型不成立。
    sections = load_profile_sections(
        db, entity_type="buyer_intent", entity_ids=[buyer_intent_id]
    ).get(str(buyer_intent_id))
    preference_text = render_profile_text(sections, entity_type="buyer_intent") or None
    negative_text = None
    history_text = None
    # This document is now used as direct LLM context rather than an embedding
    # source, so exclusions must be explicit and buyer-party profile data is omitted.
    full_text = _join_lines([requirement_summary, constraint_text, preference_text, negative_text])

    row = db.execute(
        text(
            """
            insert into buyer_intent_search_doc (
              team_id, workspace_id, buyer_intent_id, title,
              requirement_summary, constraint_text, preference_text,
              negative_text, history_text, full_text, source_version, updated_at
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :title,
              :requirement_summary, :constraint_text, :preference_text,
              :negative_text, :history_text, :full_text, 1, now()
            )
            on conflict (buyer_intent_id) do update set
              title = excluded.title,
              requirement_summary = excluded.requirement_summary,
              constraint_text = excluded.constraint_text,
              preference_text = excluded.preference_text,
              negative_text = excluded.negative_text,
              history_text = excluded.history_text,
              full_text = excluded.full_text,
              source_version = buyer_intent_search_doc.source_version + 1,
              updated_at = now()
            returning id, full_text, source_version
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "title": intent["intent_name"],
            "requirement_summary": requirement_summary,
            "constraint_text": constraint_text,
            "preference_text": preference_text,
            "negative_text": negative_text,
            "history_text": history_text,
            "full_text": full_text,
        },
    ).mappings().one()
    return {"search_doc_id": row["id"], "full_text": row["full_text"], "source_version": row["source_version"]}


def create_embedding_job_for_search_doc(
    db: Session,
    *,
    owner_job_id: UUID | None,
    entity_type: str,
    entity_id: UUID,
    search_doc_id: UUID,
    # The dedicated embedding worker was retired with recommendation v3; route
    # manual embedding jobs to the llm queue so they still get consumed.
    queue_name: str = "llm",
) -> UUID:
    job_type = "embedding_generate"
    idempotency_key = f"{job_type}:{entity_type}:{entity_id}:{search_doc_id}"
    existing = db.execute(
        text(
            """
            select id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = :job_type
              and idempotency_key = :idempotency_key
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": job_type,
            "idempotency_key": idempotency_key,
        },
    ).mappings().one_or_none()
    if existing:
        return existing["id"]

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              parent_job_id, created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :job_type, 100, :queue_name,
              :entity_type, :entity_id, :idempotency_key, :payload_json,
              :parent_job_id, null, :metadata_json
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
            "job_type": job_type,
            "queue_name": queue_name,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "idempotency_key": idempotency_key,
            "payload_json": {
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "search_doc_id": str(search_doc_id),
            },
            "parent_job_id": owner_job_id,
            "metadata_json": {"source": "search_doc_rebuild"},
        },
    ).mappings().one()
    return row["id"]


def create_search_doc_rebuild_job(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    # 重建只做数据库文本拼接，不调用任何模型；队列名仅决定由哪个 worker 池执行。
    # 历史上它进 embedding 队列是因为文档要拿去算向量，推荐 v3 之后改为直接作为
    # LLM 上下文，专用 embedding worker 也已下线，因此改走 llm 队列。
    queue_name: str = "llm",
    source: str = "search_doc_rebuild",
) -> dict[str, Any]:
    if entity_type == "seller_target":
        job_type = "seller_search_doc_rebuild"
    elif entity_type == "buyer_intent":
        job_type = "buyer_intent_search_doc_rebuild"
    else:
        raise ValueError("search doc rebuild supports seller_target or buyer_intent only.")

    idempotency_key = f"{job_type}:{entity_id}"
    existing = db.execute(
        text(
            """
            select id, job_type, status, queue_name, entity_type, entity_id
            from background_job
            where team_id = :team_id
              and workspace_id = :workspace_id
              and job_type = :job_type
              and idempotency_key = :idempotency_key
              and status in ('queued', 'running', 'retry_waiting')
            order by created_at desc
            limit 1
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": job_type,
            "idempotency_key": idempotency_key,
        },
    ).mappings().one_or_none()
    if existing:
        return {
            "job_id": existing["id"],
            "job_type": existing["job_type"],
            "status": existing["status"],
            "queue_name": existing["queue_name"],
            "entity_type": existing["entity_type"],
            "entity_id": existing["entity_id"],
        }

    row = db.execute(
        text(
            """
            insert into background_job (
              team_id, workspace_id, job_type, priority, queue_name,
              entity_type, entity_id, idempotency_key, payload_json,
              created_by, metadata_json
            )
            values (
              :team_id, :workspace_id, :job_type, 100, :queue_name,
              :entity_type, :entity_id, :idempotency_key, :payload_json,
              :created_by, :metadata_json
            )
            returning id, job_type, status, queue_name, entity_type, entity_id
            """
        ).bindparams(
            bindparam("payload_json", type_=JSONB),
            bindparam("metadata_json", type_=JSONB),
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "job_type": job_type,
            "queue_name": queue_name,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "idempotency_key": idempotency_key,
            "payload_json": {"entity_type": entity_type, "entity_id": str(entity_id)},
            "created_by": DEFAULT_ADMIN_USER_ID,
            "metadata_json": {"source": source},
        },
    ).mappings().one()
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "queue_name": row["queue_name"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
    }


def _get_seller_target(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, target_name, target_type, target_subject_name, industry_l1, industry_l2, industry_pairs_json,
              location_province, location_city, location_district, listed_status,
              current_revenue_yuan, current_net_profit_yuan, valuation_yuan, valuation_date,
              asking_price_yuan, asking_price_date, pe_ratio, is_for_sale, can_control,
              can_consolidate, business_summary, transaction_summary,
              risk_summary, gap_summary
            from seller_target
            where id = :seller_target_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "seller_target_id": seller_target_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Seller target not found: {seller_target_id}")
    return dict(row)


def _get_buyer_intent(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              id, buyer_party_id, intent_name, raw_requirement_text, intent_summary,
              industry_primary, industry_secondary, industries_json, industry_l2_json,
              excluded_industries_json, industry_focus_tags_json,
              region_scope_summary, region_constraints_json,
              min_revenue_yuan, min_net_profit_yuan, max_pe, max_ps,
              min_net_margin, min_gross_margin, min_valuation_yuan, max_valuation_yuan,
              min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary,
              requires_control, requires_consolidation, accepts_minority_investment,
              preferred_listed_status, acceptable_listed_status_json, condition_effects_json,
              requires_relocation, requires_return_investment, requires_team_retention,
              listing_board_requirement_summary,
              financing_stage_requirement_summary, transaction_type, transaction_types_json,
              premium_tolerance_summary, max_premium_rate, max_debt_ratio,
              debt_ratio_requirement_summary, major_risk_tolerance_summary,
              unacceptable_risk_flags_json,
              buyer_industry_advantage_summary
            from buyer_intent
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        raise ValueError(f"Buyer intent not found: {buyer_intent_id}")
    return dict(row)


def _region_text(target: dict[str, Any]) -> str | None:
    parts = [target.get("location_province"), target.get("location_city"), target.get("location_district")]
    text_value = "".join(str(part) for part in parts if part)
    return text_value or None


def _join_lines(values: Any) -> str | None:
    lines = [str(value).strip() for value in values if value is not None and str(value).strip()]
    return "\n".join(lines) if lines else None


def _kv(label: str, value: Any) -> str | None:
    return f"{label}：{value}" if value is not None and str(value).strip() else None


def _money(label: str, value: Any) -> str | None:
    if value is None:
        return None
    return f"{label}：{_decimal_text(value)}元"


def _decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "、".join(str(item) for item in value if str(item).strip()) or None
    if isinstance(value, dict):
        return "、".join(f"{key}:{item}" for key, item in value.items() if item is not None) or None
    return str(value)
