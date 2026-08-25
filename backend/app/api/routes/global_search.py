from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.api.routes.utils import owner_scope_required, owner_scope_sql
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/search", tags=["search"])


class GlobalSearchItemOut(BaseModel):
    entity_type: str
    entity_id: str
    title: str
    subtitle: str | None = None
    snippet: str | None = None
    route: str
    updated_at: str | None = None
    match_reason: str | None = None
    metadata: dict[str, Any]


class GlobalSearchGroupOut(BaseModel):
    key: str
    label: str
    count: int
    items: list[GlobalSearchItemOut]


class GlobalSearchOut(BaseModel):
    query: str
    groups: list[GlobalSearchGroupOut]
    total_count: int


@router.get("", response_model=GlobalSearchOut)
def global_search(
    current_user: CurrentUser,
    q: str = Query(min_length=1, max_length=200),
    limit_per_type: int = Query(default=8, ge=1, le=30),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"query": query, "groups": [], "total_count": 0}

    params = {
        "team_id": DEFAULT_TEAM_ID,
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "q": f"%{query}%",
        "q_prefix": f"{query}%",
        "q_plain": query,
        "limit": limit_per_type,
    }
    if owner_scope_required(current_user):
        params["scope_user_id"] = current_user.user_id
    groups = [
        _search_seller_targets(db, params, current_user),
        _search_buyer_parties(db, params, current_user),
        _search_buyer_intents(db, params, current_user),
    ]
    return {
        "query": query,
        "groups": groups,
        "total_count": sum(group["count"] for group in groups),
    }


