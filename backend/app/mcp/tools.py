"""MCP 工具目录：买家库与标的库各三个只读工具。

工具的名称、说明和参数 schema 就是外部 Agent 看到的全部说明书 —— SKILL.md 里那些
「空值方向相反」「多方案是 OR」「别从公司名猜业务」的规则压缩在这里，随工具一起下发，
不依赖调用方有没有装 skill。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.app.mcp.protocol import ToolError, ToolSpec
from backend.app.services import agent_buyer_views as buyers
from backend.app.services import agent_target_views as targets
from backend.app.services.api_keys import ApiKeyContext
from backend.app.services.screening_schema import build_conditions_properties
from backend.app.services.screening_sql import MAX_BUSINESS_SCAN_LIMIT, MAX_SCREENING_LIMIT


@dataclass(frozen=True)
class ToolContext:
    db: Session
    caller: ApiKeyContext


INSTRUCTIONS = "\n".join(
    [
        "Match-MA 是投资撮合的买家库与标的库。你拿到的是材料，业务是否对口由你读文本判断，"
        "库里没有行业筛选。",
        "反向（为标的找买家）：buyers_scan 一次取回全库买家的业务原文、门槛和其他要求 → "
        "逐条读判断业务对口 → 选出 5-10 家后 buyer_get 取原文和主体财务。",
        "正向（为买家找标的）：targets_scan 取回全库标的的业务摘要 → 读文本判断 → "
        "target_get 取全量档；有硬数字时先 targets_filter 收窄。",
        "三条铁律：① 买家需求的门槛为空 = 买家没提 = 不构成障碍，是正面信号；"
        "买家自身事实为空才是未知。② 一条需求的多个方案是 OR，满足任一即命中，不要叠加门槛。"
        "③ 只引用工具返回的名称和 id，业务说明为空就说信息不足，不要从公司名猜业务。"
        "返回里没有联系人，这是业务规则。",
    ]
)

_LISTED = ["listed", "unlisted", "pre_ipo"]
_OWNERSHIP = ["state_owned", "private", "foreign", "other"]


def _string_array(description: str, max_items: int | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
        "description": description,
    }
    if max_items:
        schema["maxItems"] = max_items
    return schema


def _region_object(description: str) -> dict[str, Any]:
    return {
        "type": "object",
        "description": description,
        "properties": {
            "province": {"type": "string", "description": "省份全称，如 江苏省 / 上海市"},
            "city": {"type": "string", "description": "地级市全称，如 苏州市"},
            "district": {"type": "string", "description": "区县全称，如 吴中区"},
        },
        "additionalProperties": False,
    }


# ---------------------------------------------------------------- 买家库


def _buyers_scan(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return buyers.buyers_scan(context.db)


def _buyer_get(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return buyers.buyer_get(context.db, ids=arguments.get("ids"), names=arguments.get("names"))


def _buyers_filter(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return buyers.buyers_filter(context.db, arguments)


BUYERS_SCAN = ToolSpec(
    name="buyers_scan",
    description=(
        "全库买家的业务原文：每家买家的业务标签、业务说明，名下每条需求的各方案「要买什么业务」、排除方向、"
        "门槛和其他要求。没有行业或关键词参数，这是设计：业务是否对口由你逐条读文本判断。"
        "绝大多数反向查询的第一步。「门槛」为空 = 买家没提 = 不构成障碍。多方案是 OR。"
    ),
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    handler=_buyers_scan,
)

BUYER_GET = ToolSpec(
    name="buyer_get",
    description=(
        "按 id 或名称取买家全量档案：主体全部事实（企业性质、上市、所在地、市值/估值、营收、"
        "现金流、别名、补充信息）"
        "和名下每条需求的完整档，含原始需求正文。可一次传多个。名称模糊匹配且认别名，同名多个主体全部返回，"
        "不要合并也不要只用第一个。返回里没有联系人。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ids": _string_array(
                "buyer_party_id 列表，来自 buyers_scan / buyers_filter 的返回。", 20
            ),
            "names": _string_array("买家名称或别名列表，模糊匹配。", 20),
        },
        "additionalProperties": False,
    },
    handler=_buyer_get,
)

BUYERS_FILTER = ToolSpec(
    name="buyers_filter",
    description=(
        "按条件筛买家，按主体分组返回全量档。三类条件可以组合（AND）："
        "① 买家自身条件（企业性质、上市状态、所在地、市值/营收下限）——"
        "显式筛选时事实未知的买家不算满足；"
        "② 标的事实 target_*（传你手上这个标的的真实数字），代码拿它去比每条需求各方案的门槛，"
        "买家没提的门槛一律通过并标注「没提过」；"
        "③ 买家提出的门槛 requires_* / has_threshold"
        "（「谁要求上市标的」「谁要求地区含上海」「谁设了 PE 上限」）。"
        "地区只认标准省市区全称，长三角、大湾区等大区请先展开成省份。上限 50 家，用 offset 翻页。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ownership_type": {"type": "string", "enum": _OWNERSHIP, "description": "买家企业性质"},
            "listed_status": {"type": "string", "enum": _LISTED, "description": "买家自身上市状态"},
            "province": {"type": "string", "description": "买家所在省份全称，如 江苏省"},
            "city": {"type": "string", "description": "买家所在城市全称，如 杭州市"},
            "district": {"type": "string", "description": "买家所在区县全称"},
            "min_market_cap_yuan": {"type": "number", "description": "买家自己的市值下限，单位元"},
            "min_revenue_yuan": {"type": "number", "description": "买家自己的营收下限，单位元"},
            "target_revenue_yuan": {
                "type": "number",
                "description": "手上标的的营收，单位元，用来比需求的最低营收",
            },
            "target_net_profit_yuan": {"type": "number", "description": "手上标的的净利润，单位元"},
            "target_pe": {"type": "number", "description": "手上标的的 PE 倍数，15 倍写 15"},
            "target_market_cap_yuan": {"type": "number", "description": "手上标的的市值，单位元"},
            "target_valuation_yuan": {"type": "number", "description": "手上标的的估值，单位元"},
            "target_listed_status": {
                "type": "string",
                "enum": _LISTED,
                "description": "手上标的的上市状态",
            },
            "target_province": {"type": "string", "description": "手上标的所在省份全称"},
            "target_city": {"type": "string", "description": "手上标的所在城市全称"},
            "target_district": {"type": "string", "description": "手上标的所在区县全称"},
            "requires_listed_status": {
                "type": "string",
                "enum": _LISTED,
                "description": "只要明确要求这种上市状态的买家（接受多种的也算）",
            },
            "requires_region": _region_object("只要明确要求标的位于该地区的买家"),
            "has_threshold": {
                "type": "array",
                "items": {"type": "string", "enum": list(buyers.THRESHOLD_FIELDS)},
                "description": '只要明确设了这些门槛的买家，例如 ["max_pe"] 找设了 PE 上限的',
            },
            "grade": {
                "type": "array",
                "items": {"type": "string", "enum": ["A", "B", "C", "D"]},
                "description": "需求级别",
            },
            "updated_since": {
                "type": "string",
                "description": "只要这个日期之后更新过的需求，YYYY-MM-DD",
            },
            "include_paused": {
                "type": "boolean",
                "description": "是否包含暂停推荐的需求，默认包含并标注",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": buyers.FILTER_RESULT_LIMIT,
                "description": "每页家数，默认 50",
            },
            "offset": {"type": "integer", "minimum": 0},
            "count_only": {"type": "boolean", "description": "只要命中数，不要明细"},
        },
        "additionalProperties": False,
    },
    handler=_buyers_filter,
)


# ---------------------------------------------------------------- 标的库


def _targets_scan(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return targets.targets_scan(
        context.db,
        limit=int(arguments.get("limit") or MAX_BUSINESS_SCAN_LIMIT),
        offset=int(arguments.get("offset") or 0),
    )


def _target_get(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    return targets.target_get(context.db, ids=arguments.get("ids"))


def _targets_filter(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    conditions = arguments.get("conditions")
    if conditions is not None and not isinstance(conditions, dict):
        raise ToolError("conditions 必须是对象。")
    return targets.targets_filter(
        context.db,
        conditions=conditions or {},
        limit=int(arguments.get("limit") or MAX_SCREENING_LIMIT),
        offset=int(arguments.get("offset") or 0),
        count_only=bool(arguments.get("count_only")),
    )


TARGETS_SCAN = ToolSpec(
    name="targets_scan",
    description=(
        "全库标的的业务扫描：每条只有名称、级别、业务标签、地区、上市状态、业务摘要和主要产品，没有财务数字。"
        "没有行业或关键词参数：业务是否对口由你逐条读「业务摘要」判断，业务标签只是辅助"
        "（自由词，老数据可能没有；键不存在 = 没录，不是没有业务）。正向查询的第一步；"
        f"上限 {MAX_BUSINESS_SCAN_LIMIT} 条，超出用 offset 翻页。业务摘要为空的不要从公司名猜。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_BUSINESS_SCAN_LIMIT},
            "offset": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    },
    handler=_targets_scan,
)

TARGET_GET = ToolSpec(
    name="target_get",
    description=(
        "按 id 取标的全量档：财务、估值与交易条件（可控股、可并表、出售比例、交易结构）、风险、"
        "以及五组补充说明。一次最多 20 个。「未录」不等于「没有」。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ids": _string_array("seller_target_id 列表，来自 targets_scan / targets_filter。", 20)
        },
        "required": ["ids"],
        "additionalProperties": False,
    },
    handler=_target_get,
)

TARGETS_FILTER = ToolSpec(
    name="targets_filter",
    description=(
        "按硬条件筛标的（AND）：要求地区、上市状态、最低营收、最低净利润、PE 上限、市值/估值区间。"
        "只在买家明确提出硬要求时才填，「优先大湾区」是偏好不是门槛，填进去会把外地的好标的筛掉。"
        "返回命中数、按级别排序的前 N 条，以及逐条件的淘汰拆分"
        "（missing = 标的没录这个数，failed = 明确不达标）。"
        f"每页最多 {MAX_SCREENING_LIMIT} 条，用 offset 翻页；count_only 只探规模。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "conditions": {
                "type": "object",
                "properties": build_conditions_properties(),
                "additionalProperties": False,
                "description": "硬条件，全部可选，不填表示不筛。",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_SCREENING_LIMIT},
            "offset": {"type": "integer", "minimum": 0},
            "count_only": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
    handler=_targets_filter,
)


TOOLS: list[ToolSpec] = [
    BUYERS_SCAN,
    BUYER_GET,
    BUYERS_FILTER,
    TARGETS_SCAN,
    TARGET_GET,
    TARGETS_FILTER,
]
