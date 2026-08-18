"""对话链路的深评：逐条判定定性诉求，然后按匹配程度重排序。

阶段二把用户的话拆成了两半：能翻译成 SQL 的进 `condition_groups`，翻译不了的进
`qualitative_requirements`（「具备地区产业优势」「有成熟的海外仓网络」「与我们现有
业务有协同」）。后一半至今无人消费 —— 解析出来了、落库了，然后就停在那里。这个
模块是它的消费者：一次干净上下文的 LLM 调用，拿到全部候选的完整画像，**逐条判定
每个定性诉求，再按判定结果重排序**。

与旧的 `/candidates` 深评（`jobs/handlers/recommendation.py` 里那一组 `_run_deep_eval_*`）
是**两条并存的路，不是它的改版**。旧路服务的接口还在、测试还在，阶段五整体拆除；
在那之前谁也别改谁。三处不同写在这里，免得日后被「顺手统一」回去：

1. **不评级、不打分，只排序。** 分档是绝对判断（要求模型心里有一把看不见的标尺），
   排序是相对判断（两两比较），LLM 对后者稳定得多。
2. **不分片，整体提交。** 这是取消分档的必然结果：分档时两片的结果能靠同一把标尺
   合并，纯排序时 A 片的 rank 1 和 B 片的 rank 1 谁靠前**没有任何依据**。硬要合并
   就得再跑一次「合并评估」，那还不如一开始就整体提交。40 家 × 800 字符 ≈ 3.2 万字，
   当前模型放得下。
3. **定性诉求是独立输入变量**，不是塞进 `anchor_context` 的一段文本 —— 它是深评的
   主要工作对象，提示词要能明确指令「逐条判定这些」。

叶子模块：只依赖 `llm_client` / `prompting` / `profile_sections` / `registry`。
**不 import `recommendation_flow` 与 `jobs.handlers.*`**，否则成环。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.prompting import render_template
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.nodes import deep_eval_node_by_mode
from backend.app.services.profile_sections import (
    buyer_party_fact_block,
    load_profile_sections,
    render_profile_text,
)

# 深评这一轮到底怎么样了，如实写进消息与 trace。
#
# `schema_mismatch` 专抓「提示词版本与代码失配」：模型返回了东西，但一个认识的键
# 都没有。这是阶段二吃过的亏 —— v0.1.0 提示词把变量写成单花括号，模型收到字面量，
# 输出全错但**全链路零报错**，只能靠人读对话记录才发现。两种失败都必须有名字。
DEEP_EVAL_STATUSES: tuple[str, ...] = ("ok", "unavailable", "schema_mismatch")

# 逐条判定的闭集。`无法判断` 是**合法答案**，不是失败的代名词 —— 猜出来的「符合」
# 比诚实的「无法判断」有害得多，所以它必须是一个模型敢选的选项。
VERDICT_VALUES: tuple[str, ...] = ("符合", "不符合", "无法判断")
VERDICT_UNKNOWN = "无法判断"

# 模型把所有候选都剔掉时保底放回的家数。「一家都没有」比「有几家但都不理想」糟糕
# 得多 —— 后者至少给了客户经理判断材料，前者只会让他把需求重说一遍。
FALLBACK_KEEP_COUNT = 3

MAX_FIT_POINTS = 5
MAX_RESULT_TEXT_LENGTH = 300

# 节点没配超时值时用它。整体提交之后单次调用要读完全部候选，比旧的分片调用长得多。
DEFAULT_DEEP_EVAL_TIMEOUT_SECONDS = 300

# 一个认得的顶层键都没有 = 提示词版本与代码对不上。与
# `recommendation_conditions._INTENT_RESULT_KEYS` 是同一个手法、同一个理由。
_DEEP_EVAL_RESULT_KEYS: tuple[str, ...] = ("ranked", "dropped")

# 对「合不合适」没有贡献、纯占位的字段。3 万字的预算里每个字都该有用。
# `facts` 现在本来就不带这几个（见 `recommendation_flow._target_facts`），这份清单
# 是防回归的：哪天那边开始带了，深评不会顺手把它们一起喂进去。
_NOISE_FACT_KEYS: frozenset[str] = frozenset(
    {"pe_source_type", "financial_period_label", "valuation_date", "asking_price_date"}
)

# 画像可能一个字都没有（测试库里字段不全是常态）。**必须显式标注**，不能给个空
# 字符串让模型以为这家真的没内容 —— 那会让「没查到」被读成「不符合」。
NO_PROFILE_TEXT = "（暂无画像信息。信息缺失不等于不符合，判不了就写「无法判断」）"

# 传错实体类型不会报错，只会返回空画像，然后深评在没有画像的情况下照常给出排序，
# **看起来完全正常**。所以按方向查表，查不到就报错，不留「猜一个」的余地。
_ENTITY_TYPE_BY_MODE: dict[str, str] = {
    "buyer_to_target": "seller_target",
    "target_to_buyer": "buyer_intent",
}
_NAME_KEY_BY_MODE: dict[str, str] = {
    "buyer_to_target": "seller_target_name",
    "target_to_buyer": "buyer_intent_name",
}

# 没给 rank 的条目排在给了 rank 的后面，组内保持模型给出的先后顺序。
_RANK_TAIL = 10**6


# =========================================================================
# 节点配置
# =========================================================================


def _get_deep_eval_node_config(db: Session, mode: str) -> dict[str, Any]:
    """本链路的深评节点配置。**取不到就是取不到，不回落共用节点。**

    `jobs/handlers/recommendation.py` 里那个同名函数在方向节点未配置时会回落到共用的
    `recommendation_deep_eval`，对旧链路是对的 —— 两个方向共享同一份旧提示词。
    这条链路不能这么干：新形态的提示词只装在方向节点上，回落会拿到旧形态提示词
    （分档、分片、旧 schema），模型返回的东西对不上新代码，**而且不会报错**。
    取不到配置就按「深评不可用」降级，不要悄悄换一个节点跑。
    """
    node_name = deep_eval_node_by_mode().get(mode)
    if not node_name:
        raise ValueError(f"No deep eval node is registered for mode {mode!r}")
    row = db.execute(
        text(
            """
            select
              node.node_name, node.model_name, node.temperature, node.top_p,
              node.max_tokens, node.timeout_seconds, node.response_format,
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
            "node_name": node_name,
        },
    ).mappings().one_or_none()
    if row is None or not row.get("base_url") or not row.get("user_prompt_template"):
        raise ValueError(f"Deep eval node is not configured: {node_name}")
    return dict(row)