def _search_seller_targets(db: Session, params: dict[str, Any], current_user: Any) -> dict[str, Any]:
    scope_clause = ""
    if owner_scope_required(current_user):
        scope_clause = f"and {owner_scope_sql('seller_target', 'seller_target')}"
    rows = db.execute(
        text(
            f"""
            select
              'seller_target' as entity_type,
              id::text as entity_id,
              target_name as title,
              nullif(concat_ws(' · ',
                (select string_agg(concat_ws(' / ', pair ->> 'l1', pair ->> 'l2'), '；')
                 from jsonb_array_elements(industry_pairs_json) pair),
                location_province, location_city, location_district), '') as subtitle,
              business_summary as snippet,
              '/targets/' || id::text as route,
              updated_at::text as updated_at,
              case
                when lower(target_name) = lower(:q_plain) then '名称完全匹配'
                when target_name ilike :q_prefix then '名称前缀匹配'
                when business_summary ilike :q then '简介匹配'
                else '字段匹配'
              end as match_reason,
              jsonb_build_object(
                'industry_l1', industry_l1,
                'industry_l2', industry_l2,
                'industry_pairs_json', industry_pairs_json,
                'location_province', location_province,
                'location_city', location_city,
                'location_district', location_district,
                'listed_status', listed_status
              ) as metadata
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              {scope_clause}
              and (
                target_name ilike :q
                or coalesce(business_summary, '') ilike :q
                or industry_pairs_json::text ilike :q
                or coalesce(location_province, '') ilike :q
                or coalesce(location_city, '') ilike :q
                or coalesce(location_district, '') ilike :q
              )
            order by
              case
                when lower(target_name) = lower(:q_plain) then 0
                when target_name ilike :q_prefix then 1
                else 2
              end,
              updated_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return _group("seller_targets", "标的", rows)


def _search_buyer_parties(db: Session, params: dict[str, Any], current_user: Any) -> dict[str, Any]:
    scope_clause = ""
    if owner_scope_required(current_user):
        scope_clause = f"and {owner_scope_sql('buyer_party', 'buyer_party')}"
    rows = db.execute(
        text(
            f"""
            select
              'buyer_party' as entity_type,
              id::text as entity_id,
              buyer_name as title,
              nullif(concat_ws(' · ', location_province, location_city), '') as subtitle,
              coalesce(business_summary, contact_name, nullif(contact_info_json::text, '{{}}'), notes) as snippet,
              '/buyers/' || id::text as route,
              updated_at::text as updated_at,
              case
                when lower(buyer_name) = lower(:q_plain) then '名称完全匹配'
                when buyer_name ilike :q_prefix then '名称前缀匹配'
                when aliases_json::text ilike :q then '别名匹配'
                else '字段匹配'
              end as match_reason,
              jsonb_build_object(
                'aliases_json', aliases_json,
                'business_tags_json', business_tags_json,
                'ownership_type', ownership_type,
                'location_province', location_province,
                'location_city', location_city,
                'contact_name', contact_name
              ) as metadata
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              {scope_clause}
              and (
                buyer_name ilike :q
                or coalesce(aliases_json::text, '') ilike :q
                or coalesce(business_tags_json::text, '') ilike :q
                or coalesce(business_summary, '') ilike :q
                or coalesce(location_province, '') ilike :q
                or coalesce(location_city, '') ilike :q
                or coalesce(contact_name, '') ilike :q
                or coalesce(contact_info_json::text, '') ilike :q
                or coalesce(notes, '') ilike :q
              )
            order by
              case
                when lower(buyer_name) = lower(:q_plain) then 0
                when buyer_name ilike :q_prefix then 1
                else 2
              end,
              updated_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return _group("buyer_parties", "买家", rows)


def _search_buyer_intents(db: Session, params: dict[str, Any], current_user: Any) -> dict[str, Any]:
    scope_clause = ""
    if owner_scope_required(current_user):
        scope_clause = f"and {owner_scope_sql('buyer_intent', 'bi')}"
    rows = db.execute(
        text(
            f"""
            select
              'buyer_intent' as entity_type,
              bi.id::text as entity_id,
              bi.intent_name as title,
              nullif(concat_ws(' · ', bp.buyer_name, bi.industry_primary, bi.region_scope_summary), '') as subtitle,
              coalesce(bi.intent_summary, bi.raw_requirement_text) as snippet,
              case
                when bi.buyer_party_id is not null
                  then '/buyers/' || bi.buyer_party_id::text || '?intentId=' || bi.id::text
                else '/buyers?q=' || bi.intent_name
              end as route,
              bi.updated_at::text as updated_at,
              case
                when lower(bi.intent_name) = lower(:q_plain) then '意向名称完全匹配'
                when bi.intent_name ilike :q_prefix then '意向名称前缀匹配'
                when bp.buyer_name ilike :q then '买家名称匹配'
                else '字段匹配'
              end as match_reason,
              jsonb_build_object(
                'buyer_party_id', bi.buyer_party_id,
                'buyer_name', bp.buyer_name,
                'industry_primary', bi.industry_primary,
                'industry_secondary', bi.industry_secondary,
                'region_scope_summary', bi.region_scope_summary,
                'preferred_listed_status', bi.preferred_listed_status
              ) as metadata
            from buyer_intent bi
            left join buyer_party bp
              on bp.id = bi.buyer_party_id
             and bp.team_id = bi.team_id
             and bp.workspace_id = bi.workspace_id
             and bp.deleted_at is null
            where bi.team_id = :team_id
              and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              {scope_clause}
              and (
                bi.intent_name ilike :q
                or coalesce(bi.raw_requirement_text, '') ilike :q
                or coalesce(bi.intent_summary, '') ilike :q
                or coalesce(bi.industry_primary, '') ilike :q
                or coalesce(bi.industry_secondary, '') ilike :q
                or coalesce(bi.region_scope_summary, '') ilike :q
                or coalesce(bp.buyer_name, '') ilike :q
              )
            order by
              case
                when lower(bi.intent_name) = lower(:q_plain) then 0
                when bi.intent_name ilike :q_prefix then 1
                when bp.buyer_name ilike :q then 2
                else 3
              end,
              bi.updated_at desc
            limit :limit
            """
        ),
        params,
    ).mappings().all()
    return _group("buyer_intents", "买家意向", rows)


def _group(key: str, label: str, rows: Any) -> dict[str, Any]:
    items = [dict(row) for row in rows]
    return {
        "key": key,
        "label": label,
        "count": len(items),
        "items": items,
    }
