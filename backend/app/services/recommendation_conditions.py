"""Turn a recommendation-chat message into structured conditions.

`parse_recommendation_intent` (node `recommendation_query_parser`) returns a
**complete snapshot** of what the user wants now, after the parser reads the
last completed turns and the current message. It is not an incremental patch.
That is what the agent chat链路 needs, because the point of splitting
parsing out of the agent is to have a baseline the agent can only consume,
never invent. (The incremental `condition_ops` parser that fed the old
`/candidates` condition panel was removed with that page in 阶段五 5B.)

The LLM only extracts. Whitelisting and type coercion are derived in code so
they stay deterministic and testable.
"""

from __future__ import annotations

import json
import time
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
)
from backend.app.services.recommendation_trace import (
    RecommendationTraceContext,
    insert_recommendation_node_trace,
)
from backend.app.services.screening_schema import SCREENING_FIELDS, normalize_conditions

QUERY_PARSER_NODE_NAME = "recommendation_query_parser"

def _condition_value_kind(field: str) -> str | None:
    """方案字段 → 归一化形状。0901 起只剩四种，全部由 kind/editor 决定。

    以前这里还有按列名写死的四个分支（控股与并表的 yes_no、上市状态、
    上市地、迁址返投留任对赌的 requirement_strength），它们打在的列本轮
    全部退役 —— 那几条约束现在落进方案的 other_requirements_text 文本。
    """
    indicator = indicator_by_column("buyer_intent_scenario", field)
    if indicator.kind in {"yuan", "ratio"}:
        return "number"
    if indicator.editor in {"multi_enum", "tags"}:
        return "string_list"
    if indicator.editor == "region_multi":
        return "region_list"
    if indicator.kind == "text":
        return "text"
    return None


# 方案与对话覆盖用的是同一份词表，0901 起它来自**方案注册表**：
# 门槛已经不住在 buyer_intent 上了，继续从那边派生只会得到一份空表，
# 而空表不报错 —— 表现是「方案字段一个都写不进去」。
OVERRIDE_FIELD_KINDS: dict[str, str] = {
    indicator.column: kind
    for indicator in indicators_for("buyer_intent_scenario")
    if (kind := _condition_value_kind(indicator.column)) is not None
}

_LISTED_STATUS_VALUES = {"listed", "unlisted", "pre_ipo", "any", "unknown"}
_YES_NO_VALUES = {"yes", "no", "unknown"}
# 上市地 2026-08-07 换成交易所闭集，0828 随双侧皆空退役 —— 取值表留着给
# 覆盖存储里的存量值兜底，不再有任何字段声明指向它。
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
def _get_query_parser_node_config(db: Session) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select
              node.id as node_config_id,
              node.model_name, node.temperature, node.top_p, node.max_tokens,
              node.timeout_seconds, node.response_format,
              provider.id as provider_config_id, provider.provider_name,
              provider.base_url, provider.api_key_secret_ref, provider.api_key_encrypted,
              prompt.id as prompt_template_id,
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

# 全局粘性排除（见 recommendation_agent_tools.STICKY_CONDITIONS）：放宽多少次
# 都还是不要。模型有时会把它写进某一组的 conditions 里，那样只有那一组排除、
# 别的组不排除，与用户的意思正好相反 —— 所以在这里往上提，而不是留在组里。
#
# excluded_industries_json 2026-08-28 起**不再是可筛字段**（行业条件整组退役），
# 但仍然留在这份清单里，理由变了：现在往上提是为了**把它救下来**。
# 不提的话它会留在组条件里，被 normalize_conditions 当成「不是可筛字段，已忽略」
# 丢掉 —— 用户说的「不要房地产」就此消失。提上来之后它进 exclusions.industries，
# 再渲染成「不接受房地产」进 qualitative_requirements，由主 Agent 读业务摘要时执行。
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
    # 方向必须写反过来：同一个形状（省市区数组）在 region_none 下是「命中即出局」。
    # 照 region_any 那句写，模型会把「不要新疆」理解成「只要新疆」，而 SQL 照做且不报错。
    "region_none": '数组，每项形如 {"province": "新疆维吾尔自治区"}，只填你确定的层级，任一项命中即出局',
    "requirement_capability": "布尔。填 true 表示本次要求标的具备该能力；不作要求就不要写这个字段",
}


