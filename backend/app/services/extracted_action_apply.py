"""Apply logic for extracted actions, shared by API routes and job handlers."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.registry.indicators import seller_target_fact_columns, writable_columns
from backend.app.api.routes.utils import (
    diff_payload,
    write_action_logs_for_diff,
    write_field_value_sources_for_diff,
)
from backend.app.services.buyer_intent_industry import normalize_buyer_intent_industry_changes
from backend.app.services.entity_grade import BUYER_GRADE, normalize_lifecycle_status, resolve_grade_pair
from backend.app.services.field_writer import WriteProvenance, write_seller_target_fields
from backend.app.services.relation_flow import mark_seller_target_sold_for_deal_closed
from backend.app.services.search_docs import create_search_doc_rebuild_job
from backend.app.services.seller_target_status import mark_parse_completed

def apply_seller_fact_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
    actor_user_id: UUID = SYSTEM_USER_ID,
) -> dict[str, Any]:
    if action["action_type"] != "seller_fact_update" or action["target_entity_type"] != "seller_target":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only seller_fact_update actions targeting seller_target are supported now.",
        )
    if action["target_entity_id"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_entity_id is required.")
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    seller_target_id = action["target_entity_id"]
    original = _get_seller_target_snapshot_or_404(db, seller_target_id)
    changes = _allowed_seller_target_changes(action["proposed_changes_json"])
    lifecycle_status = _lifecycle_status_from_changes(action["proposed_changes_json"])
    if lifecycle_status is not None:
        # 运行时提示词可编辑，模型可能给中文也可能给枚举码，映射在这里做完再交给
        # field_writer —— 它按注册表做严格枚举校验，"已售出" 会被当成非法值。
        # 级别（target_grade）由 field_writer 内部按这一对派生，这里不碰。
        changes["lifecycle_status"] = lifecycle_status
    if lifecycle_status in {"sold", "off_market"}:
        # Terminal market evidence is a safe one-way sync. A later in-sale
        # signal never reactivates a sold or off-market target automatically
        # (entity_grade.resolve_grade_pair 的 allow_reactivation=False 保证).
        changes["is_for_sale"] = "no"
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported changes to apply.")
    changes = _seller_target_changes_with_parse_completion(original, changes)
    source_context = _action_source_context(action, default_source_label="Business update extracted action")
    # 一次 action 是一袋互相独立的主张。一个数字格式不对，不该把同批另外八个
    # 好字段一起扔掉 —— 被拒的字段记进 action，可查、可复核，但不阻断其余写入。
    rejected_fields: dict[str, str] = {}
    applied_fields = write_seller_target_fields(
        db,
        seller_target_id,
        changes,
        rejected_fields=rejected_fields,
        provenance=WriteProvenance(
            source_type="extracted_action",
            actor_user_id=actor_user_id,
            source_id=action["id"],
            evidence_id=source_context["evidence_id"],
            business_update_id=action["business_update_id"],
            extracted_action_id=action["id"],
            field_source_label=source_context["source_label"],
            confidence=action.get("confidence"),
            review_status="auto_accepted",
            source_context=source_context,
            log_metadata={
                "source": "extracted_action_apply",
                "action_type": action["action_type"],
                "field_value_source": source_context,
            },
        ),
        search_doc_source="seller_fact_update_apply",
    )
    mark_parse_completed(
        db,
        seller_target_id=seller_target_id,
        actor_user_id=actor_user_id,
    )
    if rejected_fields:
        _record_rejected_fields(db, action["id"], rejected_fields)
    if not applied_fields:
        _mark_action_applied(db, action["id"], review_status="auto_accepted")
        _refresh_business_update_status(db, action["business_update_id"])
        return {
            "status": "noop",
            "extracted_action_id": action["id"],
            "business_update_id": action["business_update_id"],
            "entity_type": "seller_target",
            "entity_id": seller_target_id,
            "applied_fields": [],
            "rejected_fields": rejected_fields,
        }

    _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "seller_target",
        "entity_id": seller_target_id,
        "applied_fields": applied_fields,
        "rejected_fields": rejected_fields,
    }


def _record_rejected_fields(
    db: Session,
    extracted_action_id: UUID,
    rejected_fields: dict[str, str],
) -> None:
    """把被拒字段挂到 action 上。

    静默丢弃比整批失败更糟 —— 落在这里，复核页和 debug 都能看到模型给了什么、
    为什么没写进去，也是判断提示词该怎么改的唯一证据。
    """
    db.execute(
        text(
            """
            update extracted_action
            set metadata_json = metadata_json || :metadata_patch
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {"rejected_fields": rejected_fields},
        },
    )


