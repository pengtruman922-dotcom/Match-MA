"""外部 Agent 看到的买家库：三种查询形状的服务端实现。

这是 `skills/buyer-search/search_buyers.py` 的服务端版本。原来那 1100 行 Python 跑在
wegent 沙箱里，闸门、方案 OR 判定、门槛比较、联系人剥离全在客户端，服务端改了数据
模型沙箱不知道（0901 那次「skill 不读方案表」就是这么来的）。现在只有这一份。

设计要点（改动前先读）：

1. **业务匹配不走结构化字段，走全量文本 + LLM 判断。** ``scan`` 没有行业 / 关键词参数，
   这是设计不是遗漏：买家说的是「薄膜电容器」「线控底盘」，任何字典都接不住。
2. **空值方向和正向相反。** 买家需求的门槛为空 = 买家没提 = **不构成障碍**，是正面信号。
   买家自身的事实为空 = 没录、未知。返回结构把两者分在「买家信息」/「收购需求」两块，
   让这个区分在数据形状上成立。
3. **多方案是 OR。** 命中任意一个方案即算命中这条需求，绝不把各方案的门槛叠加。
4. **联系人三件套与运营备注永不出库。** 投影里根本不选这几列，不是取出来再删。
5. **首轮卡片带门槛与其他要求**（0907 用户拍板）：门槛体积小、原文才贵。原文只在 ``get`` 里。
6. **多方案的重复文本在输出层去重**：各方案都有的「其他要求」句子提到需求级「各方案共同要求」。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import (
    buyer_intent_scenario_fact_columns,
    buyer_party_fact_columns,
    indicator_by_column,
)
from backend.app.services.scenario_text import dedupe_scenario_requirements

# ---------------------------------------------------------------- 常量

CONTACT_COLUMNS: frozenset[str] = frozenset(
    {"contact_name", "contact_info_json", "our_contact_name"}
)
FILTER_RESULT_LIMIT = 50
GET_LIMIT = 20
RAW_TEXT_LIMIT = 6000

THRESHOLD_FIELDS: tuple[str, ...] = (
    "required_regions_json",
    "acceptable_listed_status_json",
    "min_revenue_yuan",
    "min_net_profit_yuan",
    "max_pe",
    "min_market_cap_yuan",
    "max_market_cap_yuan",
    "min_valuation_yuan",
    "max_valuation_yuan",
)

EMPTY_TOKENS = {"", "unknown", "none", "null"}
_ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")
_PARSE_INSTRUCTION = re.compile(
    r"(【新建买家及并购需求初始输入】|【需求原文/补充材料】|解析要求|提取要求|输出要求|请按以下|以下为附件内容|附件内容如下)[：:]?[^\n]*\n?"
)


def _enum_labels(entity: str, column: str) -> dict[str, str]:
    try:
        options = indicator_by_column(entity, column).enum_options or ()
    except KeyError:
        options = ()
    return {code: label for code, label in options}


OWNERSHIP_LABELS = _enum_labels("buyer_party", "ownership_type")
LISTED_LABELS = _enum_labels("buyer_party", "listed_status")
EXCHANGE_LABELS = _enum_labels("buyer_party", "listing_exchange")
ACCEPTABLE_LISTED_LABELS = _enum_labels("buyer_intent_scenario", "acceptable_listed_status_json")
INTENT_STATUS_LABELS = _enum_labels("buyer_intent", "status")


# ---------------------------------------------------------------- 取值工具


def _clean(value: Any) -> str:
    return _ZERO_WIDTH.sub("", str(value or "")).strip()


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return not value
    return _clean(value).lower() in EMPTY_TOKENS


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not _blank(value)}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str | None:
    amount = _number(value)
    if amount is None:
        return None
    if abs(amount) >= 1e8:
        return f"{amount / 1e8:.2f}".rstrip("0").rstrip(".") + "亿"
    if abs(amount) >= 1e4:
        return f"{amount / 1e4:.0f}万"
    return f"{amount:.0f}元"


def _ratio(value: Any) -> str | None:
    number = _number(value)
    return None if number is None else f"{number:g}"


def _labels(values: Any, table: dict[str, str]) -> str | None:
    if not isinstance(values, list):
        return None
    named = [table.get(str(item), str(item)) for item in values if not _blank(item)]
    return "、".join(named) or None


def _region_text(regions: Any) -> str | None:
    if not isinstance(regions, list) or not regions:
        return None
    parts: list[str] = []
    for item in regions:
        if not isinstance(item, dict):
            continue
        levels = [_clean(item.get(key)) for key in ("province", "city", "district")]
        label = "".join(dict.fromkeys(level for level in levels if level))
        if label and label not in parts:
            parts.append(label)
    return "、".join(parts) or None


def _date_text(value: Any) -> str | None:
    text_value = _clean(value)
    return text_value[:19] if text_value else None


def clean_requirement_text(value: Any, limit: int = RAW_TEXT_LIMIT) -> str | None:
    """原始需求正文：去解析指令、去重复段落、限长。"""
    text_value = _clean(value)
    if not text_value:
        return None
    text_value = _PARSE_INSTRUCTION.sub("", text_value)
    # 按行去重而不是按段：OCR 把同一附件贴两遍时段落边界常常对不上，
    # 而需求卡片的模板行（「1. 所属行业：」）本来就该只出现一次。
    seen: set[str] = set()
    kept: list[str] = []
    for line in text_value.splitlines():
        normalized = re.sub(r"\s+", "", line)
        if not normalized:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if len(normalized) >= 8 and normalized in seen:
            continue
        seen.add(normalized)
        kept.append(line.strip())
    joined = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if not joined:
        return None
    return joined if len(joined) <= limit else joined[:limit] + "…（已截断）"


# ---------------------------------------------------------------- 读库


def party_projection_columns() -> list[str]:
    """主体投影：事实列减去联系人三件套。``notes`` 是系统列，本来就不在事实列里。"""
    return [column for column in buyer_party_fact_columns() if column not in CONTACT_COLUMNS]


def load_active_parties(db: Session) -> dict[str, dict[str, Any]]:
    columns = ", ".join(["id", "buyer_name", "aliases_json", "status", *party_projection_columns()])
    rows = (
        db.execute(
            text(
                f"""
            select {columns},
                   created_at::text as created_at, updated_at::text as updated_at
            from buyer_party
            where team_id = :team_id and workspace_id = :workspace_id
              and deleted_at is null and status = 'active'
            order by buyer_name
            """
            ),
            {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
        )
        .mappings()
        .all()
    )
    return {str(row["id"]): dict(row) for row in rows}


def _scenario_json_object_sql() -> str:
    pairs = ["'id', s.id", "'updated_at', s.updated_at::text"]
    pairs.extend(f"'{column}', s.{column}" for column in buyer_intent_scenario_fact_columns())
    return "jsonb_build_object(" + ", ".join(pairs) + ")"


def load_live_intents(db: Session) -> list[dict[str, Any]]:
    """过闸门的需求：E 级不进、结束推荐不进、主体非 active 不进。暂停的进，带标注。"""
    rows = (
        db.execute(
            text(
                f"""
            select bi.id, bi.buyer_party_id, bi.intent_name, bi.intent_grade, bi.status,
                   bi.pause_reason, bi.raw_requirement_text, bi.needs_confirmation_json,
                   bi.created_at::text as created_at, bi.updated_at::text as updated_at,
                   (select coalesce(jsonb_agg({_scenario_json_object_sql()}
                                              order by s.sort_order, s.created_at), '[]'::jsonb)
                      from buyer_intent_scenario s
                     where s.buyer_intent_id = bi.id
                       and s.team_id = bi.team_id and s.workspace_id = bi.workspace_id
                       and s.active and s.deleted_at is null) as scenarios_json
            from buyer_intent bi
            join buyer_party bp
              on bp.id = bi.buyer_party_id and bp.deleted_at is null and bp.status = 'active'
            where bi.team_id = :team_id and bi.workspace_id = :workspace_id
              and bi.deleted_at is null
              and bi.intent_grade <> 'E'
              and bi.status <> 'closed'
            order by bi.intent_grade asc, bi.updated_at desc
            """
            ),
            {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def _scenarios(intent: dict[str, Any]) -> list[dict[str, Any]]:
    rows = intent.get("scenarios_json")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _group_intents(intents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for intent in intents:
        grouped.setdefault(str(intent.get("buyer_party_id")), []).append(intent)
    return grouped


# ---------------------------------------------------------------- 形状：主体


def _party_location(party: dict[str, Any]) -> str | None:
    return _region_text(
        [
            {
                "province": party.get("location_province"),
                "city": party.get("location_city"),
                "district": party.get("location_district"),
            }
        ]
    )


def party_card(party: dict[str, Any]) -> dict[str, Any]:
    """扫描卡片里的主体部分：判业务匹配需要的，加几项便宜的自身事实。"""
    return _compact(
        {
            "buyer_party_id": str(party.get("id") or ""),
            "买家名称": _clean(party.get("buyer_name")),
            "别名": _labels(party.get("aliases_json"), {}),
            "所在地": _party_location(party),
            "企业性质": OWNERSHIP_LABELS.get(str(party.get("ownership_type") or "")),
            "上市状态": LISTED_LABELS.get(str(party.get("listed_status") or "")),
            "业务标签": _labels(party.get("business_tags_json"), {}),
            "业务说明": _clean(party.get("business_summary")),
            "更新时间": _date_text(party.get("updated_at")),
        }
    )


def party_dossier(party: dict[str, Any]) -> dict[str, Any]:
    """主体全量。联系人三件套与运营备注不在投影里，这里自然没有。"""
    listed = str(party.get("listed_status") or "")
    money: dict[str, Any] = {}
    if listed == "listed" or not _blank(party.get("market_cap_yuan")):
        money["市值"] = _money(party.get("market_cap_yuan"))
        money["市值日期"] = _clean(party.get("market_cap_as_of"))
    if listed != "listed" or not _blank(party.get("valuation_yuan")):
        money["估值"] = _money(party.get("valuation_yuan"))
        money["估值时点"] = _clean(party.get("valuation_date"))
    return _compact(
        {
            "buyer_party_id": str(party.get("id") or ""),
            "买家名称": _clean(party.get("buyer_name")),
            "别名": _labels(party.get("aliases_json"), {}),
            "企业性质": OWNERSHIP_LABELS.get(str(party.get("ownership_type") or "")),
            "上市状态": LISTED_LABELS.get(listed),
            "上市地": EXCHANGE_LABELS.get(str(party.get("listing_exchange") or "")),
            "股票代码": _clean(party.get("stock_code")),
            "所在地": _party_location(party),
            "业务标签": _labels(party.get("business_tags_json"), {}),
            "业务说明": _clean(party.get("business_summary")),
            **_compact(money),
            "营收": _money(party.get("current_revenue_yuan")),
            "经营现金流": _money(party.get("current_operating_cash_flow_yuan")),
            "财务期间": _clean(party.get("financial_period_label")),
            "补充信息": _clean(party.get("supplementary_summary")),
            "录入时间": _date_text(party.get("created_at")),
            "更新时间": _date_text(party.get("updated_at")),
        }
    )


# ---------------------------------------------------------------- 形状：方案与需求


def scenario_thresholds(scenario: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "最低营收": _money(scenario.get("min_revenue_yuan")),
            "最低净利润": _money(scenario.get("min_net_profit_yuan")),
            "PE 上限": _ratio(scenario.get("max_pe")),
            "估值下限": _money(scenario.get("min_valuation_yuan")),
            "估值上限": _money(scenario.get("max_valuation_yuan")),
            "市值下限": _money(scenario.get("min_market_cap_yuan")),
            "市值上限": _money(scenario.get("max_market_cap_yuan")),
            "上市状态": _labels(
                scenario.get("acceptable_listed_status_json"), ACCEPTABLE_LISTED_LABELS
            ),
            "要求地区": _region_text(scenario.get("required_regions_json")),
        }
    )


def _scenario_label(index: int, total: int) -> str | None:
    return f"方案 {index + 1}" if total > 1 else None


def _scenario_block(
    scenario: dict[str, Any], index: int, total: int, other_requirements: str | None
) -> dict[str, Any]:
    thresholds = scenario_thresholds(scenario)
    payload = _compact(
        {
            "档": _scenario_label(index, total),
            "业务标签": _labels(scenario.get("business_tags_json"), {}),
            "要买什么业务": _clean(scenario.get("scenario_summary")),
            "排除方向": _clean(scenario.get("excluded_business_text")),
            "门槛": thresholds,
            "其他要求": other_requirements,
            "更新时间": _date_text(scenario.get("updated_at")),
        }
    )
    if not thresholds:
        payload["门槛说明"] = "这个方案没有提出任何硬门槛，不构成障碍。"
    return payload


def _intent_shell(intent: dict[str, Any]) -> dict[str, Any]:
    payload = _compact(
        {
            "buyer_intent_id": str(intent.get("id") or ""),
            "需求名称": _clean(intent.get("intent_name")),
            "级别": _clean(intent.get("intent_grade")),
            "更新时间": _date_text(intent.get("updated_at")),
        }
    )
    if str(intent.get("status") or "") == "paused":
        payload["状态"] = "暂停推荐（仍在库里，推荐前先跟顾问确认）"
        reason = _clean(intent.get("pause_reason"))
        if reason:
            payload["暂停原因"] = reason
    return payload


def _attach_scenarios(payload: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    scenarios = _scenarios(intent)
    shared, remaining = dedupe_scenario_requirements(
        [scenario.get("other_requirements_text") for scenario in scenarios]
    )
    if shared:
        payload["各方案共同要求"] = "；".join(shared)
    blocks = [
        _scenario_block(
            scenario, index, len(scenarios), remaining[index] if index < len(remaining) else None
        )
        for index, scenario in enumerate(scenarios)
    ]
    if len(blocks) == 1:
        payload.update(blocks[0])
    elif blocks:
        payload["方案"] = blocks
        payload["方案说明"] = (
            "满足任意一个方案即算命中这条需求。逐个读、逐个判，不要把各方案的门槛叠加。"
        )
    if len(scenarios) > 1 and not any(scenario_thresholds(scenario) for scenario in scenarios):
        payload["门槛说明"] = "这条需求的每个方案都没有提出硬门槛，不构成障碍。"
    return payload


def intent_card(intent: dict[str, Any]) -> dict[str, Any]:
    """扫描卡片里的需求：业务方向 + 门槛 + 其他要求，不带原文。"""
    return _attach_scenarios(_intent_shell(intent), intent)


def intent_dossier(intent: dict[str, Any]) -> dict[str, Any]:
    """需求全量：卡片 + 原始需求正文 + 待确认项数。"""
    payload = _attach_scenarios(_intent_shell(intent), intent)
    payload["录入时间"] = _date_text(intent.get("created_at"))
    pending = intent.get("needs_confirmation_json")
    pending_count = len(pending) if isinstance(pending, list) else 0
    pending_count += sum(
        len(scenario.get("needs_confirmation_json") or [])
        for scenario in _scenarios(intent)
        if isinstance(scenario.get("needs_confirmation_json"), list)
    )
    if pending_count:
        payload["解析待确认"] = f"有 {pending_count} 处解析时不确定，待顾问核对"
    raw = clean_requirement_text(intent.get("raw_requirement_text"))
    if raw:
        payload["原始需求"] = raw
    return _compact(payload)


def dossier(party: dict[str, Any], intents: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "买家信息": party_dossier(party),
        "收购需求": [intent_dossier(intent) for intent in intents],
    }


# ---------------------------------------------------------------- 查询一：全库扫描


def buyers_scan(db: Session) -> dict[str, Any]:
    parties = load_active_parties(db)
    by_party = _group_intents(load_live_intents(db))
    cards: list[dict[str, Any]] = []
    for party_id, party in parties.items():
        intents = by_party.get(party_id) or []
        if not intents:
            continue  # 没有在库需求的主体判不了「要买什么」，扫描里不出现，get / filter 里能查到
        cards.append({**party_card(party), "需求": [intent_card(intent) for intent in intents]})
    cards.sort(key=_card_sort_key)
    return {
        "matched": len(cards),
        "returned": cards,
        "notes": [
            "这是全库业务原文，没有做过任何业务筛选，业务是否对口完全由你读文本判断。",
            "「门槛」为空 = 买家没提这个门槛 = 不构成障碍，是正面信号；"
            "「业务说明」为空才是没录、未知。",
            "业务说明为空的买家不要从公司名猜业务，如实说信息不足。",
            "同一家买家名下可能有多条需求，它们是不同的收购方向，分别判断。",
            "选出候选后用 buyer_get 取原始需求正文与主体财务信息。",
        ],
    }


def _card_sort_key(card: dict[str, Any]) -> tuple[str, str]:
    grades = sorted(str(intent.get("级别") or "Z") for intent in card.get("需求") or [])
    return (grades[0] if grades else "Z", str(card.get("买家名称") or ""))


# ---------------------------------------------------------------- 查询二：取档


def buyer_get(db: Session, *, ids: Any = None, names: Any = None) -> dict[str, Any]:
    id_list = (
        [_clean(item) for item in (ids or []) if _clean(item)] if isinstance(ids, list) else []
    )
    name_list = (
        [_clean(item) for item in (names or []) if _clean(item)] if isinstance(names, list) else []
    )
    if not id_list and not name_list:
        return {"matched": 0, "returned": [], "notes": ["需要 ids 或 names 至少一个。"]}
    if len(id_list) + len(name_list) > GET_LIMIT:
        return {"matched": 0, "returned": [], "notes": [f"一次最多取 {GET_LIMIT} 家。"]}

    parties = load_active_parties(db)
    by_party = _group_intents(load_live_intents(db))
    hits: dict[str, dict[str, Any]] = {}
    notes: list[str] = []

    for party_id in id_list:
        party = parties.get(party_id)
        if party is None:
            notes.append(f"没有 id 为 {party_id} 的在库买家（也可能它已归档）。")
        else:
            hits[party_id] = party

    for keyword in name_list:
        lowered = keyword.lower()
        matched = []
        for party_id, party in parties.items():
            haystack = [_clean(party.get("buyer_name"))]
            aliases = party.get("aliases_json")
            if isinstance(aliases, list):
                haystack.extend(_clean(alias) for alias in aliases)
            if any(lowered in item.lower() for item in haystack if item):
                matched.append((party_id, party))
        if not matched:
            notes.append(
                f"买家库里没有名称或别名包含「{keyword}」的在库买家。不要据此推断这家公司不存在，只是不在库里。"
            )
        elif len(matched) > 1:
            notes.append(
                f"「{keyword}」命中 {len(matched)} 个主体，全部返回，"
                "请按需求内容判断该用哪一个或向用户说明。"
            )
        for party_id, party in matched:
            hits[party_id] = party

    ordered = sorted(
        hits.values(),
        key=lambda party: (len(_clean(party.get("buyer_name"))), _clean(party.get("buyer_name"))),
    )
    return {
        "matched": len(ordered),
        "returned": [dossier(party, by_party.get(str(party["id"])) or []) for party in ordered],
        **({"notes": notes} if notes else {}),
    }


# ---------------------------------------------------------------- 查询三：筛选


def _region_hit(regions: Any, province: str, city: str, district: str) -> bool:
    if not isinstance(regions, list):
        return False
    for item in regions:
        if not isinstance(item, dict):
            continue
        levels = [
            (_clean(item.get("province")), province),
            (_clean(item.get("city")), city),
            (_clean(item.get("district")), district),
        ]
        if not any(wanted for wanted, _ in levels):
            continue
        if all(not wanted or wanted == actual for wanted, actual in levels):
            return True
    return False


def scenario_fact_checks(
    scenario: dict[str, Any], target: dict[str, Any]
) -> list[tuple[str, bool, bool]]:
    """(条件名, 买家提了没, 提了的话过没过)。买家没提 = 不构成障碍。"""
    checks: list[tuple[str, bool, bool]] = []

    def numeric(label: str, threshold: Any, actual: Any, *, at_least: bool) -> None:
        limit = _number(threshold)
        if limit is None:
            checks.append((label, False, True))
            return
        value = _number(actual)
        if value is None:
            checks.append((label, True, True))  # 标的这一侧没给数：不能判它不达标
            return
        checks.append((label, True, value >= limit if at_least else value <= limit))

    numeric("最低营收", scenario.get("min_revenue_yuan"), target.get("revenue_yuan"), at_least=True)
    numeric(
        "最低净利润",
        scenario.get("min_net_profit_yuan"),
        target.get("net_profit_yuan"),
        at_least=True,
    )
    numeric("PE 上限", scenario.get("max_pe"), target.get("pe"), at_least=False)
    numeric(
        "估值下限", scenario.get("min_valuation_yuan"), target.get("valuation_yuan"), at_least=True
    )
    numeric(
        "估值上限", scenario.get("max_valuation_yuan"), target.get("valuation_yuan"), at_least=False
    )
    numeric(
        "市值下限",
        scenario.get("min_market_cap_yuan"),
        target.get("market_cap_yuan"),
        at_least=True,
    )
    numeric(
        "市值上限",
        scenario.get("max_market_cap_yuan"),
        target.get("market_cap_yuan"),
        at_least=False,
    )

    acceptable = scenario.get("acceptable_listed_status_json")
    listed = _clean(target.get("listed_status"))
    if not isinstance(acceptable, list) or not acceptable:
        checks.append(("上市状态", False, True))
    elif not listed:
        checks.append(("上市状态", True, True))
    else:
        checks.append(("上市状态", True, listed in {str(item) for item in acceptable}))

    province, city, district = (
        _clean(target.get("province")),
        _clean(target.get("city")),
        _clean(target.get("district")),
    )
    regions = scenario.get("required_regions_json")
    if not isinstance(regions, list) or not regions:
        checks.append(("要求地区", False, True))
    elif not (province or city or district):
        checks.append(("要求地区", True, True))
    else:
        checks.append(("要求地区", True, _region_hit(regions, province, city, district)))
    return checks


def scenario_stated_checks(scenario: dict[str, Any], stated: dict[str, Any]) -> bool:
    """按买家**提出的**门槛反查：「谁要求上市标的」「谁要求地区含上海」「谁设了 PE 上限」。"""
    wanted_listed = _clean(stated.get("requires_listed_status"))
    if wanted_listed:
        acceptable = scenario.get("acceptable_listed_status_json")
        if not isinstance(acceptable, list) or wanted_listed not in {
            str(item) for item in acceptable
        }:
            return False
    region = stated.get("requires_region")
    if isinstance(region, dict) and any(
        _clean(region.get(key)) for key in ("province", "city", "district")
    ):
        regions = scenario.get("required_regions_json")
        if not isinstance(regions, list) or not regions:
            return False
        if not _region_hit(
            regions,
            _clean(region.get("province")),
            _clean(region.get("city")),
            _clean(region.get("district")),
        ):
            return False
    for field in stated.get("has_threshold") or []:
        if _blank(scenario.get(str(field))):
            return False
    return True


def party_conditions_hit(party: dict[str, Any], filters: dict[str, Any]) -> bool:
    """买家自身条件：显式筛选，未知 / 空值不算满足。"""
    for key, column in (
        ("ownership_type", "ownership_type"),
        ("listed_status", "listed_status"),
        ("province", "location_province"),
        ("city", "location_city"),
        ("district", "location_district"),
    ):
        wanted = _clean(filters.get(key))
        if not wanted:
            continue
        actual = _clean(party.get(column))
        if _blank(actual) or actual != wanted:
            return False
    for key, column in (
        ("min_market_cap_yuan", "market_cap_yuan"),
        ("min_revenue_yuan", "current_revenue_yuan"),
    ):
        limit = _number(filters.get(key))
        if limit is None:
            continue
        value = _number(party.get(column))
        if value is None or value < limit:
            return False
    return True


_PARTY_FILTER_KEYS = (
    "ownership_type",
    "listed_status",
    "province",
    "city",
    "district",
    "min_market_cap_yuan",
    "min_revenue_yuan",
)
_TARGET_FACT_KEYS = {
    "target_revenue_yuan": "revenue_yuan",
    "target_net_profit_yuan": "net_profit_yuan",
    "target_pe": "pe",
    "target_market_cap_yuan": "market_cap_yuan",
    "target_valuation_yuan": "valuation_yuan",
    "target_listed_status": "listed_status",
    "target_province": "province",
    "target_city": "city",
    "target_district": "district",
}
_STATED_KEYS = ("requires_listed_status", "requires_region", "has_threshold")


def buyers_filter(db: Session, arguments: dict[str, Any]) -> dict[str, Any]:
    """按买家自身条件、标的事实、买家提出的门槛筛，按主体分组返回。"""
    party_filters = {key: arguments.get(key) for key in _PARTY_FILTER_KEYS}
    target = {column: arguments.get(key) for key, column in _TARGET_FACT_KEYS.items()}
    stated = {key: arguments.get(key) for key in _STATED_KEYS}
    grades = {str(item).upper() for item in (arguments.get("grade") or []) if str(item).strip()}
    updated_since = _parse_date(arguments.get("updated_since"))
    include_paused = arguments.get("include_paused", True) is not False
    limit = max(1, min(int(arguments.get("limit") or FILTER_RESULT_LIMIT), FILTER_RESULT_LIMIT))
    offset = max(0, int(arguments.get("offset") or 0))
    count_only = bool(arguments.get("count_only"))

    has_target_facts = any(not _blank(value) for value in target.values())
    has_stated = any(not _blank(value) for value in stated.values())
    has_intent_conditions = (
        has_target_facts
        or has_stated
        or bool(grades)
        or updated_since is not None
        or not include_paused
    )

    parties = load_active_parties(db)
    by_party = _group_intents(load_live_intents(db))

    hits: list[dict[str, Any]] = []
    marginal: dict[str, int] = {}
    for party_id, party in parties.items():
        if not party_conditions_hit(party, party_filters):
            continue
        intents = by_party.get(party_id) or []
        if not has_intent_conditions:
            hits.append(dossier(party, intents))
            continue
        passed: list[dict[str, Any]] = []
        for intent in intents:
            if not include_paused and str(intent.get("status") or "") == "paused":
                continue
            if grades and str(intent.get("intent_grade") or "").upper() not in grades:
                continue
            if (
                updated_since is not None
                and (_parse_date(intent.get("updated_at")) or date.min) < updated_since
            ):
                continue
            verdicts, failed_once = _intent_verdicts(
                intent, target, stated, has_target_facts, has_stated
            )
            if verdicts is None:
                if failed_once:
                    marginal[failed_once] = marginal.get(failed_once, 0) + 1
                continue
            entry = intent_dossier(intent)
            if verdicts:
                entry["条件判定"] = verdicts
            passed.append(entry)
        if passed:
            hits.append({"买家信息": party_dossier(party), "收购需求": passed})

    hits.sort(key=lambda item: str(item["买家信息"].get("买家名称") or ""))
    notes = [
        "「买家没提过这个门槛」= 不构成障碍，是正面信号，不要读成信息不足。",
        "买家自身信息（业务说明、市值、营收）缺失才是没录、未知。两类缺失含义相反。",
    ]
    if marginal:
        notes.append(
            "只差一条就能命中的："
            + "、".join(
                f"{label}（去掉能多召回 {count} 条需求）"
                for label, count in sorted(marginal.items())
            )
        )
    if not hits:
        notes.append(
            "该条件下没有命中。检查 target_* 传的是不是这个标的的真实数字；"
            "按买家自身条件筛时，事实未知的买家会被排除。"
        )
    payload: dict[str, Any] = {
        "matched": len(hits),
        "offset": offset,
        "limit": limit,
        "notes": notes,
    }
    if not count_only:
        page = hits[offset : offset + limit]
        payload["returned"] = page
        remaining = len(hits) - offset - len(page)
        if remaining > 0:
            payload["note"] = f"另有 {remaining} 家未返回，用 offset 翻页可以取到。"
    return payload


def _intent_verdicts(
    intent: dict[str, Any],
    target: dict[str, Any],
    stated: dict[str, Any],
    has_target_facts: bool,
    has_stated: bool,
) -> tuple[dict[str, str] | None, str | None]:
    """命中任意一个方案即算命中。返回 (命中方案的判定表, 只差一条时那一条的名字)。"""
    scenarios = _scenarios(intent)
    if not scenarios:
        return ({} if not has_stated else None), None
    single_miss: str | None = None
    first_table: dict[str, str] | None = None
    for scenario in scenarios:
        if has_stated and not scenario_stated_checks(scenario, stated):
            continue
        if not has_target_facts:
            return {}, None
        checks = scenario_fact_checks(scenario, target)
        failed = [label for label, is_stated, passed in checks if is_stated and not passed]
        table = {
            label: ("明确符合" if is_stated else "买家没提过这个门槛，不构成障碍")
            for label, is_stated, _ in checks
        }
        if first_table is None:
            first_table = table
        if not failed:
            return table, None
        if len(failed) == 1 and single_miss is None:
            single_miss = failed[0]
    return None, single_miss


def _parse_date(value: Any) -> date | None:
    text_value = _clean(value)[:10]
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value)
    except ValueError:
        return None


__all__ = [
    "buyer_get",
    "buyers_filter",
    "buyers_scan",
    "clean_requirement_text",
    "dossier",
    "intent_card",
    "intent_dossier",
    "party_card",
    "party_dossier",
    "party_conditions_hit",
    "party_projection_columns",
    "scenario_fact_checks",
    "scenario_stated_checks",
    "scenario_thresholds",
]
