"""Tools the recommendation agent drives, and the budgets that keep it honest.

The agent orchestrates; it never sees the library. Screening stays in SQL and
in the scoring code (`_candidate_targets_for_intent`) exactly as before — the
agent only chooses the filter arguments, reads back a compact digest, and
decides whether to search again. That boundary is the hard rule from
`AGENTS.md`: 初筛与打分必须代码化，禁止全库打包给 LLM.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import ToolCall
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.profile_sections import load_profile_sections, render_profile_text
from backend.app.services.recommendation_conditions import coerce_condition_value
from backend.app.services.relation_flow import DEEP_PROGRESS_STATUSES

# 预算。超了不是抛异常终止运行，而是把「你已经用完」作为工具结果回给模型，
# 让它用手上的信息收尾 —— 跟 tool_loop 处理工具报错的策略一致。
MAX_SEARCH_CALLS = 6
MAX_SEARCH_RESULTS_PER_CALL = 30
DEFAULT_SEARCH_RESULTS_PER_CALL = 20
MAX_DETAIL_TARGETS_TOTAL = 12
MAX_ASK_USER_CALLS = 1
MAX_ASK_USER_QUESTIONS = 3

# 这一份是暴露给模型的过滤器白名单。键必须是 buyer_intent 的列名，
# 因为它们会被直接放进打分用的 anchor；实际取值仍由
# `coerce_condition_value` 按条件契约校验，模型写错类型就被丢掉。
_FILTER_PROPERTIES: dict[str, dict[str, Any]] = {
    "industries_json": {
        "type": "array",
        "items": {"type": "string"},
        "description": "目标行业，用一级行业名。留空表示不限行业。",
    },
    "excluded_industries_json": {
        "type": "array",
        "items": {"type": "string"},
        "description": "明确排除的行业或关键词。",
    },
    "region_scope_summary": {
        "type": "string",
        "description": "地区范围，例如「华东」「浙江、江苏」「杭州」。",
    },
    "min_net_profit_yuan": {"type": "number", "description": "净利润下限，单位元。2000 万写 20000000。"},
    "min_revenue_yuan": {"type": "number", "description": "营业收入下限，单位元。"},
    "max_pe": {"type": "number", "description": "PE 倍数上限。"},
    "min_valuation_yuan": {"type": "number", "description": "估值下限，单位元。"},
    "max_valuation_yuan": {"type": "number", "description": "估值上限（预算上限），单位元。"},
    "max_debt_ratio": {"type": "number", "description": "资产负债率上限，0-1 之间的小数。"},
    "requires_control": {
        "type": "string",
        "enum": ["yes", "no", "unknown"],
        "description": "是否要求取得控股权。",
    },
    "requires_consolidation": {
        "type": "string",
        "enum": ["yes", "no", "unknown"],
        "description": "是否要求能并表。",
    },
    "preferred_listed_status": {
        "type": "string",
        "enum": ["listed", "unlisted", "pre_ipo", "any", "unknown"],
        "description": "对标的上市状态的偏好。",
    },
}

SEARCH_TARGETS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_targets",
        "description": (
            "按结构化条件在标的库里初筛，返回候选摘要与漏斗计数。"
            "可以多次调用来试不同条件组合（例如先严格筛，命中太少就放宽某一项）。"
            "只想知道某个条件下有多少家时，用 count_only=true，成本低很多。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "筛选条件。只填用户明确表达或可合理推断的项，不要凭空补。",
                    "properties": _FILTER_PROPERTIES,
                },
                "limit": {
                    "type": "integer",
                    "description": f"返回条数，默认 {DEFAULT_SEARCH_RESULTS_PER_CALL}，上限 {MAX_SEARCH_RESULTS_PER_CALL}。",
                },
                "count_only": {
                    "type": "boolean",
                    "description": "只返回命中数量，不返回候选明细。用来低成本试探条件宽窄。",
                },
                "note": {
                    "type": "string",
                    "description": "这次筛选想验证什么，一句话。会展示给用户看，让他知道你做了什么。",
                },
            },
            "required": ["filters"],
        },
    },
}

GET_TARGET_DETAIL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_target_detail",
        "description": (
            "取若干候选标的的完整画像（业务、财务、交易条件、风险等分栏正文）。"
            "只对准备写进推荐结果的少数几家调用，不要对全部候选调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"标的 id，来自 search_targets 的返回。全程累计上限 {MAX_DETAIL_TARGETS_TOTAL} 个。",
                }
            },
            "required": ["target_ids"],
        },
    },
}

ASK_USER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "向用户澄清。**默认不要用**：条件不全时先按现有条件给结果，在结尾提示可以补充什么。"
            "只有当条件空到无法有效收敛（例如行业、地区、规模全缺，命中数以千计）时才调用。"
            "调用后本轮结束，等用户回答。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "maxItems": MAX_ASK_USER_QUESTIONS,
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "一句话问题。"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "可点选项，2-5 个。必须给，用户不想打字。",
                            },
                        },
                        "required": ["question", "options"],
                    },
                },
                "reason": {"type": "string", "description": "为什么非问不可，一句话，会展示给用户。"},
            },
            "required": ["questions"],
        },
    },
}

RECOMMENDATION_AGENT_TOOLS: list[dict[str, Any]] = [
    SEARCH_TARGETS_TOOL,
    GET_TARGET_DETAIL_TOOL,
    ASK_USER_TOOL,
]


def anchor_from_filters(filters: Any) -> dict[str, Any]:
    """Turn the agent's filter arguments into a scoring anchor.

    The anchor deliberately has no id: that is what stops a tool-driven search
    from ever being mistaken for a persisted buyer intent, and it also makes
    `_effective_scenarios` fall back to the single implicit scenario.
    """
    anchor: dict[str, Any] = {
        "id": None,
        "buyer_party_id": None,
        "buyer_name": None,
        "intent_name": "本次需求",
        "industries_json": [],
        "excluded_industries_json": [],
    }
    if not isinstance(filters, dict):
        return anchor
    for field, raw in filters.items():
        if field not in _FILTER_PROPERTIES:
            continue
        value = coerce_condition_value(field, raw)
        if value is None:
            continue
        anchor[field] = value
    return anchor


def _candidate_digest(candidate: dict[str, Any]) -> dict[str, Any]:
    """One candidate, small enough that 30 of them still fit in a tool result."""
    facts = candidate.get("facts") or {}
    evidence = candidate.get("evidence_json") or {}
    digest: dict[str, Any] = {
        "id": str(candidate.get("seller_target_id") or ""),
        "name": candidate.get("seller_target_name"),
        "level": candidate.get("recommendation_level"),
    }
    for key in ("industry", "region", "net_profit_text", "revenue_text", "valuation_text",
                "asking_price_text", "pe_ratio", "can_control", "can_consolidate", "listed_status"):
        if facts.get(key) is not None:
            digest[key] = facts[key]
    matches = [str(item) for item in (evidence.get("matches") or [])][:6]
    gaps = [str(item) for item in (evidence.get("gaps") or [])][:4]
    unknown = [str(item) for item in (candidate.get("missing_dimensions") or [])][:5]
    if matches:
        digest["matches"] = matches
    if gaps:
        digest["gaps"] = gaps
    if unknown:
        digest["unknown"] = unknown
    if candidate.get("relation_status"):
        digest["already_in_progress"] = candidate["relation_status"]
    if candidate.get("seller_target_has_other_deep_progress"):
        digest["other_buyer_in_deep_progress"] = True
    return digest


class RecommendationAgentTools:
    """Stateful tool executor: enforces budgets and records what happened.

    The recorded calls are not debug output — the UI replays them as the
    "已筛选 2 次" process line, which is how the user finds out that the agent
    loosened a condition on its own.
    """

    def __init__(
        self,
        db: Session,
        *,
        search_targets_fn: Any,
        target_facts_fn: Any,
        step_sink: Any = None,
    ) -> None:
        self._db = db
        # 注入而不是直接 import，避免 recommendation_flow <-> 本模块的循环依赖。
        self._search_targets_fn = search_targets_fn
        self._target_facts_fn = target_facts_fn
        # 每记录一步就回调一次。handler 用它把过程写进消息表并提交，
        # 前端轮询才能在 agent 还在跑的时候看到「已筛选 2 次」。
        self._step_sink = step_sink
        self.search_calls: list[dict[str, Any]] = []
        self.detail_target_ids: list[str] = []
        self.ask_user_payload: dict[str, Any] | None = None
        self.last_candidates: list[dict[str, Any]] = []
        self.candidates_by_id: dict[str, dict[str, Any]] = {}

    def _emit_step(self, step: dict[str, Any]) -> None:
        if self._step_sink is None:
            return
        try:
            self._step_sink(step)
        except Exception:  # noqa: BLE001 - 进度回显失败不该拖垮整次推荐
            pass

    # -- dispatch ---------------------------------------------------------
    def execute(self, call: ToolCall) -> Any:
        if call.name == "search_targets":
            return self._search_targets(call.arguments)
        if call.name == "get_target_detail":
            return self._get_target_detail(call.arguments)
        if call.name == "ask_user":
            return self._ask_user(call.arguments)
        return {"error": f"unknown tool: {call.name}"}

    @property
    def should_stop(self) -> bool:
        """ask_user ends the turn — there is nothing to do until the user replies."""
        return self.ask_user_payload is not None

    # -- tools ------------------------------------------------------------
    def _search_targets(self, arguments: dict[str, Any]) -> Any:
        if len(self.search_calls) >= MAX_SEARCH_CALLS:
            return {
                "error": f"已达到本次会话的筛选次数上限（{MAX_SEARCH_CALLS} 次）。"
                         "请基于已有结果给出推荐，不要再调用 search_targets。"
            }
        raw_limit = arguments.get("limit")
        try:
            limit = int(raw_limit) if raw_limit is not None else DEFAULT_SEARCH_RESULTS_PER_CALL
        except (TypeError, ValueError):
            limit = DEFAULT_SEARCH_RESULTS_PER_CALL
        limit = max(1, min(limit, MAX_SEARCH_RESULTS_PER_CALL))
        count_only = bool(arguments.get("count_only"))
        filters = arguments.get("filters")
        anchor = anchor_from_filters(filters)

        result = self._search_targets_fn(self._db, anchor, limit)
        candidates = result.get("candidates") or []
        funnel = result.get("funnel") or {}

        applied = {key: value for key, value in anchor.items()
                   if key not in {"id", "buyer_party_id", "buyer_name", "intent_name"} and value not in (None, [], "")}
        record = {
            "call_index": len(self.search_calls) + 1,
            "note": str(arguments.get("note") or "").strip() or None,
            "filters": applied,
            "count_only": count_only,
            "eligible_count": funnel.get("eligible_count"),
            "scan_count": funnel.get("scan_count"),
            "conflict_count": funnel.get("conflict_count"),
            "returned_count": 0 if count_only else len(candidates),
        }
        self.search_calls.append(record)
        self._emit_step({"kind": "search", **record})

        if count_only:
            return {
                "matched_count": funnel.get("eligible_count"),
                "scanned": funnel.get("scan_count"),
                "excluded_by_conflict": funnel.get("conflict_count"),
            }

        self.last_candidates = candidates
        for candidate in candidates:
            key = str(candidate.get("seller_target_id") or "")
            if key:
                self.candidates_by_id[key] = candidate
        return {
            "matched_count": funnel.get("eligible_count"),
            "scanned": funnel.get("scan_count"),
            "excluded_by_conflict": funnel.get("conflict_count"),
            "returned": [_candidate_digest(item) for item in candidates],
        }

    def _get_target_detail(self, arguments: dict[str, Any]) -> Any:
        raw_ids = arguments.get("target_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            return {"error": "target_ids 必须是非空数组。"}
        remaining = MAX_DETAIL_TARGETS_TOTAL - len(self.detail_target_ids)
        if remaining <= 0:
            return {
                "error": f"已达到详情读取上限（累计 {MAX_DETAIL_TARGETS_TOTAL} 个）。"
                         "请基于已有信息给出推荐。"
            }
        wanted: list[str] = []
        for value in raw_ids:
            key = str(value or "").strip()
            if key and key not in self.detail_target_ids and key not in wanted:
                wanted.append(key)
        truncated = len(wanted) > remaining
        wanted = wanted[:remaining]
        if not wanted:
            return {"error": "target_ids 里没有新的标的（可能已经取过）。"}
        self.detail_target_ids.extend(wanted)
        self._emit_step({"kind": "detail", "count": len(wanted), "total": len(self.detail_target_ids)})

        rows = self._db.execute(
            text(
                """
                select
                  st.id, st.target_name, st.business_summary, st.transaction_summary,
                  st.risk_summary, st.gap_summary, st.industry_l1, st.industry_l2,
                  st.location_province, st.location_city, st.location_district,
                  st.current_revenue_yuan, st.current_net_profit_yuan, st.pe_ratio,
                  st.valuation_yuan, st.asking_price_yuan, st.current_debt_ratio,
                  st.can_control, st.can_consolidate, st.transfer_ratio_min, st.transfer_ratio_max,
                  st.listed_status, st.cash_flow_status, st.profitability_status,
                  st.management_retention_possible
                from seller_target st
                where st.team_id = :team_id
                  and st.workspace_id = :workspace_id
                  and st.deleted_at is null
                  -- 与 recommendation_flow 是两条独立召回路径，闸门口径必须一致。
                  and st.target_grade <> 'E'
                  and st.id = any(:ids)
                """
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "ids": wanted,
            },
        ).mappings().all()

        sections = load_profile_sections(
            self._db, entity_type="seller_target", entity_ids=[row["id"] for row in rows]
        )
        # 按 id 直接取到的标的也要登记成候选。跟进问题（「第二个再详细点」）拿的是
        # 上一轮正文里的 id，不登记的话最终那道 join 会把它当成模型编的 id 丢掉，
        # 用户得到的是一片空白。事实仍然来自代码，红线不变。
        unseen = [str(row["id"]) for row in rows if str(row["id"]) not in self.candidates_by_id]
        deep_progress_ids = self._targets_in_deep_progress(unseen) if unseen else set()

        details = []
        for row in rows:
            key = str(row["id"])
            candidate = self.candidates_by_id.get(key)
            if candidate is None:
                candidate = {
                    "seller_target_id": key,
                    "seller_target_name": row["target_name"],
                    "facts": self._target_facts_fn(dict(row)),
                    "relation_status": None,
                    "seller_target_has_other_deep_progress": key in deep_progress_ids,
                }
                self.candidates_by_id[key] = candidate
            details.append(
                {
                    "id": key,
                    "name": row["target_name"],
                    "facts": candidate.get("facts") or {},
                    "business_summary": row["business_summary"],
                    "transaction_summary": row["transaction_summary"],
                    "risk_summary": row["risk_summary"],
                    "gap_summary": row["gap_summary"],
                    "profile": render_profile_text(sections.get(key), entity_type="seller_target"),
                }
            )
        payload: dict[str, Any] = {"details": details}
        if truncated:
            payload["note"] = f"超出上限的 id 未读取，累计上限 {MAX_DETAIL_TARGETS_TOTAL} 个。"
        return payload

    def _targets_in_deep_progress(self, target_ids: list[str]) -> set[str]:
        """Which of these are already in due diligence / agreement with someone.

        An agent session has no buyer intent of its own, so the seller-side
        warning is the only conflict signal that means anything here — and it is
        exactly the one a client manager must not be allowed to miss.
        """
        rows = self._db.execute(
            text(
                """
                select distinct seller_target_id::text as seller_target_id
                from buyer_seller_relation
                where team_id = :team_id and workspace_id = :workspace_id
                  and deleted_at is null
                  and seller_target_id in :target_ids
                  and status in :deep_statuses
                """
            ).bindparams(
                bindparam("target_ids", expanding=True),
                bindparam("deep_statuses", expanding=True),
            ),
            {
                "team_id": DEFAULT_TEAM_ID,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "target_ids": target_ids,
                "deep_statuses": list(DEEP_PROGRESS_STATUSES),
            },
        ).mappings().all()
        return {row["seller_target_id"] for row in rows}

    def _ask_user(self, arguments: dict[str, Any]) -> Any:
        if self.ask_user_payload is not None:
            return {"error": "本轮已经问过一次，不能再问。请基于现有条件给出结果。"}
        raw_questions = arguments.get("questions")
        if not isinstance(raw_questions, list) or not raw_questions:
            return {"error": "questions 必须是非空数组。"}
        questions = []
        for item in raw_questions[:MAX_ASK_USER_QUESTIONS]:
            if not isinstance(item, dict):
                continue
            question = str(item.get("question") or "").strip()
            if not question:
                continue
            options = [
                str(option).strip()
                for option in (item.get("options") or [])
                if str(option or "").strip()
            ][:5]
            questions.append({"question": question, "options": options})
        if not questions:
            return {"error": "没有解析出有效问题。"}
        self.ask_user_payload = {
            "questions": questions,
            "reason": str(arguments.get("reason") or "").strip() or None,
        }
        return {"status": "asked", "note": "问题已发给用户，本轮到此结束。"}

    # -- for the writer ---------------------------------------------------
    def process_steps(self) -> list[dict[str, Any]]:
        """The process line the UI shows. Same data the agent actually acted on."""
        return list(self.search_calls)

    def as_trace_payload(self) -> dict[str, Any]:
        return {
            "search_calls": self.search_calls,
            "detail_target_ids": self.detail_target_ids,
            "asked_user": self.ask_user_payload is not None,
        }


def tool_result_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