def _record_industry_notes(db: Session, extracted_action_id: UUID, notes: list[str]) -> None:
    """把字典对齐时挪走的行业说法挂到 action 上。

    值没丢（都进了 industry_focus_tags_json 走深评），但「模型说的是汽车电子零部件、
    字典里只有汽车零部件」这件事只有这里留得住 —— 也是判断字典该不该补词的依据。
    """
    db.execute(
        text(
            """
            update extracted_action
            set metadata_json = metadata_json || :metadata_patch
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("metadata_patch", type_=JSONB)),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "metadata_patch": {"industry_normalization_notes": notes[:50]},
        },
    )


def apply_buyer_intent_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
    actor_user_id: UUID = SYSTEM_USER_ID,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_intent_update" or action["target_entity_type"] != "buyer_intent":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_intent_update actions targeting buyer_intent are supported now.",
        )
    if action["target_entity_id"] is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_entity_id is required.")
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = _allowed_buyer_intent_changes(action["proposed_changes_json"])
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No supported changes to apply.")

    # 行业列是封闭词表的筛选列，只能带着字典写。新建解析那条路一直这么做，
    # 这条路（带附件时的 business_update_extractor）此前直接写原文，于是
    # 「汽车电子零部件」这类字典外的说法进了 industries_json —— 页面上看着有
    # 行业筛选，实际一个标的都匹配不上。字典装不下的说法挪进 focus_tags 走深评。
    industry_notes = normalize_buyer_intent_industry_changes(db, changes)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No supported changes to apply after industry normalization.",
        )

    buyer_intent_id = action["target_entity_id"]
    original = _get_buyer_intent_snapshot_or_404(db, buyer_intent_id)
    _apply_grade_pair(changes, original, allow_reactivation=False)
    diff = diff_payload(original, changes)
    if not diff:
        _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
        _refresh_business_update_status(db, action["business_update_id"])
        return {
            "status": "noop",
            "extracted_action_id": action["id"],
            "business_update_id": action["business_update_id"],
            "entity_type": "buyer_intent",
            "entity_id": buyer_intent_id,
            "applied_fields": [],
        }

    set_clauses = [f"{field} = :{field}" for field in diff]
    set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])

    update_statement = text(
        f"""
            update buyer_intent
            set {', '.join(set_clauses)}
            where id = :buyer_intent_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
    )
    json_fields = {
        "contact_info_json",
        "parsed_requirement_json",
        "region_constraints_json",
        "acceptable_control_paths_json",
        "transaction_types_json",
        "industries_json",
        "industry_l2_json",
        "excluded_industries_json",
        "industry_focus_tags_json",
        "acceptable_cash_flow_status_json",
        "acceptable_profitability_status_json",
        "acceptable_listed_status_json",
        "unacceptable_risk_flags_json",
        "condition_effects_json",
        "relocation_target_regions_json",
        "needs_confirmation_json",
    }
    bind_params = [bindparam(field, type_=JSONB) for field in diff if field in json_fields]
    if bind_params:
        update_statement = update_statement.bindparams(*bind_params)

    db.execute(
        update_statement,
        {
            **{field: changes[field] for field in diff},
            "updated_by": actor_user_id,
            "buyer_intent_id": buyer_intent_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )

    source_context = _action_source_context(action, default_source_label="Business update extracted action")
    write_action_logs_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        business_update_id=action["business_update_id"],
        extracted_action_id=action["id"],
        metadata_json={
            "source": "extracted_action_apply",
            "action_type": action["action_type"],
            "field_value_source": source_context,
        },
        applied_by=actor_user_id,
    )
    write_field_value_sources_for_diff(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        changes=changes,
        diff=diff,
        source_type="extracted_action",
        source_id=action["id"],
        evidence_id=source_context["evidence_id"],
        source_label=source_context["source_label"],
        confidence=action.get("confidence"),
        review_status="auto_accepted",
        source_context=source_context,
        created_by=actor_user_id,
    )
    create_search_doc_rebuild_job(
        db,
        entity_type="buyer_intent",
        entity_id=buyer_intent_id,
        source="buyer_intent_update_apply",
    )
    if industry_notes:
        _record_industry_notes(db, action["id"], industry_notes)
    _mark_action_applied(db, action["id"], review_status="auto_accepted" if not require_accepted else None)
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_intent",
        "entity_id": buyer_intent_id,
        "applied_fields": list(diff.keys()),
        "industry_normalization_notes": industry_notes,
    }


