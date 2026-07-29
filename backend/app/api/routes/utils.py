from decimal import Decimal
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.constants import DEFAULT_ADMIN_USER_ID, DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value


def write_action_log(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    field_path: str,
    old_value: Any,
    new_value: Any,
    source_type: str = "direct_api",
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
    applied_by: UUID | None = None,
) -> None:
    statement = text(
        """
        insert into action_application_log (
          team_id, workspace_id, entity_type, entity_id, field_path,
          old_value_json, new_value_json, source_type, source_id, evidence_id,
          business_update_id, extracted_action_id, applied_by, edited_before_apply,
          metadata_json
        )
        values (
          :team_id, :workspace_id, :entity_type, :entity_id, :field_path,
          :old_value_json, :new_value_json,
          :source_type, :source_id, :evidence_id,
          :business_update_id, :extracted_action_id, :applied_by, false,
          :metadata_json
        )
        """
    ).bindparams(
        bindparam("old_value_json", type_=JSONB),
        bindparam("new_value_json", type_=JSONB),
        bindparam("metadata_json", type_=JSONB),
    )

    db.execute(
        statement,
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "field_path": field_path,
            "old_value_json": json_safe(old_value),
            "new_value_json": json_safe(new_value),
            "source_type": source_type,
            "source_id": source_id,
            "evidence_id": evidence_id,
            "business_update_id": business_update_id,
            "extracted_action_id": extracted_action_id,
            "applied_by": applied_by or DEFAULT_ADMIN_USER_ID,
            "metadata_json": json_safe(metadata_json or {}),
        },
    )


def diff_payload(original: dict[str, Any], changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    diff: dict[str, tuple[Any, Any]] = {}
    for key, new_value in changes.items():
        old_value = original.get(key)
        if json_safe(old_value) != json_safe(new_value):
            diff[key] = (old_value, new_value)
    return diff


def write_action_logs_for_diff(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    diff: dict[str, tuple[Any, Any]],
    source_type: str = "direct_api",
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extracted_action_id: UUID | None = None,
    metadata_json: dict[str, Any] | None = None,
    applied_by: UUID | None = None,
) -> None:
    for field_path, (old_value, new_value) in diff.items():
        write_action_log(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            field_path=field_path,
            old_value=old_value,
            new_value=new_value,
            source_type=source_type,
            source_id=source_id,
            evidence_id=evidence_id,
            business_update_id=business_update_id,
            extracted_action_id=extracted_action_id,
            metadata_json=metadata_json,
            applied_by=applied_by,
        )


def owner_filter_condition(
    owner: str | None,
    *,
    column: str = "owner_user_id",
) -> tuple[str, UUID | None] | None:
    """Parse a list-endpoint owner filter: a user UUID or the literal 'unassigned'."""
    if not owner:
        return None
    if owner == "unassigned":
        return (f"{column} is null", None)
    try:
        return (f"{column} = :owner_user_id", UUID(owner))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无效的负责人筛选值。",
        ) from exc


def ensure_active_user(db: Session, user_id: UUID) -> None:
    row = db.execute(
        text("select 1 from app_user where id = :user_id and status = 'active'"),
        {"user_id": user_id},
    ).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="指定的负责人不存在或已停用。",
        )


