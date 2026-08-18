"""Turn a recommendation-chat message into structured conditions.

Two parsers share one node (`recommendation_query_parser`) and differ only in
output shape:

- `parse_recommendation_message` -> `condition_ops`, the **incremental** form
  the old `/candidates` list page patched its condition panel with.
- `parse_recommendation_intent` -> a **complete snapshot** of what the user
  wants now, after the parser reads the last completed turns and the current
  message. It is not an incremental patch. That is what the agent chat链路
  needs, because the point of splitting parsing out of the agent is to have a
  baseline the agent can only consume, never invent.

Either way the LLM only extracts. Routing, whitelisting and type coercion are
derived in code so they stay deterministic and testable.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.prompting import render_template
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column, indicators_for
from backend.app.services.buyer_risk_tolerance import normalize_unacceptable_risk_flags
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    industry_l2_prompt_list,
    list_l1_terms,
    list_l2_terms,
)
from backend.app.services.screening_schema import SCREENING_FIELDS, normalize_conditions

QUERY_PARSER_NODE_NAME = "recommendation_query_parser"

def _condition_value_kind(field: str) -> str | None:
    indicator = indicator_by_column("buyer_intent", field)
    if indicator.kind in {"yuan", "ratio"}:
        return "number"
    if indicator.editor in {"industry", "industry_l2"}:
        return "industry_list"
    if indicator.editor in {"multi_enum", "tags"}:
        return "string_list"
    if indicator.editor == "region_multi":
        return "region_list"
    if field in {"requires_control", "requires_consolidation", "accepts_minority_investment"}:
        return "yes_no"
    if field == "preferred_listed_status":
        return "listed_status"
    if field == "listing_market_region":
        return "listing_market_region"
    if field in {"requires_relocation", "requires_return_investment", "requires_team_retention", "earnout_requirement"}:
        return "requirement_strength"
    if indicator.kind == "text":
        return "text"
    return None


# Every scenario/chat field is derived from the buyer condition contract.
OVERRIDE_FIELD_KINDS: dict[str, str] = {
    indicator.column: kind
    for indicator in indicators_for("buyer_intent")
    if (indicator.scenario_allowed or indicator.column == "preferred_listed_status")
    if (kind := _condition_value_kind(indicator.column)) is not None
}

FIELD_LABELS: dict[str, str] = {
    "industries_json": "行业",
    "excluded_industries_json": "排除行业",
    "region_scope_summary": "地区",
    "min_net_profit_yuan": "净利润下限",
    "min_revenue_yuan": "营收下限",
    "min_valuation_yuan": "估值下限",
    "max_valuation_yuan": "估值上限",
    "max_pe": "PE上限",
    "min_market_cap_yuan": "市值下限",
    "max_market_cap_yuan": "市值上限",
    "requires_control": "控股要求",
    "requires_consolidation": "并表要求",
    "desired_equity_ratio_min": "最低股比",
    "preferred_listed_status": "上市偏好",
    "acceptable_listed_status_json": "可接受上市状态",
    "max_debt_ratio": "负债率上限",
}

_LISTED_STATUS_VALUES = {"listed", "unlisted", "pre_ipo", "any", "unknown"}
_YES_NO_VALUES = {"yes", "no", "unknown"}
# 从注册表取，不再手抄：上市地 2026-08-07 换成交易所闭集，手抄一份就会漂。
_LISTING_MARKET_REGION_VALUES = {
    value for value, _ in (indicator_by_column("buyer_intent", "listing_market_region").enum_options or ())
}
_REQUIREMENT_STRENGTH_VALUES = {"required", "preferred", "not_required", "unknown"}


def _coerce_value(kind: str, value: Any) -> Any | None:
    if kind == "number":
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number
    if kind == "text":
        text_value = str(value or "").strip()
        return text_value or None
    if kind == "yes_no":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _YES_NO_VALUES else None
    if kind == "listed_status":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _LISTED_STATUS_VALUES else None
    if kind == "listing_market_region":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _LISTING_MARKET_REGION_VALUES else None
    if kind == "requirement_strength":
        text_value = str(value or "").strip().lower()
        return text_value if text_value in _REQUIREMENT_STRENGTH_VALUES else None
    if kind == "region_list":
        return value if isinstance(value, list) else None
    if kind in {"industry_list", "string_list"}:
        if isinstance(value, str):
            item = value.strip()
            return [item] if item else None
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item or "").strip()]
            return items or None
        return None
    return None


def coerce_condition_value(field: str, value: Any) -> Any | None:
    """Public whitelist coercion for one condition field.

    The agent's `search_targets` arguments go through here, so a filter the
    scoring engine does not understand is dropped rather than silently carried
    into the anchor as an unrecognised key.
    """
    kind = OVERRIDE_FIELD_KINDS.get(field)
    if kind is None:
        return None
    return _coerce_value(kind, value)


def normalize_parse_result(raw: Any) -> dict[str, Any]:
    """Whitelist-filter the LLM extraction into a safe, typed structure."""
    data = raw if isinstance(raw, dict) else {}
    ops: list[dict[str, Any]] = []
    for item in data.get("condition_ops") or []:
        if not isinstance(item, dict):
            continue
        op = str(item.get("op") or "").strip().lower()
        field = str(item.get("field") or "").strip()
        if op not in {"set", "remove", "exclude"} or field not in OVERRIDE_FIELD_KINDS:
            continue
        if op == "exclude" and field != "excluded_industries_json":
            continue
        if op == "remove":
            ops.append({"op": "remove", "field": field, "value": None})
            continue
        value = _coerce_value(OVERRIDE_FIELD_KINDS[field], item.get("value"))
        if value is None:
            continue
        if op == "exclude":
            for term in value if isinstance(value, list) else [value]:
                ops.append({"op": "exclude", "field": field, "value": term})
        else:
            ops.append({"op": "set", "field": field, "value": value})

    preferences = [
        str(item).strip()
        for item in (data.get("semantic_preferences") or [])
        if str(item or "").strip()
    ]

    display_ops: list[dict[str, Any]] = []
    for item in data.get("display_ops") or []:
        if not isinstance(item, dict):
            continue
        op_type = str(item.get("type") or "").strip()
        if op_type == "only_grade" and str(item.get("value") or "").upper() in {"A", "B", "C"}:
            display_ops.append({"type": "only_grade", "value": str(item["value"]).upper()})
        elif op_type == "top_n":
            try:
                count = int(item.get("value"))
            except (TypeError, ValueError):
                continue
            if 1 <= count <= 50:
                display_ops.append({"type": "top_n", "value": count})

    question = str(data.get("question") or "").strip() or None
    reply = str(data.get("reply_summary") or "").strip() or None
    return {
        "condition_ops": ops,
        "semantic_preferences": preferences,
        "display_ops": display_ops,
        "question": question,
        "reply_summary": reply,
        "parser_status": "ok",
    }


def fallback_parse_result(user_message: str) -> dict[str, Any]:
    return {
        "condition_ops": [],
        "semantic_preferences": [user_message.strip()] if user_message.strip() else [],
        "display_ops": [],
        "question": None,
        "reply_summary": "条件解析暂不可用，已把这句话作为语义偏好记录",
        "parser_status": "fallback",
    }


def _get_query_parser_node_config(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.model_name, node.temperature, node.top_p, node.max_tokens,
              node.timeout_seconds, node.response_format,
              provider.base_url, provider.api_key_secret_ref, provider.api_key_encrypted,
              prompt.version as prompt_version,
              prompt.system_prompt, prompt.user_prompt_template
            from model_node_config node
            join model_provider_config provider on provider.id = node.provider_config_id
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
            "node_name": QUERY_PARSER_NODE_NAME,
        },
    ).mappings().one_or_none()
    if row is None or not row.get("base_url") or not row.get("user_prompt_template"):
        raise ValueError(f"Query parser node is not configured: {QUERY_PARSER_NODE_NAME}")
    return dict(row)


def parse_recommendation_message(
    db: Session,
    *,
    mode: str,
    user_message: str,
    current_conditions: dict[str, Any],
) -> dict[str, Any]:
    """Run the query parser LLM; degrade to a semantic-preference fallback on failure."""
    try:
        node = _get_query_parser_node_config(db)
        variables = {
            "mode": mode,
            "current_conditions_json": json.dumps(current_conditions, ensure_ascii=False, default=str),
            "industry_l1_list": industry_l1_prompt_list(db),
            "user_message": user_message,
        }
        messages = []
        system_prompt = render_template(node.get("system_prompt"), variables)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": render_template(node["user_prompt_template"], variables)})
        llm_result = call_openai_compatible_chat(
            base_url=node["base_url"],
            api_key_secret_ref=node["api_key_secret_ref"],
            api_key_encrypted=node.get("api_key_encrypted"),
            model_name=node["model_name"],
            messages=messages,
            temperature=node["temperature"],
            top_p=node["top_p"],
            max_tokens=node["max_tokens"],
            timeout_seconds=node["timeout_seconds"] or 30,
            response_format=node["response_format"],
        )
        return normalize_parse_result(llm_result.parsed_output_json)
    except (LlmCallError, ValueError, KeyError):
        return fallback_parse_result(user_message)


# =========================================================================
# 需求解析快照（阶段二）
# =========================================================================
#
# 上面那套 `condition_ops` 是**增量操作**：给列表页的条件面板打补丁，语义是
# 「在已有条件上改一处」。对话链路要的是另一种东西 —— 一份**完整快照**：
# 解析节点读最近已完成问答与本轮消息后，判断用户现在完整地要什么。保留、替换、
# 删除或整体重置由模型结合原文判断，代码不拿上一份 JSON 机械打补丁。
#
# 拆出来的理由只有一个：解析与执行在同一个模型里时，没有任何地方能比对
# 「用户说了什么」和「agent 筛了什么」。实测出现过用户只说「杭州标的」，
# agent 自己编出「半导体 + 华东 + 净利 3000 万」去筛的事故。快照落库之后它
# 就是基线，主 Agent 只能消费不能创造，编条件这个问题从结构上消失。
#
# 两套解析共用同一个节点（`recommendation_query_parser`）与同一份节点配置，
# 只是提示词版本不同：v0.3.0 起默认提示词产出多轮语义下的当前完整快照。旧的 `/candidates` 链路
# 前端已无调用方，拿到快照形状时 `normalize_parse_result` 会得到空操作集，
# 退化成「这一轮没解析出条件」，不会报错。

# 一组条件 = 主 Agent 的一次 search_targets 调用，而工具预算就是 6 次。
# 超出的组不是丢掉不管，是记进 parser_notes，让「我砍了几组」看得见。
MAX_CONDITION_GROUPS = 6
# 定性诉求与残留笔记的条数与单条长度上限。模型偶尔会把整段材料原样倒进来，
# 而这两个字段最终要进深评的上下文。
MAX_INTENT_TEXT_ITEMS = 20
MAX_INTENT_TEXT_LENGTH = 300

PARSER_STATUSES: tuple[str, ...] = ("ok", "fallback", "schema_mismatch")

# 一个都认不出来就是「提示词版本与代码失配」。`raw_text` 不算数 —— 它是我们
# 自己回填的东西，模型给不给都一样，拿它当认领信号会把失配放过去。
_INTENT_RESULT_KEYS: tuple[str, ...] = (
    "condition_groups",
    "qualitative_requirements",
    "exclusions",
    "unstructured_notes",
)

# 这两条是全局粘性的（见 recommendation_agent_tools.STICKY_CONDITIONS 与
# 排除类条件的语义）：放宽多少次都还是不要。模型有时会把它们写进某一组的
# conditions 里，那样只有那一组排除、别的组不排除，与用户的意思正好相反。
# 所以在这里往上提，而不是留在组里。
_GLOBAL_EXCLUSION_COLUMNS: tuple[str, ...] = (
    "excluded_industries_json",
    "unacceptable_risk_flags_json",
)

_OPERATOR_NOTES: dict[str, str] = {
    "gte": "标的对应值不低于该数",
    "lte": "标的对应值不高于该数",
    "eq": "标的对应值必须等于该值",
    "in": "标的对应状态命中数组里任一项即通过",
    "overlap": "标的命中数组里任一项即通过",
    "not_overlap": "标的命中数组里任一项即出局",
    "region_any": '数组，每项形如 {"province": "江苏省", "city": "苏州市"}，只填你确定的层级，任一项命中即通过',
    "requirement_capability": "布尔。填 true 表示本次要求标的具备该能力；不作要求就不要写这个字段",
}

_INDUSTRY_VOCABULARY_NOTES: dict[str, str] = {
    "industry_l1": "只能填一级行业清单里的词",
    "industry_l2": "只能填二级行业清单里的词",
    "industry_any": "只能填一级或二级行业清单里的词",
}


def screening_fields_prompt_json() -> str:
    """24 个可筛字段的说明，注入解析提示词。

    从 `SCREENING_FIELDS` 生成，不手写。手写的那份必然与注册表漂移，而漂移
    的方向永远是「提示词里还留着一个已经不能筛的字段」—— 模型照填，代码照
    丢，用户的话就这么没了。行业闭集不在这里展开：它有自己的两个变量，
    一百多个二级行业塞进来会把这份说明淹掉。
    """
    entries: list[dict[str, Any]] = []
    for field in SCREENING_FIELDS:
        entry: dict[str, Any] = {
            "field": field.column,
            "label": field.label,
            "type": field.value_type,
        }
        if field.enum_values:
            entry["enum"] = list(field.enum_values)
        if field.unit_hint:
            entry["unit"] = field.unit_hint
        note = "；".join(
            part
            for part in (
                _OPERATOR_NOTES.get(field.operator, ""),
                _INDUSTRY_VOCABULARY_NOTES.get(field.value_type, ""),
            )
            if part
        )
        if note:
            entry["note"] = note
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, indent=2)


def _append_intent_text(bucket: list[str], value: Any) -> None:
    text_value = str(value).strip() if value is not None else ""
    if not text_value or len(bucket) >= MAX_INTENT_TEXT_ITEMS:
        return
    text_value = text_value[:MAX_INTENT_TEXT_LENGTH]
    if text_value not in bucket:
        bucket.append(text_value)


def _clean_intent_texts(values: Any) -> list[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for value in values:
        _append_intent_text(cleaned, value)
    return cleaned


def _buyer_field_label(column: str) -> str:
    try:
        return indicator_by_column("buyer_intent", str(column)).label
    except KeyError:
        return str(column)


def _condition_value_text(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    if isinstance(value, list):
        return "、".join(_condition_value_text(item) for item in value)
    if isinstance(value, dict):
        return "".join(str(item) for item in value.values() if item)
    return str(value).strip()


def _leftover_requirements(raw_conditions: dict[str, Any], kept: dict[str, Any]) -> list[str]:
    """模型放进 conditions、却没能变成筛选条件的东西。

    白名单只约束 conditions，不约束用户的表达 —— 被过滤掉的每一条都是合法的
    业务诉求（净利率、PS、溢价、迁址返投留任、字典外的行业词），只是不进初筛。
    没有这个出口，用户说的「净利率要 15% 以上」就既不进条件也不进定性诉求，
    静默蒸发；有了它，那句话会落到深评手里。
    """
    leftovers: list[str] = []
    for key, value in raw_conditions.items():
        column = str(key)
        label = _buyer_field_label(column)
        if column not in kept:
            text_value = _condition_value_text(value)
            leftovers.append(f"{label}：{text_value}" if text_value else label)
            continue
        # 部分保留：行业/枚举数组里被闭集剔掉的那几项同样不能丢。
        if isinstance(value, list) and isinstance(kept[column], list):
            survivors = {str(item).strip().lower() for item in kept[column]}
            for item in value:
                # 地区是唯一一个数组元素为对象的条件，而它会被**改写**成标准
                # 名（浙江 → 浙江省）。拿改写前后的字面量对比，等于把一条已经
                # 生效的条件当成漏网的诉求再报一遍。逐项比对只对标量成立。
                if isinstance(item, dict):
                    continue
                term = str(item).strip()
                if term and term.lower() not in survivors:
                    leftovers.append(f"{label}：{term}")
    return leftovers


def _normalize_group_strength(raw: Any, conditions: dict[str, Any]) -> dict[str, str]:
    """强度只给主 Agent 看，skill 不认。

    没给强度的定量门槛按 `required` 记：漏标的那一条如果被当成「可选」，
    agent 放宽时会先把它丢掉，而它很可能正是用户唯一说死的那个数。
    """
    values = raw if isinstance(raw, dict) else {}
    strength: dict[str, str] = {}
    for column in conditions:
        token = str(values.get(column) or "").strip().lower()
        strength[column] = token if token in CONDITION_EFFECTS else "required"
    return strength


def normalize_intent_parse_result(
    raw: Any,
    *,
    industry_l1_terms: list[str],
    industry_l2_terms: list[str],
    user_message: str,
) -> dict[str, Any]:
    """把模型给的需求快照收敛成可执行的形状。纯函数，不碰 DB、不碰 LLM。

    双出口是这里的全部要点：能过 `normalize_conditions` 的进 `conditions`，
    过不了的进 `qualitative_requirements`，模型自己就没结构化的进
    `unstructured_notes`。三个出口合起来保证**没有任何一句用户的话会凭空消失**。
    """
    data = raw if isinstance(raw, dict) else {}
    if not any(key in data for key in _INTENT_RESULT_KEYS):
        # 返回了 JSON，却一个认得的顶层键都没有 = 提示词版本与代码对不上。
        # 上一轮就是这样翻的车：模板变量写成单花括号，模型收到字面量，输出
        # 全错而全链路零报错，只能靠人读对话记录才发现。所以这里既不抛异常
        # 也不伪造条件，而是把状态标出来，让它在 trace 和消息里响。
        return fallback_intent_parse_result(
            user_message,
            status="schema_mismatch",
            note="解析节点返回的 JSON 里没有任何已知字段，提示词版本可能与代码不匹配",
        )

    parser_notes: list[str] = []
    qualitative = _clean_intent_texts(data.get("qualitative_requirements"))
    notes = _clean_intent_texts(data.get("unstructured_notes"))

    raw_groups = data.get("condition_groups")
    if isinstance(raw_groups, dict):
        raw_groups = [raw_groups]
    if not isinstance(raw_groups, list):
        raw_groups = []
    if len(raw_groups) > MAX_CONDITION_GROUPS:
        parser_notes.append(
            f"条件分组 {len(raw_groups)} 组超过上限 {MAX_CONDITION_GROUPS} 组，"
            f"只保留前 {MAX_CONDITION_GROUPS} 组"
        )
        raw_groups = raw_groups[:MAX_CONDITION_GROUPS]

    hoisted_industries: list[Any] = []
    hoisted_risk: list[Any] = []
    groups: list[dict[str, Any]] = []
    for index, raw_group in enumerate(raw_groups, start=1):
        if not isinstance(raw_group, dict):
            parser_notes.append(f"第 {index} 组不是对象，已忽略")
            continue
        raw_conditions = raw_group.get("conditions")
        raw_conditions = dict(raw_conditions) if isinstance(raw_conditions, dict) else {}
        for column in _GLOBAL_EXCLUSION_COLUMNS:
            value = raw_conditions.pop(column, None)
            if value is None:
                continue
            bucket = hoisted_industries if column == "excluded_industries_json" else hoisted_risk
            bucket.extend(value if isinstance(value, list) else [value])

        conditions, ignored = normalize_conditions(
            raw_conditions,
            industry_l1_terms=industry_l1_terms,
            industry_l2_terms=industry_l2_terms,
        )
        parser_notes.extend(ignored)
        for phrase in _leftover_requirements(raw_conditions, conditions):
            _append_intent_text(qualitative, phrase)
        if not conditions:
            continue
        groups.append(
            {
                "label": str(raw_group.get("label") or "").strip() or f"方案{index}",
                "conditions": conditions,
                "strength": _normalize_group_strength(raw_group.get("strength"), conditions),
            }
        )

    exclusions, exclusion_notes = _normalize_intent_exclusions(
        data.get("exclusions"),
        hoisted_industries=hoisted_industries,
        hoisted_risk=hoisted_risk,
        industry_l1_terms=industry_l1_terms,
        industry_l2_terms=industry_l2_terms,
        qualitative=qualitative,
    )
    parser_notes.extend(exclusion_notes)

    if not groups and not qualitative and not notes and not any(exclusions.values()):
        # 一句话什么都没解析出来（闲聊、纯提问，或者模型给了个空壳）。原话
        # 必须留下：这一栏是「漏掉了什么」唯一看得见的地方。
        _append_intent_text(notes, user_message)

    return {
        "condition_groups": groups,
        "qualitative_requirements": qualitative,
        "exclusions": exclusions,
        "unstructured_notes": notes,
        # 原话由代码回填，不用模型那一份 —— 模型会顺手把它改写成系统术语，
        # 而这一栏存在的意义就是「用户到底说了什么」。
        "raw_text": (user_message or "").strip(),
        "parser_status": "ok",
        "parser_notes": parser_notes,
    }


def _normalize_intent_exclusions(
    raw: Any,
    *,
    hoisted_industries: list[Any],
    hoisted_risk: list[Any],
    industry_l1_terms: list[str],
    industry_l2_terms: list[str],
    qualitative: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """排除项归一。落不进闭集的排除词也要留下，但必须**留成否定句**。

    这里有个方向陷阱：把没归一上的「房地产」丢进 qualitative_requirements
    会读成「想要房地产」，与用户的意思正好相反。所以统一渲染成「不接受 X」。
    """
    data = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    industry_terms: list[str] = []
    for value in [*(data.get("industries") or []), *hoisted_industries]:
        term = str(value).strip() if value is not None else ""
        if term and term not in industry_terms:
            industry_terms.append(term)
    industries: list[str] = []
    if industry_terms:
        coerced, ignored = normalize_conditions(
            {"excluded_industries_json": industry_terms},
            industry_l1_terms=industry_l1_terms,
            industry_l2_terms=industry_l2_terms,
        )
        notes.extend(ignored)
        industries = list(coerced.get("excluded_industries_json") or [])
        survivors = {term.lower() for term in industries}
        for term in industry_terms:
            if term.lower() not in survivors:
                _append_intent_text(qualitative, f"不接受{term}")

    raw_risk = data.get("risk_flags")
    if raw_risk in (None, [], {}) and hoisted_risk:
        raw_risk = hoisted_risk
    elif hoisted_risk and isinstance(raw_risk, list):
        raw_risk = [*raw_risk, *hoisted_risk]
    risk_flags = normalize_unacceptable_risk_flags(raw_risk) or []
    if raw_risk and not risk_flags:
        # 说了但一个都没落进闭集：不写空数组（那是「明确未提及」的结论），
        # 原话转成否定句交给深评。
        notes.append(f"重大风险排除项 {raw_risk} 不在闭集内，已转为定性诉求")
        for value in raw_risk if isinstance(raw_risk, list) else [raw_risk]:
            term = str(value).strip()
            if term:
                _append_intent_text(qualitative, f"不接受{term}")

    return {"industries": industries, "risk_flags": risk_flags}, notes


def fallback_intent_parse_result(
    user_message: str,
    *,
    status: str = "fallback",
    note: str | None = None,
) -> dict[str, Any]:
    """解析没成，但这一轮照跑。

    退化成「没有结构化条件的一轮」比直接报错对用户有用得多：agent 仍然拿得到
    原话，仍然能筛、能答。代价是这一轮没有可审计的条件基线，所以状态必须如实
    标出来，不能假装 ok。
    """
    text_value = (user_message or "").strip()[:MAX_INTENT_TEXT_LENGTH]
    return {
        "condition_groups": [],
        "qualitative_requirements": [text_value] if text_value else [],
        "exclusions": {"industries": [], "risk_flags": []},
        "unstructured_notes": [],
        "raw_text": text_value,
        "parser_status": status,
        "parser_notes": [note] if note else [],
    }


def parse_recommendation_intent(
    db: Session,
    *,
    mode: str,
    user_message: str,
    history_context: str = "",
) -> dict[str, Any]:
    """跑一次需求解析节点，产出用户经过本轮表达后的完整当前需求快照。

    历史原文与本轮消息一起交给模型，由模型判断保留、替换、删除或重置；代码
    只归一化模型给出的完整结果，不从上一轮 JSON 机械累计条件。

    只有「调不通」才降级（节点没配、超时、模型报错）。归一化刻意留在 try 之外：
    把它也包进去的话，归一化里的一个 bug 会被记成 `fallback`，看起来像模型不
    稳定，实际是代码坏了 —— 那正是这个阶段要消灭的那类静默失败。
    """
    try:
        node = _get_query_parser_node_config(db)
        industry_l1_terms = list_l1_terms(db)
        industry_l2_terms = list_l2_terms(db)
        variables = {
            "mode": mode,
            "user_message": user_message,
            "history_context": history_context or "",
            "industry_l1_list": industry_l1_prompt_list(db),
            "industry_l2_list": industry_l2_prompt_list(db),
            "screening_fields_json": screening_fields_prompt_json(),
        }
        messages: list[dict[str, str]] = []
        system_prompt = render_template(node.get("system_prompt"), variables)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": render_template(node["user_prompt_template"], variables)})
        llm_result = call_openai_compatible_chat(
            base_url=node["base_url"],
            api_key_secret_ref=node["api_key_secret_ref"],
            api_key_encrypted=node.get("api_key_encrypted"),
            model_name=node["model_name"],
            messages=messages,
            temperature=node["temperature"],
            top_p=node["top_p"],
            max_tokens=node["max_tokens"],
            timeout_seconds=node["timeout_seconds"] or 30,
            response_format=node["response_format"],
        )
        raw_output = llm_result.parsed_output_json
    except (LlmCallError, ValueError, KeyError) as exc:
        return fallback_intent_parse_result(user_message, note=f"解析节点未产出结果：{exc}")

    result = normalize_intent_parse_result(
        raw_output,
        industry_l1_terms=industry_l1_terms,
        industry_l2_terms=industry_l2_terms,
        user_message=user_message,
    )
    # 哪一版提示词产出的这份快照，写进结果一起落库：失配要响，得先能指认。
    result["prompt_version"] = str(node.get("prompt_version") or "")
    return result


def describe_intent_snapshot(result: dict[str, Any]) -> str:
    """一句中文说明这一轮解析出了什么，给 agent_understanding 消息用。"""
    status = str(result.get("parser_status") or "")
    if status == "fallback":
        return "需求解析节点未能返回结果，本轮按原话继续推荐"
    if status == "schema_mismatch":
        return "需求解析节点返回的结构无法识别（提示词版本可能与代码不匹配），本轮按原话继续推荐"
    parts: list[str] = []
    groups = result.get("condition_groups") or []
    if groups:
        parts.append(f"{len(groups)} 组筛选条件")
    qualitative = result.get("qualitative_requirements") or []
    if qualitative:
        parts.append(f"{len(qualitative)} 条定性诉求")
    exclusions = result.get("exclusions") or {}
    if exclusions.get("industries") or exclusions.get("risk_flags"):
        parts.append("排除项")
    if not parts:
        return "这句话里没有可结构化的筛选条件，已原样记录"
    return "已解析出" + "、".join(parts)


EMPTY_OVERRIDES: dict[str, Any] = {
    "fields": {},
    "removed_fields": [],
    "extra_excluded_industries": [],
    "semantic_preferences": [],
}


def _normalized_overrides(overrides: Any) -> dict[str, Any]:
    data = overrides if isinstance(overrides, dict) else {}
    return {
        "fields": dict(data.get("fields") or {}),
        "removed_fields": list(data.get("removed_fields") or []),
        "extra_excluded_industries": list(data.get("extra_excluded_industries") or []),
        "semantic_preferences": list(data.get("semantic_preferences") or []),
        # 方案停用只作用于本次会话，不改买家需求本身
        "disabled_scenarios": [str(value) for value in (data.get("disabled_scenarios") or [])],
    }


def normalize_scenario_fields(raw: Any) -> dict[str, Any]:
    """Coerce a scenario's own condition values through the shared whitelist.

    Scenarios reuse the override field vocabulary so a value written by the
    intake parser, by the chat parser or by hand all land in the same shape.
    """
    if not isinstance(raw, dict):
        return {}
    fields: dict[str, Any] = {}
    for field, value in raw.items():
        kind = OVERRIDE_FIELD_KINDS.get(field)
        if kind is None:
            continue
        coerced = _coerce_value(kind, value)
        if coerced is not None:
            fields[field] = coerced
    return fields


# 规则只有两态：必须（初筛硬门槛）和优先（只影响排序）。
# 曾经还有第三个取值 deep_eval，名字骗人 —— 深评上下文是把整个 anchor 打包成
# 一个 JSON 交给模型的，从来不按字段分流；那个标签实际只让字段跳过规则打分。
# 现在「不参与规则打分」由 condition_effect 返回 None 表达，不再是可选的规则。
CONDITION_EFFECTS = {"required", "preferred"}


def normalize_condition_effects(raw: Any) -> dict[str, str]:
    """Keep only editable contract fields and the two supported effects."""
    if not isinstance(raw, dict):
        return {}
    allowed = {
        indicator.column
        for indicator in indicators_for("buyer_intent")
        if indicator.effect_editable or indicator.default_effect is not None
    }
    return {
        str(field): str(effect)
        for field, effect in raw.items()
        if str(field) in allowed and str(effect) in CONDITION_EFFECTS
    }


def condition_effect(anchor: dict[str, Any], field: str) -> str | None:
    """这个字段在这次比对里怎么用：required / preferred，或 None（不参与规则打分）。

    方案里显式设过的字段，取值一个方案一份，方案说了算。
    """
    effects = anchor.get("condition_effects_json")
    if isinstance(effects, dict) and str(effects.get(field)) in CONDITION_EFFECTS:
        return str(effects[field])
    # 方案自己写进 fields_json 的字段，是这一档和别档的分界线，必须硬判。
    # 软条件只扣分不冲突，而打分取各档中最好的一档 —— 于是标的会从要求最松的
    # 那一档溜进来，买家的分档等于没写。举个实测过的例子：
    # 「市值≥10亿→盈利≥1000万 / 市值<10亿→盈利≥1亿」，min_market_cap_yuan
    # 注册表默认是 preferred，一个 5亿市值、1500万盈利的标的在第一档只扣分、
    # 不冲突，盈利又够 1000万，就这么进来了。
    # 方案里显式设过规则的字段不走这里 —— 上面那个分支已经返回了。
    if field in (anchor.get("_scenario_fields") or ()):
        return "required"
    # These fields carry their effect in the value itself.  Keeping that
    # interpretation here lets the scorer use the same contract as ordinary
    # fields without accidentally downgrading a ``required`` requirement to
    # the registry's editing default.
    if field in {
        "requires_relocation",
        "requires_return_investment",
        "requires_team_retention",
    }:
        strength = str(anchor.get(field) or "").strip().lower()
        if strength in CONDITION_EFFECTS:
            return strength
        return None
    try:
        return indicator_by_column("buyer_intent", field).default_effect
    except KeyError:
        return None


def merge_scenario_into_anchor(anchor: dict[str, Any], scenario_fields: Any) -> dict[str, Any]:
    """Global intent conditions AND the scenario's own conditions.

    Scenarios are self-contained rather than inheriting from each other, but
    they always combine with the intent-level fields, so editing a global
    exclusion cannot drift between scenarios.
    """
    merged = dict(anchor)
    for field, value in (scenario_fields or {}).items():
        merged[field] = value
    return merged


def confirmation_field_names(raw: Any) -> set[str]:
    """Return fields whose parser suggestions are still awaiting a human decision."""
    if not isinstance(raw, list):
        return set()
    return {
        str(item.get("field") or "").strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("field") or "").strip()
    }


def _confirmation_proposed_values(raw: Any, field: str) -> list[Any]:
    if not isinstance(raw, list):
        return []
    return [
        item.get("proposed_value")
        for item in raw
        if isinstance(item, dict)
        and str(item.get("field") or "").strip() == field
        and item.get("proposed_value") is not None
    ]


def _remove_pending_items(value: Any, proposed_values: list[Any]) -> Any:
    if not isinstance(value, list) or not proposed_values:
        return value
    pending_scalars: set[str] = set()
    pending_objects: list[dict[str, Any]] = []
    for proposed in proposed_values:
        items = proposed if isinstance(proposed, list) else [proposed]
        for item in items:
            if isinstance(item, dict):
                pending_objects.append(item)
            else:
                pending_scalars.add(str(item))

    def pending(item: Any) -> bool:
        if isinstance(item, dict):
            return any(all(item.get(key) == expected for key, expected in candidate.items()) for candidate in pending_objects)
        return str(item) in pending_scalars

    return [item for item in value if not pending(item)]


def suppress_pending_confirmation_fields(
    anchor: dict[str, Any],
    extra_confirmations: Any = None,
) -> dict[str, Any]:
    """Make pending fields invisible to deterministic screening and ranking.

    The original anchor remains intact for LLM deep evaluation. This helper is
    only applied to the copy passed into the rule scorer.
    """
    effective = dict(anchor)
    anchor_confirmations = anchor.get("needs_confirmation_json")
    pending_fields = confirmation_field_names(anchor_confirmations)
    pending_fields.update(confirmation_field_names(extra_confirmations))
    for field in pending_fields:
        kind = OVERRIDE_FIELD_KINDS.get(field)
        proposed_values = _confirmation_proposed_values(anchor_confirmations, field)
        proposed_values.extend(_confirmation_proposed_values(extra_confirmations, field))
        if kind in {"industry_list", "string_list", "region_list"} and proposed_values:
            effective[field] = _remove_pending_items(effective.get(field), proposed_values)
        else:
            effective[field] = [] if kind in {"industry_list", "string_list", "region_list"} else None
        if field == "industries_json":
            effective["industry_primary"] = None
    return effective


def merge_condition_overrides(existing: Any, parse_result: dict[str, Any]) -> dict[str, Any]:
    merged = _normalized_overrides(existing)
    for op in parse_result.get("condition_ops") or []:
        field = op["field"]
        if op["op"] == "set":
            merged["fields"][field] = op["value"]
            if field in merged["removed_fields"]:
                merged["removed_fields"].remove(field)
        elif op["op"] == "remove":
            merged["fields"].pop(field, None)
            if field not in merged["removed_fields"]:
                merged["removed_fields"].append(field)
            if field == "excluded_industries_json":
                merged["extra_excluded_industries"] = []
        elif op["op"] == "exclude":
            if op["value"] not in merged["extra_excluded_industries"]:
                merged["extra_excluded_industries"].append(op["value"])
            if "excluded_industries_json" in merged["removed_fields"]:
                merged["removed_fields"].remove("excluded_industries_json")
    for preference in parse_result.get("semantic_preferences") or []:
        if preference not in merged["semantic_preferences"]:
            merged["semantic_preferences"].append(preference)
    return merged


def apply_overrides_to_anchor(anchor: dict[str, Any], overrides: Any) -> dict[str, Any]:
    """Return a copy of the intent anchor with session overrides applied."""
    data = _normalized_overrides(overrides)
    effective = dict(anchor)
    for field in data["removed_fields"]:
        if field in {"industries_json", "excluded_industries_json"}:
            effective[field] = []
        else:
            effective[field] = None
        if field == "industries_json":
            effective["industry_primary"] = None
    for field, value in data["fields"].items():
        effective[field] = value
    if data["extra_excluded_industries"]:
        existing = effective.get("excluded_industries_json")
        base = [str(item) for item in existing] if isinstance(existing, list) else []
        for term in data["extra_excluded_industries"]:
            if term not in base:
                base.append(term)
        effective["excluded_industries_json"] = base
    return effective


def conditions_snapshot(anchor: dict[str, Any], overrides: Any) -> dict[str, Any]:
    """Active condition values (base + overrides) for display and parser context."""
    effective = apply_overrides_to_anchor(anchor, overrides)
    data = _normalized_overrides(overrides)
    snapshot: dict[str, Any] = {}
    for field in OVERRIDE_FIELD_KINDS:
        value = effective.get(field)
        if value in (None, "", []):
            continue
        snapshot[field] = value
    snapshot["semantic_preferences"] = data["semantic_preferences"]
    return snapshot


def derive_route(parse_result: dict[str, Any] | None) -> str:
    """Deterministic routing from the extraction result (never LLM-decided)."""
    if parse_result is None:
        return "refilter"
    if parse_result.get("condition_ops"):
        return "refilter"
    if parse_result.get("semantic_preferences"):
        return "re_evaluate"
    if parse_result.get("display_ops"):
        return "display"
    if parse_result.get("question"):
        return "question"
    return "noop"


def describe_condition_ops(ops: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for op in ops:
        label = FIELD_LABELS.get(op["field"], op["field"])
        if op["op"] == "remove":
            parts.append(f"取消{label}")
        elif op["op"] == "exclude":
            parts.append(f"排除{op['value']}")
        else:
            value = op["value"]
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            elif isinstance(value, float) and value >= 10000:
                value = _compact_money(value)
            parts.append(f"{label}={value}")
    return "、".join(parts)


def _compact_money(value: float) -> str:
    if value >= 100000000:
        rounded = value / 100000000
        return f"{rounded:.1f}亿".replace(".0亿", "亿")
    if value >= 10000:
        return f"{value / 10000:.0f}万"
    return str(int(value))


def apply_condition_actions(overrides: Any, actions: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Apply deterministic UI actions (chip removal / clear-all) to overrides.

    Returns the new overrides plus a Chinese description for the system reply.
    """
    merged = _normalized_overrides(overrides)
    parts: list[str] = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        op = str(action.get("op") or "").strip()
        if op == "clear_all":
            merged = _normalized_overrides(None)
            parts = ["恢复默认条件"]
            break
        if op == "remove_field":
            field = str(action.get("field") or "").strip()
            if field not in OVERRIDE_FIELD_KINDS:
                continue
            merged["fields"].pop(field, None)
            if field in merged["removed_fields"]:
                merged["removed_fields"].remove(field)
            if field == "excluded_industries_json":
                merged["extra_excluded_industries"] = []
            parts.append(f"移除{FIELD_LABELS.get(field, field)}")
        elif op == "disable_field":
            # Suppress a base (intent-level) condition for this session only.
            field = str(action.get("field") or "").strip()
            if field not in OVERRIDE_FIELD_KINDS:
                continue
            merged["fields"].pop(field, None)
            if field not in merged["removed_fields"]:
                merged["removed_fields"].append(field)
            parts.append(f"临时停用{FIELD_LABELS.get(field, field)}")
        elif op == "remove_exclusion":
            value = str(action.get("value") or "").strip()
            if value in merged["extra_excluded_industries"]:
                merged["extra_excluded_industries"].remove(value)
                parts.append(f"移除排除项{value}")
        elif op == "remove_preference":
            value = str(action.get("value") or "").strip()
            if value in merged["semantic_preferences"]:
                merged["semantic_preferences"].remove(value)
                parts.append("移除偏好")
        elif op in {"disable_scenario", "enable_scenario"}:
            # 方案级操作走同一套 condition_actions 词汇，不另开机制。
            scenario_id = str(action.get("scenario_id") or action.get("value") or "").strip()
            if not scenario_id:
                continue
            label = str(action.get("label") or "").strip() or "方案"
            if op == "disable_scenario":
                if scenario_id not in merged["disabled_scenarios"]:
                    merged["disabled_scenarios"].append(scenario_id)
                    parts.append(f"停用{label}")
            elif scenario_id in merged["disabled_scenarios"]:
                merged["disabled_scenarios"].remove(scenario_id)
                parts.append(f"恢复{label}")
    return merged, "、".join(parts)


def persist_session_overrides(db: Session, session_id: Any, overrides: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            update recommendation_session
            set condition_overrides_json = :overrides,
                updated_at = now()
            where id = :session_id
              and team_id = :team_id
              and workspace_id = :workspace_id
            """
        ).bindparams(bindparam("overrides", type_=JSONB)),
        {
            "session_id": session_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "overrides": overrides,
        },
    )