def apply_buyer_seller_relation_update_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
    actor_user_id: UUID = SYSTEM_USER_ID,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_seller_relation_update":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_seller_relation_update actions are supported here.",
        )
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = action["proposed_changes_json"]
    buyer_intent_id = _required_uuid(changes.get("buyer_intent_id"), "buyer_intent_id")
    seller_target_id = _required_uuid(changes.get("seller_target_id"), "seller_target_id")
    buyer_party_id = _optional_uuid(changes.get("buyer_party_id")) or _get_buyer_party_id_for_intent(
        db,
        buyer_intent_id,
    )
    relation = _get_or_create_relation(
        db,
        buyer_intent_id,
        seller_target_id,
        buyer_party_id,
        actor_user_id=actor_user_id,
    )

    relation_updates = _allowed_relation_changes(changes)
    relation_updates.setdefault("last_event_summary", _relation_event_content(changes, action))
    relation_updates.setdefault("last_event_at", changes.get("last_event_at") or "now()")
    if changes.get("event_type") == "recommended":
        relation_updates.setdefault("first_recommended_at", changes.get("first_recommended_at") or "now()")

    diff = diff_payload(relation, relation_updates)
    if diff:
        set_clauses: list[str] = []
        params: dict[str, Any] = {
            "relation_id": relation["id"],
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "updated_by": actor_user_id,
        }
        for field in diff:
            if field in {"last_event_at", "first_recommended_at"} and relation_updates[field] == "now()":
                set_clauses.append(f"{field} = now()")
            else:
                set_clauses.append(f"{field} = :{field}")
                params[field] = relation_updates[field]
        set_clauses.extend(["updated_at = now()", "updated_by = :updated_by"])
        db.execute(
            text(
                f"""
                update buyer_seller_relation
                set {', '.join(set_clauses)}
                where id = :relation_id
                  and team_id = :team_id
                  and workspace_id = :workspace_id
                  and deleted_at is null
                """
            ),
            params,
        )
        source_context = _action_source_context(action, default_source_label="Business update relation update")
        write_action_logs_for_diff(
            db,
            entity_type="buyer_seller_relation",
            entity_id=relation["id"],
            diff=diff,
            source_type="extracted_action",
            source_id=action["id"],
            evidence_id=source_context["evidence_id"],
            business_update_id=action["business_update_id"],
            extracted_action_id=action["id"],
            metadata_json={
                "source": "extracted_action_apply",
                "action_type": action["action_type"],
                "field_value_source": source_context,
            },
            applied_by=actor_user_id,
        )
        write_field_value_sources_for_diff(
            db,
            entity_type="buyer_seller_relation",
            entity_id=relation["id"],
            changes=relation_updates,
            diff=diff,
            source_type="extracted_action",
            source_id=action["id"],
            evidence_id=source_context["evidence_id"],
            source_label=source_context["source_label"],
            confidence=action.get("confidence"),
            review_status="auto_accepted",
            source_context=source_context,
            created_by=actor_user_id,
        )
    if relation_updates.get("status") == "deal_closed":
        # AI-extracted and manually changed relation statuses share the same
        # target lifecycle consequence: an explicit closed deal sells the
        # target and removes it from subsequent recommendation candidates.
        mark_seller_target_sold_for_deal_closed(
            db,
            seller_target_id=seller_target_id,
            relation_id=relation["id"],
            actor_user_id=actor_user_id,
        )

    _insert_relation_event(
        db,
        action,
        relation["id"],
        buyer_intent_id,
        seller_target_id,
        buyer_party_id,
        changes,
        actor_user_id=actor_user_id,
    )
    _mark_action_applied(db, action["id"], review_status=None if require_accepted else "auto_accepted")
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_seller_relation",
        "entity_id": relation["id"],
        "applied_fields": list(diff.keys()) + ["relation_event"],
    }