def screening_fields_prompt_json() -> str:
    """可筛字段的说明，注入解析提示词。

    从 `SCREENING_FIELDS` 生成，不手写。手写的那份必然与注册表漂移，而漂移
    的方向永远是「提示词里还留着一个已经不能筛的字段」—— 模型照填，代码照
    丢，用户的话就这么没了。

    行业词表说明 0828 一并删除：需求侧的行业条件整组退役，这份清单里已经
    没有任何字段需要外部词表（地区走省份归一，其余都是注册表里的闭集）。
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
        note = _OPERATOR_NOTES.get(field.operator, "")
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


def normalize_intent_parse_result(raw: Any, *, user_message: str) -> dict[str, Any]:
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

        conditions, ignored = normalize_conditions(raw_conditions)
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
    qualitative: list[str],
) -> tuple[dict[str, Any], list[str]]:
    """排除项归一。排除词必须**留成否定句**。

    这里有个方向陷阱：把「房地产」直接丢进 qualitative_requirements 会读成
    「想要房地产」，与用户的意思正好相反。所以统一渲染成「不接受 X」。

    0828 起排除行业**没有 SQL 出口了**（行业条件整组退役），所以每一个词都走
    这条文字路径 —— 以前只有过不了字典的那些才走。`exclusions["industries"]`
    仍然如实返回，它服务快照展示与 trace，不再编译成筛选条件
    （见 recommendation_agent_policy._compile_exclusions）。
    """
    data = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    industry_terms: list[str] = []
    for value in [*(data.get("industries") or []), *hoisted_industries]:
        term = str(value).strip() if value is not None else ""
        if term and term not in industry_terms:
            industry_terms.append(term)
    industries: list[str] = list(industry_terms)
    for term in industry_terms:
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
    trace_context: RecommendationTraceContext | None = None,
) -> dict[str, Any]:
    """跑一次需求解析节点，产出用户经过本轮表达后的完整当前需求快照。

    历史原文与本轮消息一起交给模型，由模型判断保留、替换、删除或重置；代码
    只归一化模型给出的完整结果，不从上一轮 JSON 机械累计条件。

    只有「调不通」才降级（节点没配、超时、模型报错）。归一化刻意留在 try 之外：
    把它也包进去的话，归一化里的一个 bug 会被记成 `fallback`，看起来像模型不
    稳定，实际是代码坏了 —— 那正是这个阶段要消灭的那类静默失败。
    """
    node: dict[str, Any] | None = None
    messages: list[dict[str, str]] = []
    trace_input = {
        "mode": mode,
        "user_message": user_message,
        "history_context": history_context or "",
    }
    started = time.perf_counter()
    try:
        node = _get_query_parser_node_config(db)
        variables = {
            "mode": mode,
            "user_message": user_message,
            "history_context": history_context or "",
            "industry_l1_list": industry_l1_prompt_list(db),
            "industry_l2_list": industry_l2_prompt_list(db),
            "screening_fields_json": screening_fields_prompt_json(),
        }
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
        # 降级也要留一行 trace。「节点根本没被调用」和「调了但超时降级了」在设置页
        # 上都显示成一片空白，可这两件事的排查方向完全相反。
        insert_recommendation_node_trace(
            db,
            context=trace_context,
            node_name=QUERY_PARSER_NODE_NAME,
            node_config=node,
            status="failed",
            input_json=trace_input,
            prompt_messages=messages,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_message=str(exc),
            metadata={"parser_status": "fallback"},
        )
        return fallback_intent_parse_result(user_message, note=f"解析节点未产出结果：{exc}")

    result = normalize_intent_parse_result(raw_output, user_message=user_message)
    # 哪一版提示词产出的这份快照，写进结果一起落库：失配要响，得先能指认。
    result["prompt_version"] = str(node.get("prompt_version") or "")
    parser_status = str(result.get("parser_status") or "")
    insert_recommendation_node_trace(
        db,
        context=trace_context,
        node_name=QUERY_PARSER_NODE_NAME,
        node_config=node,
        # schema_mismatch 记成 failed：模型是回了话，但回的东西这一版代码用不了，
        # 对管理员来说和调不通同样需要处理。
        status="succeeded" if parser_status == "ok" else "failed",
        input_json=trace_input,
        prompt_messages=messages,
        raw_output_text=llm_result.raw_output_text,
        parsed_output_json=raw_output if isinstance(raw_output, dict) else None,
        latency_ms=int(llm_result.latency_ms or 0),
        prompt_tokens=llm_result.prompt_tokens,
        completion_tokens=llm_result.completion_tokens,
        total_tokens=llm_result.total_tokens,
        metadata={
            "parser_status": parser_status,
            "condition_group_count": len(result.get("condition_groups") or []),
        },
    )
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


# 强度只有两态：必须（硬门槛）和优先（只影响排序）。
# 曾经还有第三个取值 deep_eval，名字骗人 —— 深评上下文是把整个 anchor 打包成
# 一个 JSON 交给模型的，从来不按字段分流；那个标签实际只让字段跳过规则打分。
#
# 2026-08-28：`buyer_intent.condition_effects_json` 与它的归一函数
# `normalize_condition_effects` 一起退役（方案 0828 判决三）。那一列的三个消费方
# （前端角标、深评上下文的「条件作用」、解析写入路径）本轮全部拆掉，
# 而**筛选**消费方在阶段五 5B 拆旧链路时就已经没了 —— 注册表里那句
# 「recommendation_flow.py 用它放宽三道硬门槛」是过期注释，grep 过没有这个人。
#
# 这个词表本身还有两个真实用户，所以留着：
#   1. `_normalize_group_strength`：对话链路的条件强度由解析节点输出，
#      由主 Agent 的调用策略表达，与已退役的那一列是两套东西。
#   2. `buyer_intent_parse` 的待确认项：一条 needs_confirmation 可以带 effect
#      说明「这个门槛是硬是软还没定」。
CONDITION_EFFECTS = {"required", "preferred"}


