"""Aggregate counts for the 数据看板 (inventory picture).

Deliberately **not** owner-scoped and deliberately status-agnostic: the board
is an inventory portrait for the internal big screen and one-on-one client
demos, so it answers "what does the whole book look like" rather than "what is
mine". That is also why nothing here returns a name — only counts leave this
module, so showing the board to a client cannot leak a target or a buyer.
"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.authn import CurrentUser
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.db import get_db

router = APIRouter(prefix="/stats", tags=["stats"])

# 二级行业只取前 N 名。生产现在有 28 个不同的 L2，全画出来是一条长尾，
# 尾部清一色 1 个，读不出任何东西。
INDUSTRY_TOP_N = 10

# 营收分档。阈值写死而不是按当前最大值分位，理由同地图着色：同一个档位在两次
# 打开之间含义必须不变。(key, 中文名, 上界(不含)，最后一档为 None 表示无上界)
REVENUE_BUCKETS: tuple[tuple[str, str, int | None], ...] = (
    ("lt_50m", "5000万以下", 50_000_000),
    ("50m_100m", "0.5–1亿", 100_000_000),
    ("100m_300m", "1–3亿", 300_000_000),
    ("300m_500m", "3–5亿", 500_000_000),
    ("500m_1b", "5–10亿", 1_000_000_000),
    ("gte_1b", "10亿以上", None),
)


def _revenue_bucket_case() -> str:
    """由 REVENUE_BUCKETS 生成 CASE，档位定义只有一份。"""
    branches = [
        f"when current_revenue_yuan < {upper} then {index}"
        for index, (_, _, upper) in enumerate(REVENUE_BUCKETS)
        if upper is not None
    ]
    return "case " + " ".join(branches) + f" else {len(REVENUE_BUCKETS) - 1} end"


@router.get("/overview")
def platform_overview(current_user: CurrentUser, db: Session = Depends(get_db)) -> dict[str, Any]:
    """标的与买家主体的存量画像。

    ``industries`` 是「标的数 per 二级行业」，一个标的挂两个不同 L2 会在两边各计
    一次，所以各项之和大于 total。地区与营收分档没有这种重叠——一个标的只有一个
    省、一个营收值。
    """
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}

    totals = db.execute(
        text(
            """
            select
              now()::text as generated_at,
              count(*) as total,
              count(*) filter (where nullif(location_province, '') is null) as province_unknown,
              count(*) filter (
                where not exists (
                  select 1
                  from jsonb_array_elements(coalesce(industry_pairs_json, '[]'::jsonb)) pair
                  where coalesce(pair ->> 'l2', '') <> ''
                )
              ) as industry_unknown,
              count(*) filter (where current_revenue_yuan is null) as revenue_unknown
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        params,
    ).mappings().one()

    province_rows = db.execute(
        text(
            """
            select nullif(location_province, '') as province, count(*) as count
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and nullif(location_province, '') is not null
            group by province
            order by count desc, province
            """
        ),
        params,
    ).mappings().all()

    industry_rows = db.execute(
        text(
            """
            with target_l2 as (
              select distinct
                seller_target.id as target_id,
                pair ->> 'l2' as l2
              from seller_target
              cross join lateral jsonb_array_elements(industry_pairs_json) pair
              where team_id = :team_id
                and workspace_id = :workspace_id
                and deleted_at is null
                and coalesce(pair ->> 'l2', '') <> ''
            )
            select l2, count(*) as count
            from target_l2
            group by l2
            order by count desc, l2
            """
        ),
        params,
    ).mappings().all()

    revenue_rows = db.execute(
        text(
            f"""
            select {_revenue_bucket_case()} as bucket_index, count(*) as count
            from seller_target
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and current_revenue_yuan is not null
            group by bucket_index
            """
        ),
        params,
    ).mappings().all()
    counted_buckets = {int(row["bucket_index"]): int(row["count"]) for row in revenue_rows}

    buyer_totals = db.execute(
        text(
            """
            select
              count(*) as total,
              count(*) filter (where nullif(location_province, '') is null) as province_unknown
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        params,
    ).mappings().one()

    buyer_province_rows = db.execute(
        text(
            """
            select nullif(location_province, '') as province, count(*) as count
            from buyer_party
            where team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
              and nullif(location_province, '') is not null
            group by province
            order by count desc, province
            """
        ),
        params,
    ).mappings().all()

    return {
        # 取服务端时间而不是浏览器时间：大屏可能整天不刷新，这一栏是用来判断
        # 「屏上这份数还新不新」的，用客户端时钟就自证不了。
        "generated_at": totals["generated_at"],
        "targets": {
            "total": int(totals["total"]),
            "provinces": [
                {"province": row["province"], "count": int(row["count"])} for row in province_rows
            ],
            "province_unknown_count": int(totals["province_unknown"]),
            "industries": [
                {"l2": row["l2"], "count": int(row["count"])}
                for row in industry_rows[:INDUSTRY_TOP_N]
            ],
            # 榜外还有多少个二级行业。页面要说出来，否则 top 10 会被读成全部。
            "industry_other_count": max(len(industry_rows) - INDUSTRY_TOP_N, 0),
            "industry_unknown_count": int(totals["industry_unknown"]),
            # 空档位也要出现，否则条形图会把「这一档一个都没有」画成「这一档不存在」。
            "revenue_buckets": [
                {"key": key, "label": label, "count": counted_buckets.get(index, 0)}
                for index, (key, label, _) in enumerate(REVENUE_BUCKETS)
            ],
            "revenue_unknown_count": int(totals["revenue_unknown"]),
        },
        "buyers": {
            "total": int(buyer_totals["total"]),
            "provinces": [
                {"province": row["province"], "count": int(row["count"])}
                for row in buyer_province_rows
            ],
            "province_unknown_count": int(buyer_totals["province_unknown"]),
        },
    }