def owner_filter_options(db: Session, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Owner filter choices for a list page: one row per owner plus 'unassigned'."""
    rows = db.execute(
        text(
            f"""
            select
              coalesce(t.owner_user_id::text, 'unassigned') as value,
              coalesce(au.name, '未指派') as label,
              count(*) as count
            from {table} t
            left join app_user au on au.id = t.owner_user_id
            where t.team_id = :team_id
              and t.workspace_id = :workspace_id
              and t.deleted_at is null
            group by t.owner_user_id, au.name
            order by count desc, label asc
            """
        ),
        params,
    ).mappings().all()
    return [
        {"value": row["value"], "label": row["label"], "count": int(row["count"])}
        for row in rows
    ]


def owner_scope_required(current_user: Any) -> bool:
    return bool(get_settings().owner_scope_enforced and not current_user.is_admin)


def scoped_params(params: dict[str, Any], current_user: Any) -> dict[str, Any]:
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
    return params


def append_owner_scope(
    where: list[str],
    params: dict[str, Any],
    current_user: Any,
    *,
    entity_type: str,
    alias: str,
) -> None:
    if not owner_scope_required(current_user):
        return
    where.append(owner_scope_sql(entity_type, alias))
    params["scope_user_id"] = current_user.user_id


def append_visible_scope(
    where: list[str],
    params: dict[str, Any],
    current_user: Any,
    *,
    entity_type: str,
    alias: str,
) -> None:
    if not owner_scope_required(current_user):
        return
    where.append(visible_scope_sql(entity_type, alias))
    params["scope_user_id"] = current_user.user_id


def owner_scope_sql(entity_type: str, alias: str) -> str:
    if entity_type == "seller_target":
        return f"{alias}.owner_user_id = :scope_user_id"
    if entity_type == "buyer_intent":
        return f"{alias}.owner_user_id = :scope_user_id"
    if entity_type == "buyer_party":
        # A consultant may need the buyer shell for an intent they own, even
        # when the buyer_party owner differs from the intent owner.
        return f"""(
            {alias}.owner_user_id = :scope_user_id
            or exists (
              select 1
              from buyer_intent scope_bi
              where scope_bi.buyer_party_id = {alias}.id
                and scope_bi.owner_user_id = :scope_user_id
                and scope_bi.deleted_at is null
            )
        )"""
    raise ValueError(f"Unsupported owner scope entity_type: {entity_type}")


def visible_scope_sql(entity_type: str, alias: str) -> str:
    owner_sql = owner_scope_sql(entity_type, alias)
    if entity_type == "seller_target":
        return f"""(
            {owner_sql}
            or exists (
              select 1
              from buyer_seller_relation scope_r
              join buyer_intent scope_bi
                on scope_bi.id = scope_r.buyer_intent_id
               and scope_bi.deleted_at is null
              left join buyer_party scope_bp
                on scope_bp.id = coalesce(scope_r.buyer_party_id, scope_bi.buyer_party_id)
               and scope_bp.deleted_at is null
              where scope_r.seller_target_id = {alias}.id
                and scope_r.deleted_at is null
                and (
                  scope_bi.owner_user_id = :scope_user_id
                  or scope_bp.owner_user_id = :scope_user_id
                )
            )
        )"""
    if entity_type == "buyer_intent":
        return f"""(
            {owner_sql}
            or exists (
              select 1
              from buyer_seller_relation scope_r
              join seller_target scope_st
                on scope_st.id = scope_r.seller_target_id
               and scope_st.deleted_at is null
              where scope_r.buyer_intent_id = {alias}.id
                and scope_r.deleted_at is null
                and scope_st.owner_user_id = :scope_user_id
            )
        )"""
    if entity_type == "buyer_party":
        return f"""(
            {owner_sql}
            or exists (
              select 1
              from buyer_seller_relation scope_r
              join seller_target scope_st
                on scope_st.id = scope_r.seller_target_id
               and scope_st.deleted_at is null
              left join buyer_intent scope_bi
                on scope_bi.id = scope_r.buyer_intent_id
               and scope_bi.deleted_at is null
              where coalesce(scope_r.buyer_party_id, scope_bi.buyer_party_id) = {alias}.id
                and scope_r.deleted_at is null
                and scope_st.owner_user_id = :scope_user_id
            )
        )"""
    raise ValueError(f"Unsupported visible scope entity_type: {entity_type}")


def business_update_visible_sql(alias: str) -> str:
    return f"""(
        {alias}.created_by = :scope_user_id
        or exists (
          select 1
          from seller_target scope_st
          where scope_st.id::text in (
            select jsonb_array_elements_text({alias}.bound_seller_target_ids_json)
          )
            and scope_st.owner_user_id = :scope_user_id
            and scope_st.deleted_at is null
        )
        or exists (
          select 1
          from buyer_party scope_bp
          where scope_bp.id::text in (
            select jsonb_array_elements_text({alias}.bound_buyer_party_ids_json)
          )
            and scope_bp.owner_user_id = :scope_user_id
            and scope_bp.deleted_at is null
        )
        or exists (
          select 1
          from buyer_intent scope_bi
          where scope_bi.id::text in (
            select jsonb_array_elements_text({alias}.bound_buyer_intent_ids_json)
          )
            and scope_bi.owner_user_id = :scope_user_id
            and scope_bi.deleted_at is null
        )
        or exists (
          select 1
          from recommendation_session scope_rs
          left join buyer_intent scope_bi on scope_bi.id = scope_rs.buyer_intent_id
          left join buyer_party scope_bp on scope_bp.id = coalesce(scope_rs.buyer_party_id, scope_bi.buyer_party_id)
          left join seller_target scope_st on scope_st.id = scope_rs.seller_target_id
          where scope_rs.id = {alias}.bound_recommendation_session_id
            and (
              scope_rs.created_by = :scope_user_id
              or scope_bi.owner_user_id = :scope_user_id
              or scope_bp.owner_user_id = :scope_user_id
              or scope_st.owner_user_id = :scope_user_id
            )
        )
    )"""


def relation_visible_sql(alias: str) -> str:
    return f"""(
        exists (
          select 1
          from seller_target scope_st
          where scope_st.id = {alias}.seller_target_id
            and scope_st.owner_user_id = :scope_user_id
            and scope_st.deleted_at is null
        )
        or exists (
          select 1
          from buyer_intent scope_bi
          where scope_bi.id = {alias}.buyer_intent_id
            and scope_bi.owner_user_id = :scope_user_id
            and scope_bi.deleted_at is null
        )
        or exists (
          select 1
          from buyer_party scope_bp
          where scope_bp.id = coalesce(
                {alias}.buyer_party_id,
                (select scope_bi2.buyer_party_id from buyer_intent scope_bi2 where scope_bi2.id = {alias}.buyer_intent_id)
              )
            and scope_bp.owner_user_id = :scope_user_id
            and scope_bp.deleted_at is null
        )
    )"""


def relation_sole_owner_sql(alias: str) -> str:
    """看板「我全权的」视图筛选：标的侧与买家侧都归当前用户。

    与 relation_visible_sql 是 AND / OR 的关系，共用 :scope_user_id。
    这是**视图筛选**，不是权限收紧——权限地板仍由 relation_visible_sql
    在 owner_scope_enforced 打开时负责。因为 sole ⊆ involved，两者同时
    出现时不会互相矛盾。
    """
    return f"""(
        exists (
          select 1
          from seller_target sole_st
          where sole_st.id = {alias}.seller_target_id
            and sole_st.owner_user_id = :scope_user_id
            and sole_st.deleted_at is null
        )
        and (
          exists (
            select 1
            from buyer_intent sole_bi
            where sole_bi.id = {alias}.buyer_intent_id
              and sole_bi.owner_user_id = :scope_user_id
              and sole_bi.deleted_at is null
          )
          or exists (
            select 1
            from buyer_party sole_bp
            where sole_bp.id = coalesce(
                  {alias}.buyer_party_id,
                  (select sole_bi2.buyer_party_id from buyer_intent sole_bi2 where sole_bi2.id = {alias}.buyer_intent_id)
                )
              and sole_bp.owner_user_id = :scope_user_id
              and sole_bp.deleted_at is null
          )
        )
    )"""


def relation_owner_sql(alias: str) -> str:
    """看板「指定负责人」视图筛选：任一方归 :owner_user_id 指定的账号。

    与 relation_visible_sql 谓词同形，但用**独立参数**——两者可以同时出现
    （管理员挑了某人，同时 owner_scope_enforced 又对非管理员生效），共用
    一个参数名会让后写的值覆盖前一个，把权限地板悄悄改成视图筛选。
    """
    return f"""(
        exists (
          select 1
          from seller_target owner_st
          where owner_st.id = {alias}.seller_target_id
            and owner_st.owner_user_id = :owner_user_id
            and owner_st.deleted_at is null
        )
        or exists (
          select 1
          from buyer_intent owner_bi
          where owner_bi.id = {alias}.buyer_intent_id
            and owner_bi.owner_user_id = :owner_user_id
            and owner_bi.deleted_at is null
        )
        or exists (
          select 1
          from buyer_party owner_bp
          where owner_bp.id = coalesce(
                {alias}.buyer_party_id,
                (select owner_bi2.buyer_party_id from buyer_intent owner_bi2 where owner_bi2.id = {alias}.buyer_intent_id)
              )
            and owner_bp.owner_user_id = :owner_user_id
            and owner_bp.deleted_at is null
        )
    )"""


def relation_event_visible_sql(alias: str) -> str:
    return f"""(
        exists (
          select 1
          from buyer_seller_relation scope_r
          where scope_r.id = {alias}.relation_id
            and scope_r.deleted_at is null
            and {relation_visible_sql("scope_r")}
        )
        or exists (
          select 1
          from seller_target scope_st
          where scope_st.id = {alias}.seller_target_id
            and scope_st.owner_user_id = :scope_user_id
            and scope_st.deleted_at is null
        )
        or exists (
          select 1
          from buyer_intent scope_bi
          where scope_bi.id = {alias}.buyer_intent_id
            and scope_bi.owner_user_id = :scope_user_id
            and scope_bi.deleted_at is null
        )
        or exists (
          select 1
          from buyer_party scope_bp
          where scope_bp.id = {alias}.buyer_party_id
            and scope_bp.owner_user_id = :scope_user_id
            and scope_bp.deleted_at is null
        )
    )"""


def exclusion_visible_sql(alias: str) -> str:
    return f"""(
        exists (
          select 1
          from seller_target scope_st
          where scope_st.id = {alias}.seller_target_id
            and scope_st.owner_user_id = :scope_user_id
            and scope_st.deleted_at is null
        )
        or exists (
          select 1
          from buyer_intent scope_bi
          where scope_bi.id = {alias}.buyer_intent_id
            and scope_bi.owner_user_id = :scope_user_id
            and scope_bi.deleted_at is null
        )
        or exists (
          select 1
          from buyer_party scope_bp
          where scope_bp.id = {alias}.buyer_party_id
            and scope_bp.owner_user_id = :scope_user_id
            and scope_bp.deleted_at is null
        )
    )"""


def recommendation_session_visible_sql(alias: str) -> str:
    return f"""(
        {alias}.created_by = :scope_user_id
        or exists (
          select 1 from buyer_intent scope_bi
          where scope_bi.id = {alias}.buyer_intent_id
            and scope_bi.owner_user_id = :scope_user_id
            and scope_bi.deleted_at is null
        )
        or exists (
          select 1 from buyer_party scope_bp
          where scope_bp.id = {alias}.buyer_party_id
            and scope_bp.owner_user_id = :scope_user_id
            and scope_bp.deleted_at is null
        )
        or exists (
          select 1 from seller_target scope_st
          where scope_st.id = {alias}.seller_target_id
            and scope_st.owner_user_id = :scope_user_id
            and scope_st.deleted_at is null
        )
    )"""


def recommendation_report_visible_sql(alias: str) -> str:
    return f"""exists (
        select 1
        from recommendation_session scope_rs
        where scope_rs.id = {alias}.session_id
          and {recommendation_session_visible_sql("scope_rs")}
    )"""


def extracted_action_visible_sql(alias: str) -> str:
    return f"""(
        exists (
          select 1
          from business_update scope_bu
          where scope_bu.id = {alias}.business_update_id
            and scope_bu.team_id = :team_id
            and scope_bu.workspace_id = :workspace_id
            and {business_update_visible_sql("scope_bu")}
        )
        or (
          {alias}.target_entity_type = 'seller_target'
          and exists (
            select 1 from seller_target scope_st
            where scope_st.id = {alias}.target_entity_id
              and scope_st.deleted_at is null
              and {visible_scope_sql("seller_target", "scope_st")}
          )
        )
        or (
          {alias}.target_entity_type = 'buyer_intent'
          and exists (
            select 1 from buyer_intent scope_bi
            where scope_bi.id = {alias}.target_entity_id
              and scope_bi.deleted_at is null
              and {visible_scope_sql("buyer_intent", "scope_bi")}
          )
        )
        or (
          {alias}.target_entity_type = 'buyer_party'
          and exists (
            select 1 from buyer_party scope_bp
            where scope_bp.id = {alias}.target_entity_id
              and scope_bp.deleted_at is null
              and {visible_scope_sql("buyer_party", "scope_bp")}
          )
        )
        or (
          {alias}.target_entity_type = 'buyer_seller_relation'
          and exists (
            select 1 from buyer_seller_relation scope_r
            where scope_r.id = {alias}.target_entity_id
              and scope_r.deleted_at is null
              and {relation_visible_sql("scope_r")}
          )
        )
    )"""


def attachment_visible_sql(alias: str) -> str:
    return f"""(
        {alias}.uploaded_by = :scope_user_id
        or exists (
          select 1
          from attachment_link scope_al
          where scope_al.attachment_id = {alias}.id
            and scope_al.team_id = {alias}.team_id
            and scope_al.workspace_id = {alias}.workspace_id
            and (
              (
                scope_al.entity_type = 'seller_target'
                and exists (
                  select 1 from seller_target scope_st
                  where scope_st.id = scope_al.entity_id
                    and scope_st.deleted_at is null
                    and {visible_scope_sql("seller_target", "scope_st")}
                )
              )
              or (
                scope_al.entity_type = 'buyer_intent'
                and exists (
                  select 1 from buyer_intent scope_bi
                  where scope_bi.id = scope_al.entity_id
                    and scope_bi.deleted_at is null
                    and {visible_scope_sql("buyer_intent", "scope_bi")}
                )
              )
              or (
                scope_al.entity_type = 'buyer_party'
                and exists (
                  select 1 from buyer_party scope_bp
                  where scope_bp.id = scope_al.entity_id
                    and scope_bp.deleted_at is null
                    and {visible_scope_sql("buyer_party", "scope_bp")}
                )
              )
              or (
                scope_al.entity_type = 'business_update'
                and exists (
                  select 1 from business_update scope_bu
                  where scope_bu.id = scope_al.entity_id
                    and scope_bu.team_id = :team_id
                    and scope_bu.workspace_id = :workspace_id
                    and {business_update_visible_sql("scope_bu")}
                )
              )
              or (
                scope_al.entity_type = 'recommendation_session'
                and exists (
                  select 1 from recommendation_session scope_rs
                  where scope_rs.id = scope_al.entity_id
                    and {recommendation_session_visible_sql("scope_rs")}
                )
              )
              or (
                scope_al.entity_type = 'recommendation_report'
                and exists (
                  select 1 from recommendation_report scope_rr
                  where scope_rr.id = scope_al.entity_id
                    and {recommendation_report_visible_sql("scope_rr")}
                )
              )
            )
        )
    )"""


def ensure_entity_visible(
    db: Session,
    current_user: Any,
    *,
    entity_type: str,
    entity_id: UUID,
) -> None:
    _ensure_scoped_entity(db, current_user, entity_type=entity_type, entity_id=entity_id, access="visible")


def ensure_entity_writable(
    db: Session,
    current_user: Any,
    *,
    entity_type: str,
    entity_id: UUID,
) -> None:
    _ensure_scoped_entity(db, current_user, entity_type=entity_type, entity_id=entity_id, access="owner")


def ensure_business_update_visible(db: Session, current_user: Any, business_update_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from business_update bu
            where bu.id = :entity_id
              and bu.team_id = :team_id
              and bu.workspace_id = :workspace_id
              and {business_update_visible_sql("bu")}
            """
        ),
        {
            "entity_id": business_update_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business update not found.")


def ensure_relation_visible(db: Session, current_user: Any, relation_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from buyer_seller_relation r
            where r.id = :relation_id
              and r.team_id = :team_id
              and r.workspace_id = :workspace_id
              and r.deleted_at is null
              and {relation_visible_sql("r")}
            """
        ),
        {
            "relation_id": relation_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relation not found.")


def ensure_recommendation_session_visible(db: Session, current_user: Any, session_id: UUID) -> None:
    if not owner_scope_required(current_user):
        return
    row = db.execute(
        text(
            f"""
            select 1
            from recommendation_session rs
            where rs.id = :session_id
              and rs.team_id = :team_id
              and rs.workspace_id = :workspace_id
              and {recommendation_session_visible_sql("rs")}
            """
        ),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation session not found.")


def _ensure_scoped_entity(
    db: Session,
    current_user: Any,
    *,
    entity_type: str,
    entity_id: UUID,
    access: str,
) -> None:
    if not owner_scope_required(current_user):
        return
    table_alias = {
        "seller_target": ("seller_target", "st"),
        "buyer_party": ("buyer_party", "bp"),
        "buyer_intent": ("buyer_intent", "bi"),
    }.get(entity_type)
    if table_alias is None:
        raise ValueError(f"Unsupported scoped entity_type: {entity_type}")
    table, alias = table_alias
    if access == "owner" and entity_type == "buyer_party":
        scope_sql = f"{alias}.owner_user_id = :scope_user_id"
    else:
        scope_sql = owner_scope_sql(entity_type, alias) if access == "owner" else visible_scope_sql(entity_type, alias)
    row = db.execute(
        text(
            f"""
            select 1
            from {table} {alias}
            where {alias}.id = :entity_id
              and {alias}.team_id = :team_id
              and {alias}.workspace_id = :workspace_id
              and {alias}.deleted_at is null
              and {scope_sql}
            """
        ),
        {
            "entity_id": entity_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "scope_user_id": current_user.user_id,
        },
    ).first()
    if row is None:
        if access == "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not the owner of this entity.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found.")


def assign_owner_bulk(
    db: Session,
    *,
    table: str,
    entity_type: str,
    entity_ids: list[UUID],
    new_owner_user_id: UUID | None,
    actor_user_id: UUID,
) -> list[UUID]:
    """Reassign owner on the given rows and log each change to action_application_log."""
    if not entity_ids:
        return []
    rows = db.execute(
        text(
            f"""
            select id, owner_user_id
            from {table}
            where id in :entity_ids
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "entity_ids": entity_ids,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().all()
    changed = [row for row in rows if row["owner_user_id"] != new_owner_user_id]
    if not changed:
        return []

    changed_ids = [row["id"] for row in changed]
    db.execute(
        text(
            f"""
            update {table}
            set owner_user_id = :owner_user_id, updated_at = now(), updated_by = :updated_by
            where id in :entity_ids
            """
        ).bindparams(bindparam("entity_ids", expanding=True)),
        {
            "owner_user_id": new_owner_user_id,
            "updated_by": actor_user_id,
            "entity_ids": changed_ids,
        },
    )
    for row in changed:
        write_action_log(
            db,
            entity_type=entity_type,
            entity_id=row["id"],
            field_path="owner_user_id",
            old_value=row["owner_user_id"],
            new_value=new_owner_user_id,
            source_type="owner_assignment",
            applied_by=actor_user_id,
        )
    return changed_ids


def write_field_value_sources_for_diff(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    changes: dict[str, Any],
    diff: dict[str, tuple[Any, Any]],
    source_type: str,
    source_id: UUID | None = None,
    evidence_id: UUID | None = None,
    source_label: str | None = None,
    confidence: Any = None,
    review_status: str = "auto_accepted",
    source_context: dict[str, Any] | None = None,
    created_by: UUID | None = None,
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
                    "value": json_safe(changes.get(field_path)),
                    "source_context": json_safe(source_context or {}),
                },
                "source_type": source_type,
                "source_id": source_id,
                "evidence_id": evidence_id,
                "source_label": source_label,
                "confidence": confidence,
                "review_status": review_status,
                "created_by": created_by or DEFAULT_ADMIN_USER_ID,
            },
        )