def apply_buyer_intent_target_exclusion_action(
    db: Session,
    action: dict[str, Any],
    *,
    require_accepted: bool = True,
    actor_user_id: UUID = SYSTEM_USER_ID,
) -> dict[str, Any]:
    if action["action_type"] != "buyer_intent_target_exclusion":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only buyer_intent_target_exclusion actions are supported here.",
        )
    if action["applied_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Action has already been applied.")
    if require_accepted and action["review_status"] not in {"accepted", "auto_accepted"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action must be accepted before apply.",
        )

    changes = action["proposed_changes_json"]
    buyer_intent_id = _required_uuid(changes.get("buyer_intent_id") or action["target_entity_id"], "buyer_intent_id")
    seller_target_id = _required_uuid(changes.get("seller_target_id"), "seller_target_id")
    buyer_party_id = _optional_uuid(changes.get("buyer_party_id")) or _get_buyer_party_id_for_intent(
        db,
        buyer_intent_id,
    )
    reason = (
        changes.get("reason")
        or changes.get("exclusion_reason")
        or action.get("raw_evidence_text")
        or "Marked as excluded by extracted action."
    )
    relation_id = _optional_uuid(changes.get("source_relation_id"))

    row = db.execute(
        text(
            """
            insert into buyer_intent_target_exclusion (
              team_id, workspace_id, buyer_intent_id, buyer_party_id, seller_target_id,
              reason, source_relation_id, source_update_id, created_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              :reason, :source_relation_id, :source_update_id, :created_by
            )
            on conflict (team_id, buyer_intent_id, seller_target_id)
              where active = true and canceled_at is null
            do update set
              buyer_party_id = excluded.buyer_party_id,
              reason = excluded.reason,
              source_relation_id = coalesce(excluded.source_relation_id, buyer_intent_target_exclusion.source_relation_id),
              source_update_id = excluded.source_update_id
            returning id
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "reason": reason,
            "source_relation_id": relation_id,
            "source_update_id": action["business_update_id"],
            "created_by": actor_user_id,
        },
    ).mappings().one()

    relation_action = {
        **action,
        "action_type": "buyer_seller_relation_update",
        "proposed_changes_json": {
            "buyer_intent_id": str(buyer_intent_id),
            "buyer_party_id": str(buyer_party_id) if buyer_party_id else None,
            "seller_target_id": str(seller_target_id),
            "status": "not_interested",
            "status_reason": reason,
            "event_type": "buyer_not_interested",
            "event_content": reason,
        },
        "applied_at": None,
        "review_status": "auto_accepted",
    }
    apply_buyer_seller_relation_update_action(
        db,
        relation_action,
        require_accepted=True,
        actor_user_id=actor_user_id,
    )
    _mark_action_applied(db, action["id"], review_status=None if require_accepted else "auto_accepted")
    _refresh_business_update_status(db, action["business_update_id"])

    return {
        "status": "applied",
        "extracted_action_id": action["id"],
        "business_update_id": action["business_update_id"],
        "entity_type": "buyer_intent_target_exclusion",
        "entity_id": row["id"],
        "applied_fields": ["buyer_intent_target_exclusion", "relation.status", "relation_event"],
    }


def _get_seller_target_snapshot_or_404(db: Session, seller_target_id: UUID) -> dict[str, Any]:
    # 事实列来自注册表，不是外部输入，可以安全拼接（同 common._fetch_seller_targets）。
    row = db.execute(
        text(
            f"""
            select
              {", ".join(seller_target_fact_columns())}
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Seller target not found.")
    return dict(row)


def _get_buyer_intent_snapshot_or_404(db: Session, buyer_intent_id: UUID) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              intent_name, intent_grade, status, pause_reason, contact_name, contact_info_json,
              raw_requirement_text, intent_summary, parsed_requirement_json,
              industry_primary, industry_secondary, industries_json,
              excluded_industries_json, industry_focus_tags_json, region_scope_summary,
              region_constraints_json, min_revenue_yuan, min_net_profit_yuan,
              min_total_profit_yuan, max_pe, max_ps, min_net_margin, min_gross_margin,
              min_valuation_yuan, max_valuation_yuan,
              min_market_cap_yuan, max_market_cap_yuan, market_cap_range_summary,
              requires_control, requires_consolidation, accepts_minority_investment,
              desired_equity_ratio_min, desired_equity_ratio_max, equity_ratio_summary,
              equity_requirement_type, acceptable_control_paths_json,
              preferred_listed_status, acceptable_listed_status_json, condition_effects_json,
              listing_board_requirement_summary,
              financing_stage_requirement_summary, transaction_type, transaction_types_json,
              premium_tolerance_summary, max_premium_rate, max_debt_ratio,
              debt_ratio_requirement_summary, major_risk_tolerance_summary,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return dict(row)


def _get_buyer_party_id_for_intent(db: Session, buyer_intent_id: UUID) -> UUID | None:
    row = db.execute(
        text(
            """
            select buyer_party_id
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Buyer intent not found.")
    return row["buyer_party_id"]


def _get_or_create_relation(
    db: Session,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    buyer_party_id: UUID | None,
    *,
    actor_user_id: UUID,
) -> dict[str, Any]:
    existing = db.execute(
        text(
            """
            select
              id, status, status_reason, first_recommended_at, last_contact_at,
              last_event_at, last_event_summary
            from buyer_seller_relation
            where team_id = :team_id
              and workspace_id = :workspace_id
              and buyer_intent_id = :buyer_intent_id
              and seller_target_id = :seller_target_id
              and deleted_at is null
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "seller_target_id": seller_target_id,
        },
    ).mappings().one_or_none()
    if existing:
        return dict(existing)

    row = db.execute(
        text(
            """
            insert into buyer_seller_relation (
              team_id, workspace_id, buyer_intent_id, buyer_party_id, seller_target_id,
              status, created_by
            )
            values (
              :team_id, :workspace_id, :buyer_intent_id, :buyer_party_id, :seller_target_id,
              'recommended', :created_by
            )
            returning
              id, status, status_reason, first_recommended_at, last_contact_at,
              last_event_at, last_event_summary
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "created_by": actor_user_id,
        },
    ).mappings().one()
    return dict(row)


def _allowed_seller_target_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed = {key: value for key, value in changes.items() if key in writable_columns("parse")}
    # Existing editable prompts may still emit the retired raw industry keys.
    # Consume them only as transient dictionary-normalization candidates; they
    # are never written back as seller_target columns.
    if "industry_pairs_json" not in allowed:
        legacy_pair = {
            "l1": changes.get("industry_l1") or changes.get("industry_primary"),
            "l2": changes.get("industry_l2") or changes.get("industry_secondary"),
        }
        if legacy_pair["l1"] or legacy_pair["l2"]:
            # The writer performs the database-backed canonicalization. This
            # local shape conversion only keeps old prompt output actionable.
            allowed["industry_pairs_json"] = [legacy_pair]
    return allowed


def _lifecycle_status_from_changes(changes: dict[str, Any]) -> str | None:
    """Derive the market lifecycle from explicit parser facts.

    Runtime prompt versions are editable, so newer versions may emit either a
    lifecycle code or a direct transaction-status field.  Resolving the aliases
    here makes an unequivocal “已售出/已停售” update close both the lifecycle
    and the user-facing “是否还卖” fact, without treating an ordinary follow-up
    as a fact update (that routing remains deliberately deferred).

    级别（target_grade）由 field_writer 内部按这一对派生，这里只负责把非规范的
    字段名与中文说法收敛成 lifecycle_status 的枚举码。
    """
    return normalize_lifecycle_status(
        changes.get("lifecycle_status")
        or changes.get("sale_status")
        or changes.get("market_status")
        or changes.get("is_for_sale")
        or ""
    )


def _seller_target_changes_with_parse_completion(
    original: dict[str, Any],
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Return fact changes only; parse completion is maintained separately.

    ``mark_parse_completed`` runs after the fact writer. Keeping the derived
    ``information_status`` out of the fact diff means withdrawing a price or
    profile update can never restore the transient value ``parsing``.
    """
    return dict(changes)


_POST_PARSE_INFORMATION_STATUSES = {"parsing", "pending_review", "insufficient", "parse_failed"}


def _apply_grade_pair(
    changes: dict[str, Any],
    original: dict[str, Any],
    *,
    allow_reactivation: bool,
) -> None:
    """就地把买家需求的级别与推荐状态收敛成自洽的一对。

    买家侧没有 field_writer 那样的统一写入咽喉（三条路各自拼 UPDATE），所以派生
    只能在每个调用点显式做一次。空结果意味着这批变更没有级别主张，或者 AI 想把
    E 拉回在售 —— 两种都把这两列从变更里摘掉，其余字段照写。
    """
    resolved = resolve_grade_pair(
        BUYER_GRADE,
        changes,
        original,
        allow_reactivation=allow_reactivation,
    )
    changes.pop(BUYER_GRADE.grade_column, None)
    changes.pop(BUYER_GRADE.reason_column, None)
    changes.update(resolved)


def _allowed_buyer_intent_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "intent_name",
        "intent_grade",
        "status",
        "pause_reason",
        "contact_name",
        "contact_info_json",
        "raw_requirement_text",
        "intent_summary",
        "parsed_requirement_json",
        "industry_primary",
        "industry_secondary",
        "industries_json",
        "excluded_industries_json",
        "industry_focus_tags_json",
        "region_scope_summary",
        "region_constraints_json",
        "min_revenue_yuan",
        "min_net_profit_yuan",
        "min_total_profit_yuan",
        "max_pe",
        "max_ps",
        "min_net_margin",
        "min_gross_margin",
        "min_valuation_yuan",
        "max_valuation_yuan",
        "min_market_cap_yuan",
        "max_market_cap_yuan",
        "market_cap_range_summary",
        "industry_l2_json",
        "budget_min_yuan",
        "budget_max_yuan",
        "acceptable_cash_flow_status_json",
        "acceptable_profitability_status_json",
        "requires_relocation",
        "relocation_target_regions_json",
        "requires_return_investment",
        "return_investment_multiple",
        "requires_team_retention",
        "earnout_requirement",
        "listing_market_region",
        "requires_control",
        "requires_consolidation",
        "accepts_minority_investment",
        "desired_equity_ratio_min",
        "desired_equity_ratio_max",
        "equity_ratio_summary",
        "equity_requirement_type",
        "acceptable_control_paths_json",
        "preferred_listed_status",
        "acceptable_listed_status_json",
        "condition_effects_json",
        "listing_board_requirement_summary",
        "financing_stage_requirement_summary",
        "transaction_type",
        "transaction_types_json",
        "premium_tolerance_summary",
        "max_premium_rate",
        "max_debt_ratio",
        "debt_ratio_requirement_summary",
        "major_risk_tolerance_summary",
        "unacceptable_risk_flags_json",
        "buyer_industry_advantage_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _allowed_relation_changes(changes: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {
        "status",
        "status_reason",
        "first_recommended_at",
        "last_contact_at",
        "last_event_at",
        "last_event_summary",
    }
    return {key: value for key, value in changes.items() if key in allowed_fields}


def _insert_relation_event(
    db: Session,
    action: dict[str, Any],
    relation_id: UUID,
    buyer_intent_id: UUID,
    seller_target_id: UUID,
    buyer_party_id: UUID | None,
    changes: dict[str, Any],
    *,
    actor_user_id: UUID,
) -> None:
    event_type = changes.get("event_type") or _event_type_from_relation_status(changes.get("status"))
    db.execute(
        text(
            """
            insert into relation_event (
              team_id, workspace_id, relation_id, buyer_intent_id, buyer_party_id,
              seller_target_id, event_type, event_time, title, content, next_step,
              source_type, source_id, metadata_json, created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :relation_id, :buyer_intent_id, :buyer_party_id,
              :seller_target_id, :event_type, now(), :title, :content, :next_step,
              'extracted_action', :source_id, :metadata_json, :created_by, :updated_by
            )
            """
        ).bindparams(bindparam("metadata_json", type_=JSONB)),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "relation_id": relation_id,
            "buyer_intent_id": buyer_intent_id,
            "buyer_party_id": buyer_party_id,
            "seller_target_id": seller_target_id,
            "event_type": event_type,
            "title": changes.get("event_title") or changes.get("status_reason"),
            "content": _relation_event_content(changes, action),
            "next_step": changes.get("next_step"),
            "source_id": action["id"],
            "metadata_json": {
                "business_update_id": str(action["business_update_id"]),
                "raw_evidence_text": action.get("raw_evidence_text"),
            },
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
        },
    )


def _event_type_from_relation_status(status_value: Any) -> str:
    if status_value == "recommended":
        return "recommended"
    if status_value == "interested":
        return "buyer_interested"
    if status_value == "not_interested":
        return "buyer_not_interested"
    if status_value == "due_diligence":
        return "due_diligence_started"
    if status_value == "deal_closed":
        return "deal_closed"
    if status_value == "paused":
        return "paused"
    return "other"


def _relation_event_content(changes: dict[str, Any], action: dict[str, Any]) -> str:
    return (
        changes.get("event_content")
        or changes.get("last_event_summary")
        or changes.get("status_reason")
        or action.get("raw_evidence_text")
        or ""
    )


def _required_uuid(value: Any, field_name: str) -> UUID:
    parsed = _optional_uuid(value)
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} is required.")
    return parsed


def _action_source_context(action: dict[str, Any], *, default_source_label: str) -> dict[str, Any]:
    metadata = action.get("metadata_json") if isinstance(action.get("metadata_json"), dict) else {}
    evidence_id = action.get("evidence_id") or _optional_uuid(metadata.get("evidence_id"))
    return {
        "source_type": "extracted_action",
        "source_id": action["id"],
        "source_label": metadata.get("source_label") or default_source_label,
        "business_update_id": action["business_update_id"],
        "extracted_action_id": action["id"],
        "evidence_id": evidence_id,
        "confidence": action.get("confidence"),
        "raw_evidence_text": action.get("raw_evidence_text"),
        "action_type": action.get("action_type"),
    }


def _optional_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _mark_action_applied(
    db: Session,
    extracted_action_id: UUID,
    *,
    review_status: str | None = None,
) -> None:
    review_status_clause = ""
    if review_status:
        review_status_clause = ", review_status = :review_status, reviewed_by = :reviewed_by, reviewed_at = now()"
    db.execute(
        text(
            f"""
            update extracted_action
            set applied_at = now(){review_status_clause}
            where id = :extracted_action_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "extracted_action_id": extracted_action_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "review_status": review_status,
            "reviewed_by": SYSTEM_USER_ID,
        },
    )


def _refresh_business_update_status(db: Session, business_update_id: UUID) -> None:
    pending_count = db.execute(
        text(
            """
            select count(*)
            from extracted_action
            where business_update_id = :business_update_id
              and applied_at is null
              and review_status in ('pending_review', 'accepted', 'auto_accepted')
            """
        ),
        {"business_update_id": business_update_id},
    ).scalar_one()
    new_status = "applied" if int(pending_count) == 0 else "partially_applied"
    db.execute(
        text(
            """
            update business_update
            set processing_status = :processing_status
            where id = :business_update_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ),
        {
            "processing_status": new_status,
            "business_update_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    )