# =========================================================================
# 输入
# =========================================================================


def _candidate_facts(facts: Any) -> dict[str, Any]:
    if not isinstance(facts, dict):
        return {}
    return {key: value for key, value in facts.items() if key not in _NOISE_FACT_KEYS}


def build_deep_eval_candidates(
    db: Session,
    *,
    mode: str,
    candidates_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """本轮全部候选的完整画像，按初筛序（首次被登记的顺序）。

    ``group_hit_count`` 与 ``search_hit_count`` 刻意分开：前者表示命中过几个
    不同需求组，是深评的强信号；后者只表示在几次筛选中重复出现，是稳定性解释。
    同一组的完整筛和放宽筛都命中，前者仍然只能算 1。
    """
    entity_type = _ENTITY_TYPE_BY_MODE.get(mode)
    name_key = _NAME_KEY_BY_MODE.get(mode)
    if not entity_type or not name_key:
        raise ValueError(f"No deep eval candidate shape is registered for mode {mode!r}")

    ids = [key for key in candidates_by_id if str(key or "").strip()]
    sections_by_id = load_profile_sections(db, entity_type=entity_type, entity_ids=ids)

    items: list[dict[str, Any]] = []
    for candidate_id in ids:
        candidate = candidates_by_id.get(candidate_id) or {}
        profile = render_profile_text(sections_by_id.get(candidate_id), entity_type=entity_type)
        hits = [dict(item) for item in (candidate.get("screening_hits") or []) if isinstance(item, dict)]
        relaxed_fields: list[str] = []
        for hit in hits:
            for value in hit.get("relaxed_fields") or []:
                field = str(value or "").strip()
                if field and field not in relaxed_fields:
                    relaxed_fields.append(field)
        items.append(
            {
                "id": candidate_id,
                "name": candidate.get(name_key),
                "full_conditions": any(bool(hit.get("full_conditions")) for hit in hits),
                "relaxed_fields": relaxed_fields,
                "matched_group_ids": list(candidate.get("matched_group_ids") or []),
                "matched_search_call_ids": list(candidate.get("matched_search_call_ids") or []),
                "group_hit_count": int(candidate.get("group_hit_count") or 0),
                "search_hit_count": int(candidate.get("search_hit_count") or 0),
                "screening_hits": hits,
                "facts": _candidate_facts(candidate.get("facts")),
                "profile": profile or NO_PROFILE_TEXT,
            }
        )
    return items


def build_anchor_context(
    snapshot: dict[str, Any],
    *,
    party_facts: str = "",
) -> str:
    """需求快照渲染成给模型读的一段文本。定性诉求不在这里 —— 它有自己的变量。

    结构化条件要写进来，但不能再笼统宣称每家都通过完整门槛：4B 允许 Agent 在
    有真实召回依据时放宽。每家的 ``full_conditions / relaxed_fields /
    screening_hits`` 才是它实际通过了什么的事实源。
    """
    data = snapshot if isinstance(snapshot, dict) else {}
    parts: list[str] = []

    raw_text = str(data.get("raw_text") or "").strip()
    if raw_text:
        parts.append(f"【用户原话】\n{raw_text}")

    groups = data.get("condition_groups") or []
    if groups:
        parts.append(
            "【当前需求的完整条件基线】\n"
            + json.dumps(groups, ensure_ascii=False, default=str)
        )

    exclusions = data.get("exclusions") if isinstance(data.get("exclusions"), dict) else {}
    if exclusions.get("industries") or exclusions.get("risk_flags"):
        parts.append(
            "【始终由代码强制执行的排除项】\n"
            + json.dumps(exclusions, ensure_ascii=False, default=str)
        )

    notes = [str(value).strip() for value in (data.get("unstructured_notes") or []) if str(value or "").strip()]
    if notes:
        parts.append("【未结构化的残留表述（可能藏着没被条件覆盖的要求）】\n" + "\n".join(f"- {note}" for note in notes))

    status = str(data.get("parser_status") or "")
    if status and status != "ok":
        # 快照本身就是降级来的：定性诉求里只有用户原话一条。照跑，深评仍然有意义，
        # 但模型该知道自己拿到的不是一份完整的结构化基线。
        parts.append(
            f"【提示】本轮需求解析是降级结果（parser_status={status}），"
            "结构化条件可能缺失，请以用户原话为准。"
        )

    if party_facts:
        parts.append(party_facts)

    return "\n\n".join(parts)


# =========================================================================
# 输出归一化（纯函数，不碰 DB、不碰 LLM）
# =========================================================================


def _clean_text(value: Any) -> str | None:
    text_value = str(value).strip() if value is not None else ""
    return text_value[:MAX_RESULT_TEXT_LENGTH] or None


def _optional_rank(value: Any) -> int | None:
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    return rank if rank >= 0 else None


def _normalize_verdicts(
    raw: Any,
    *,
    allowed: set[str],
    candidate_id: str,
) -> tuple[dict[str, str], list[str]]:
    """逐条判定归一。**键必须来自 `qualitative_requirements` 原文。**

    模型自创的键一律丢弃并记进 notes —— 不是因为它一定错，而是因为「模型判定了
    一条谁也没提过的要求」这件事，静默吞掉就再也没人知道。值不在闭集内的归成
    `无法判断`：宁可少一条结论，不要多一条编出来的结论。
    """
    notes: list[str] = []
    if raw in (None, {}, []):
        return {}, notes
    if not isinstance(raw, dict):
        return {}, [f"{candidate_id} 的 qualitative_verdicts 不是对象，已整体忽略"]

    verdicts: dict[str, str] = {}
    for key, value in raw.items():
        requirement = str(key).strip()
        if requirement not in allowed:
            notes.append(f"{candidate_id} 判定了一条不在定性诉求里的键，已丢弃：{requirement[:60] or '(空)'}")
            continue
        verdict = str(value).strip() if value is not None else ""
        if verdict not in VERDICT_VALUES:
            notes.append(
                f"{candidate_id} 对「{requirement[:30]}」给出的判定「{verdict[:30] or '(空)'}」"
                f"不在闭集内，按{VERDICT_UNKNOWN}处理"
            )
            verdict = VERDICT_UNKNOWN
        verdicts[requirement] = verdict
    return verdicts, notes


def _fit_points(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    points: list[str] = []
    for value in raw:
        point = _clean_text(value)
        if point and point not in points:
            points.append(point)
        if len(points) >= MAX_FIT_POINTS:
            break
    return points


def normalize_deep_eval_result(
    raw: Any,
    *,
    candidate_ids: list[str],
    qualitative_requirements: list[str],
) -> dict[str, Any]:
    """把模型给的排序收敛成可执行的形状。纯函数，不碰 DB、不碰 LLM。

    三条守则，每条都对应一次「看起来完全正常」的失败：
    - 模型编的 id 一律丢弃并记 notes（不是静默丢）
    - 没被提到的候选归入 `uncovered` 并缀在 `ranked` 末尾 —— **漏判不等于淘汰**
    - 全被剔光时保底放回前 3 家，并标注 `fallback_reason`
    """
    data = raw if isinstance(raw, dict) else {}
    if not any(key in data for key in _DEEP_EVAL_RESULT_KEYS):
        # 返回了 JSON，却一个认得的顶层键都没有 = 提示词版本与代码对不上。
        # 既不抛异常也不伪造排序：ranked 保持空，让状态自己在消息与 trace 里响。
        return {
            "deep_eval_status": "schema_mismatch",
            "ranked": [],
            "dropped": [],
            "uncovered": [],
            "fallback_reason": None,
            "notes": ["深评节点返回的 JSON 里没有 ranked / dropped，提示词版本可能与代码不匹配"],
        }

    notes: list[str] = []
    order_by_id = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
    allowed = {str(value).strip() for value in qualitative_requirements if str(value or "").strip()}

    ranked, ranked_notes = _collect_ranked(data.get("ranked"), order_by_id=order_by_id, allowed=allowed)
    notes.extend(ranked_notes)
    ranked_ids = {item["id"] for item in ranked}

    dropped, dropped_notes = _collect_dropped(
        data.get("dropped"), order_by_id=order_by_id, ranked_ids=ranked_ids
    )
    notes.extend(dropped_notes)
    dropped_ids = {item["id"] for item in dropped}

    uncovered = [
        candidate_id
        for candidate_id in candidate_ids
        if candidate_id not in ranked_ids and candidate_id not in dropped_ids
    ]

    fallback_reason: str | None = None
    if not ranked and not uncovered and dropped:
        # 剔成了空集。保底取初筛序前 3 家放回来，模型给的剔除理由留在 risks 里 ——
        # 客户经理需要的是判断材料，不是一句「没有合适的」。
        rescued = sorted(dropped, key=lambda item: order_by_id[item["id"]])[:FALLBACK_KEEP_COUNT]
        rescued_ids = {item["id"] for item in rescued}
        dropped = [item for item in dropped if item["id"] not in rescued_ids]
        ranked = [
            {
                "id": item["id"],
                "rank": position,
                "qualitative_verdicts": {},
                "fit_points": [],
                "risks": item.get("reason"),
                "info_gaps": None,
                "fallback": True,
            }
            for position, item in enumerate(rescued, start=1)
        ]
        fallback_reason = "all_dropped"
        notes.append(
            f"模型把全部 {len(candidate_ids)} 家候选都剔除了，"
            f"保底按初筛序放回 {len(ranked)} 家"
        )

    for candidate_id in uncovered:
        # 模型压根没提到它。缀在末尾而不是丢掉：漏判不等于淘汰。
        ranked.append(
            {
                "id": candidate_id,
                "rank": len(ranked) + 1,
                "qualitative_verdicts": {},
                "fit_points": [],
                "risks": None,
                "info_gaps": None,
                "uncovered": True,
            }
        )
    if uncovered:
        notes.append(f"{len(uncovered)} 家候选模型未提及，已按初筛序缀在排序末尾")

    return {
        "deep_eval_status": "ok",
        "ranked": ranked,
        "dropped": dropped,
        "uncovered": uncovered,
        "fallback_reason": fallback_reason,
        "notes": notes,
    }


def _collect_ranked(
    raw: Any,
    *,
    order_by_id: dict[str, int],
    allowed: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return [], []

    notes: list[str] = []
    decorated: list[tuple[int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            notes.append(f"ranked[{position}] 不是对象，已忽略")
            continue
        candidate_id = str(item.get("id") or "").strip()
        if candidate_id not in order_by_id:
            notes.append(f"ranked 里的 id 不在本轮候选集内，已丢弃：{candidate_id[:60] or '(空)'}")
            continue
        if candidate_id in seen:
            notes.append(f"ranked 里 id 重复，只保留第一条：{candidate_id}")
            continue
        seen.add(candidate_id)

        verdicts, verdict_notes = _normalize_verdicts(
            item.get("qualitative_verdicts"), allowed=allowed, candidate_id=candidate_id
        )
        notes.extend(verdict_notes)

        rank = _optional_rank(item.get("rank"))
        if rank is None:
            notes.append(f"{candidate_id} 没给可用的 rank，按模型给出的先后顺序排")
        decorated.append(
            (
                rank if rank is not None else _RANK_TAIL + position,
                position,
                {
                    "id": candidate_id,
                    "qualitative_verdicts": verdicts,
                    "fit_points": _fit_points(item.get("fit_points")),
                    "risks": _clean_text(item.get("risks")),
                    "info_gaps": _clean_text(item.get("info_gaps")),
                },
            )
        )

    decorated.sort(key=lambda row: row[:2])
    ranked = [{**payload, "rank": position} for position, (_, _, payload) in enumerate(decorated, start=1)]
    return ranked, notes


def _collect_dropped(
    raw: Any,
    *,
    order_by_id: dict[str, int],
    ranked_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return [], []

    notes: list[str] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            notes.append(f"dropped[{position}] 不是对象，已忽略")
            continue
        candidate_id = str(item.get("id") or "").strip()
        if candidate_id not in order_by_id:
            notes.append(f"dropped 里的 id 不在本轮候选集内，已丢弃：{candidate_id[:60] or '(空)'}")
            continue
        if candidate_id in ranked_ids:
            # 两边都写了。留在 ranked：那一侧带着判定依据，信息更全。
            notes.append(f"{candidate_id} 同时出现在 ranked 与 dropped，按 ranked 处理")
            continue
        if candidate_id in seen:
            notes.append(f"dropped 里 id 重复，只保留第一条：{candidate_id}")
            continue
        seen.add(candidate_id)
        dropped.append({"id": candidate_id, "reason": _clean_text(item.get("reason"))})
    return dropped, notes


# =========================================================================
# 跑一次深评
# =========================================================================


def unavailable_deep_eval_result(note: str) -> dict[str, Any]:
    """深评调不通。**本轮不中断** —— 退化成「没有深评的一轮」，agent 的原始名单照常输出。

    但状态要如实标出来，不能假装成功，也不能假装「模型认为一家都不合适」。
    """
    return {
        "deep_eval_status": "unavailable",
        "ranked": [],
        "dropped": [],
        "uncovered": [],
        "fallback_reason": None,
        "notes": [note] if note else [],
    }


def run_recommendation_deep_eval(
    db: Session,
    *,
    mode: str,
    intent_snapshot: dict[str, Any],
    candidates_by_id: dict[str, dict[str, Any]],
    buyer_party_id: Any = None,
) -> dict[str, Any]:
    """跑一次深评节点，产出这一轮的定性判定与排序。

    只有「调不通」才降级（节点没配、超时、模型报错）。归一化刻意留在 try 之外：
    把它也包进去的话，归一化里的一个 bug 会被记成 `unavailable`，看起来像模型不
    稳定，实际是代码坏了 —— 与 `parse_recommendation_intent` 同一个理由。

    `buyer_party_id` 目前在对话链路里恒为 None：agent 会话是匿名的，不锚定任何
    买家主体，买方自身情况只存在于用户原话里（已进 `anchor_context`）。参数留着
    是为了锚定式调用（从买家需求详情页发起）接上来时不用改签名。
    """
    qualitative = [
        str(value).strip()
        for value in (intent_snapshot.get("qualitative_requirements") or [])
        if str(value or "").strip()
    ]
    started = time.perf_counter()
    try:
        node = _get_deep_eval_node_config(db, mode)
        items = build_deep_eval_candidates(db, mode=mode, candidates_by_id=candidates_by_id)
        if not items:
            raise ValueError("本轮没有候选，深评无从做起")
        variables = {
            "mode": mode,
            "anchor_context": build_anchor_context(
                intent_snapshot,
                party_facts=buyer_party_fact_block(db, buyer_party_id),
            ),
            "candidates_json": json.dumps(items, ensure_ascii=False, default=str),
            "qualitative_requirements_json": json.dumps(qualitative, ensure_ascii=False),
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
            timeout_seconds=node["timeout_seconds"] or DEFAULT_DEEP_EVAL_TIMEOUT_SECONDS,
            response_format=node["response_format"],
        )
        raw_output = llm_result.parsed_output_json
    except (LlmCallError, ValueError, KeyError) as exc:
        return {
            **unavailable_deep_eval_result(f"深评节点未产出结果：{exc}"),
            "mode": mode,
            "qualitative_requirements": qualitative,
            "candidate_count": len(candidates_by_id),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    result = normalize_deep_eval_result(
        raw_output,
        candidate_ids=[item["id"] for item in items],
        qualitative_requirements=qualitative,
    )
    result.update(
        {
            "mode": mode,
            "qualitative_requirements": qualitative,
            "candidate_count": len(items),
            "candidate_group_hit_counts": {
                item["id"]: item["group_hit_count"] for item in items
            },
            "candidate_search_hit_counts": {
                item["id"]: item["search_hit_count"] for item in items
            },
            # 哪一版提示词、哪个模型产出的这份排序，一起落库：失配要响，得先能指认。
            "node_name": node.get("node_name"),
            "prompt_version": str(node.get("prompt_version") or ""),
            "model_name": str(node.get("model_name") or ""),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "total_tokens": llm_result.total_tokens,
        }
    )
    return result


def describe_deep_eval_result(result: dict[str, Any]) -> str:
    """一句中文说明这一轮深评做了什么，给 `agent_deep_eval` 消息用。"""
    status = str(result.get("deep_eval_status") or "")
    if status == "unavailable":
        return "深评节点未能返回结果，本轮按 agent 的原始名单输出"
    if status == "schema_mismatch":
        return "深评节点返回的结构无法识别（提示词版本可能与代码不匹配），本轮按 agent 的原始名单输出"
    ranked = result.get("ranked") or []
    dropped = result.get("dropped") or []
    parts = [f"已对 {len(ranked)} 家候选重排序"]
    requirements = result.get("qualitative_requirements") or []
    if requirements:
        parts.append(f"逐条判定 {len(requirements)} 条定性诉求")
    if dropped:
        parts.append(f"剔除 {len(dropped)} 家")
    if result.get("fallback_reason") == "all_dropped":
        parts.append("（模型剔光了全部候选，已保底放回前几家）")
    return "，".join(parts)
