"""外部 Agent 看到的标的库：扫描 / 取档 / 筛选。

与买家侧镜像。筛选直接包 ``screening_sql.screen_targets``（站内推荐链路的 SQL 硬筛，
带缺失策略和逐条件淘汰拆分），扫描用它的业务扫描形状，取档照站内 Agent 的
``get_target_detail`` 投影再补上五组「其他」补充栏。闸门只有 ``_GATE_SQL`` 一处。
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column
from backend.app.services.business_tags import business_tags_text
from backend.app.services.profile_sections import load_profile_sections, render_profile_text
from backend.app.services.screening_sql import (
    _GATE_SQL,
    MAX_BUSINESS_SCAN_LIMIT,
    MAX_SCREENING_LIMIT,
    _row_digest,
    screen_targets,
)

GET_LIMIT = 20


def _enum_labels(column: str) -> dict[str, str]:
    try:
        options = indicator_by_column("seller_target", column).enum_options or ()
    except KeyError:
        options = ()
    return {code: label for code, label in options}


def _label(column: str, value: Any) -> str | None:
    if value in (None, "", "unknown"):
        return None
    return _enum_labels(column).get(str(value), str(value))


def _labels(column: str, values: Any) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    table = _enum_labels(column)
    return "、".join(table.get(str(item), str(item)) for item in values if item) or None


def _money(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if abs(amount) >= 1e8:
        return f"{amount / 1e8:.2f}".rstrip("0").rstrip(".") + "亿"
    if abs(amount) >= 1e4:
        return f"{amount / 1e4:.0f}万"
    return f"{amount:.0f}元"


def _ratio(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return None


def _region(row: dict[str, Any]) -> str | None:
    levels = [row.get("location_province"), row.get("location_city"), row.get("location_district")]
    return "".join(dict.fromkeys(str(level) for level in levels if level)) or None


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _date_text(value: Any) -> str | None:
    text_value = str(value or "").strip()
    return text_value[:19] or None


# ---------------------------------------------------------------- 扫描


def targets_scan(
    db: Session, *, limit: int = MAX_BUSINESS_SCAN_LIMIT, offset: int = 0
) -> dict[str, Any]:
    limit = max(1, min(int(limit or MAX_BUSINESS_SCAN_LIMIT), MAX_BUSINESS_SCAN_LIMIT))
    offset = max(0, int(offset or 0))
    params = {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID}
    total = db.execute(
        text(f"select count(*) from seller_target st where {_GATE_SQL}"), params
    ).scalar_one()
    rows = (
        db.execute(
            text(
                f"""
            select st.id, st.target_name, st.target_grade, st.business_tags_json,
                   st.location_province, st.location_city, st.location_district,
                   st.listed_status, st.business_summary, st.main_products_text,
                   st.updated_at::text as updated_at
            from seller_target st
            where {_GATE_SQL}
            order by st.target_grade asc, st.updated_at desc, st.id asc
            limit :limit offset :offset
            """
            ),
            {**params, "limit": limit, "offset": offset},
        )
        .mappings()
        .all()
    )
    returned = [
        _compact(
            {
                "seller_target_id": str(row["id"]),
                "标的名称": row.get("target_name"),
                "级别": row.get("target_grade"),
                "业务标签": business_tags_text(row.get("business_tags_json"), limit=8),
                "地区": _region(dict(row)),
                "上市状态": _label("listed_status", row.get("listed_status")),
                "业务摘要": (row.get("business_summary") or "").strip() or None,
                "主要产品": (row.get("main_products_text") or "").strip() or None,
                "更新时间": _date_text(row.get("updated_at")),
            }
        )
        for row in rows
    ]
    payload: dict[str, Any] = {
        "matched": int(total),
        "offset": offset,
        "returned": returned,
        "notes": [
            "这是全库业务扫描：每条只有业务标签、业务摘要和主要产品，没有财务数字。"
            "业务是否对口由你读文本判断，业务标签只是辅助；「业务标签」键不存在表示没录，不表示没有业务。",
            "业务摘要为空的标的不要从公司名猜业务，如实说信息不足。",
            "选出候选后用 target_get 取财务事实、交易条件、风险和五组补充说明。",
        ],
    }
    remaining = int(total) - offset - len(returned)
    if remaining > 0:
        payload["note"] = f"另有 {remaining} 家未返回，用 offset 翻页可以取到。"
    return payload


# ---------------------------------------------------------------- 取档

_DETAIL_COLUMNS = (
    "id",
    "target_name",
    "target_subject_name",
    "target_grade",
    "updated_at",
    "created_at",
    "business_tags_json",
    "location_province",
    "location_city",
    "location_district",
    "business_summary",
    "main_products_text",
    "transaction_summary",
    "risk_summary",
    "gap_summary",
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_debt_ratio",
    "current_operating_cash_flow_yuan",
    "financial_period_label",
    "profitability_status",
    "cash_flow_status",
    "listed_status",
    "stock_code",
    "market_cap_yuan",
    "valuation_yuan",
    "valuation_date",
    "asking_price_yuan",
    "asking_price_date",
    "pe_ratio",
    "transfer_ratio_min",
    "transfer_ratio_max",
    "transfer_ratio_text",
    "can_control",
    "can_consolidate",
    "accepts_minority_investment",
    "accepts_relocation",
    "management_retention_possible",
    "acceptable_transaction_structures_json",
    "major_risk_flags_json",
)


def _parse_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for item in raw:
        key = str(item or "").strip()
        if not key:
            continue
        try:
            UUID(key)
        except ValueError:
            continue
        if key not in ids:
            ids.append(key)
    return ids


def target_get(db: Session, *, ids: Any) -> dict[str, Any]:
    wanted = _parse_ids(ids)
    if not wanted:
        return {
            "matched": 0,
            "returned": [],
            "notes": [
                "ids 必须是非空数组，元素是 targets_scan / targets_filter 返回的 seller_target_id。"
            ],
        }
    if len(wanted) > GET_LIMIT:
        return {"matched": 0, "returned": [], "notes": [f"一次最多取 {GET_LIMIT} 家。"]}
    columns = ",\n                   ".join(
        f"st.{column}::text as {column}"
        if column in {"updated_at", "created_at"}
        else f"st.{column}"
        for column in _DETAIL_COLUMNS
    )
    rows = (
        db.execute(
            text(
                f"""
            select {columns}
            from seller_target st
            where {_GATE_SQL}
              and st.id = any(:ids)
            """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "ids": [UUID(item) for item in wanted],
            },
        )
        .mappings()
        .all()
    )
    sections = load_profile_sections(
        db, entity_type="seller_target", entity_ids=[row["id"] for row in rows]
    )
    found = {str(row["id"]) for row in rows}
    returned = [_target_dossier(dict(row), sections.get(str(row["id"]))) for row in rows]
    notes = [
        f"没有 id 为 {item} 的在库标的（可能是 E 级或已删除）。"
        for item in wanted
        if item not in found
    ]
    return {"matched": len(returned), "returned": returned, **({"notes": notes} if notes else {})}


def _target_dossier(
    row: dict[str, Any], sections: dict[str, dict[str, Any]] | None
) -> dict[str, Any]:
    listed = str(row.get("listed_status") or "")
    return _compact(
        {
            "seller_target_id": str(row.get("id") or ""),
            "标的名称": row.get("target_name"),
            "标的主体": row.get("target_subject_name"),
            "级别": row.get("target_grade"),
            "业务标签": business_tags_text(row.get("business_tags_json"), limit=8),
            "地区": _region(row),
            "业务摘要": (row.get("business_summary") or "").strip() or None,
            "主要产品": (row.get("main_products_text") or "").strip() or None,
            "财务": _compact(
                {
                    "营收": _money(row.get("current_revenue_yuan")),
                    "净利润": _money(row.get("current_net_profit_yuan")),
                    "利润总额": _money(row.get("current_total_profit_yuan")),
                    "经营现金流": _money(row.get("current_operating_cash_flow_yuan")),
                    "资产负债率": _ratio(row.get("current_debt_ratio")),
                    "财务期间": row.get("financial_period_label"),
                    "盈利状态": _label("profitability_status", row.get("profitability_status")),
                    "现金流状态": _label("cash_flow_status", row.get("cash_flow_status")),
                }
            ),
            "估值与交易": _compact(
                {
                    "上市状态": _label("listed_status", listed),
                    "股票代码": row.get("stock_code"),
                    "市值": _money(row.get("market_cap_yuan"))
                    if listed == "listed" or row.get("market_cap_yuan")
                    else None,
                    "估值": _money(row.get("valuation_yuan")),
                    "估值时间": row.get("valuation_date"),
                    "报价": _money(row.get("asking_price_yuan")),
                    "报价时间": row.get("asking_price_date"),
                    "PE": _ratio(row.get("pe_ratio")),
                    "出售比例": _ratio(row.get("transfer_ratio_min")),
                    "出售比例上限": _ratio(row.get("transfer_ratio_max")),
                    "出售比例说明": row.get("transfer_ratio_text"),
                    "可控股": _label("can_control", row.get("can_control")),
                    "可并表": _label("can_consolidate", row.get("can_consolidate")),
                    "接受少数股权": _label(
                        "accepts_minority_investment", row.get("accepts_minority_investment")
                    ),
                    "接受迁址": _label("accepts_relocation", row.get("accepts_relocation")),
                    "团队可留任": _label(
                        "management_retention_possible", row.get("management_retention_possible")
                    ),
                    "可接受交易结构": _labels(
                        "acceptable_transaction_structures_json",
                        row.get("acceptable_transaction_structures_json"),
                    ),
                    "交易摘要": row.get("transaction_summary"),
                }
            ),
            "风险": _compact(
                {
                    "重大风险": _labels("major_risk_flags_json", row.get("major_risk_flags_json")),
                    "风险摘要": row.get("risk_summary"),
                    "信息缺口": row.get("gap_summary"),
                }
            ),
            "补充说明": render_profile_text(sections, entity_type="seller_target") or None,
            "录入时间": _date_text(row.get("created_at")),
            "更新时间": _date_text(row.get("updated_at")),
        }
    )


# ---------------------------------------------------------------- 筛选


def targets_filter(
    db: Session,
    *,
    conditions: Any,
    limit: int = MAX_SCREENING_LIMIT,
    offset: int = 0,
    count_only: bool = False,
) -> dict[str, Any]:
    result = screen_targets(
        db,
        conditions if isinstance(conditions, dict) else {},
        limit=max(1, min(int(limit or MAX_SCREENING_LIMIT), MAX_SCREENING_LIMIT)),
        offset=max(0, int(offset or 0)),
        count_only=bool(count_only),
    )
    payload = result.as_tool_result()
    if not result.count_only:
        payload["returned"] = [
            {**_row_digest(row, result.conditions), "updated_at": _date_text(row.get("updated_at"))}
            for row in result.rows
        ]
    payload.setdefault("notes", []).extend(
        [
            "excluded_by_condition 里的 missing 是「标的没录这个数」，failed 才是「明确不达标」；"
            "缺数不等于不合格。",
            "这一步只做硬筛：命中集按级别排序，没有业务匹配，"
            "业务是否对口要读 targets_scan 或 target_get 的文本。",
        ]
    )
    return payload
