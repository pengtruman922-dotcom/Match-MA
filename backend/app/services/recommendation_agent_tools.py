"""Tools the recommendation agent drives, and the budgets that keep it honest.

The agent orchestrates; it never sees the library. 初筛是 `screening_sql` 那段
纯 SQL —— agent 只决定这次带哪些条件、读回一份极简摘要与逐条件淘汰拆分，再决定
要不要换一组条件重来。That boundary is the hard rule from `AGENTS.md`:
初筛与打分必须代码化，禁止全库打包给 LLM.

工具的 schema 从指标注册表生成（`screening_schema`），行业闭集运行时从字典注入，
所以模型填不出不存在的字段、也填不出字典外的行业名。
"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.app.ai.llm_client import ToolCall
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.services.industry_taxonomy import list_l1_terms, list_l2_terms
from backend.app.services.profile_sections import load_profile_sections, render_profile_text
from backend.app.services.recommendation_agent_policy import (
    CandidatePool,
    CompiledGroup,
    ENFORCED_EXCLUSION_COLUMNS,
    build_deep_eval_pool,
    compile_condition_groups,
    validate_search_call,
)
from backend.app.services.relation_flow import DEEP_PROGRESS_STATUSES
from backend.app.services.screening_schema import build_conditions_properties
from backend.app.services.screening_sql import (
    DEFAULT_SCREENING_LIMIT,
    MAX_SCREENING_LIMIT,
    screen_targets,
)

# 预算。超了不是抛异常终止运行，而是把「你已经用完」作为工具结果回给模型，
# 让它用手上的信息收尾 —— 跟 tool_loop 处理工具报错的策略一致。
MAX_SEARCH_CALLS = 6
MAX_SEARCH_RESULTS_PER_CALL = MAX_SCREENING_LIMIT
DEFAULT_SEARCH_RESULTS_PER_CALL = DEFAULT_SCREENING_LIMIT
MAX_DETAIL_TARGETS_TOTAL = 12
MAX_ASK_USER_CALLS = 1
MAX_ASK_USER_QUESTIONS = 3

# 每次调用都必须带上的粘性条件：用户说不要的东西，放宽多少次都还是不要。
# 在工具层强制，不依赖模型自觉。
#
# 4B 起行业与重大风险排除都从当前需求快照编译后由代码注入。风险排除可能因
# 库内核查覆盖率低而显著缩小召回，但那是用户明确的一票否决项，不能由 Agent
# 为了凑数量静默删除。
STICKY_CONDITIONS: tuple[str, ...] = ENFORCED_EXCLUSION_COLUMNS

_SEARCH_TARGETS_DESCRIPTION = (
    "按结构化条件在标的库里硬筛，返回命中数、逐条件淘汰拆分与候选摘要。"
    "一次调用是一组 AND 条件，全部满足才算命中；**条件涉及的字段为空的标的一律出局**，"
    "所以只填用户真正表达过的条件，不要凭空补。"
    "需要「A 或 B」两套方案时，拆成两次调用，不要指望一次调用做 OR。"
    "召回不足时看 excluded_by_condition：某一条的「字段为空」占多数说明是数据没录，"
    "该去掉它；「确实不达标」占多数说明那是真门槛，应该保留。"
    "只想知道有多少家时用 count_only=true。"
)


def build_search_targets_tool(
    db: Session,
    groups: list[CompiledGroup] | None = None,
) -> dict[str, Any]:
    """初筛工具的定义。行业闭集运行时注入，模型写不出字典外的行业名。"""
    safe_groups = groups or compile_condition_groups({})
    group_ids = [group.group_id for group in safe_groups]
    return {
        "type": "function",
        "function": {
            "name": "search_targets",
            "description": _SEARCH_TARGETS_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {
                        "type": "string",
                        "enum": group_ids,
                        "description": "本次执行的条件组 id，只能从当前需求快照的条件组中选择。",
                    },
                    "conditions": {
                        "type": "object",
                        "description": "本次的一组 AND 条件。留空表示不限，会返回全库 A-D 级标的。",
                        "properties": build_conditions_properties(
                            industry_l1_terms=list_l1_terms(db),
                            industry_l2_terms=list_l2_terms(db),
                        ),
                        "additionalProperties": False,
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"返回条数，默认 {DEFAULT_SEARCH_RESULTS_PER_CALL}，上限 {MAX_SEARCH_RESULTS_PER_CALL}。",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "同一组条件下翻页，取更后面的结果。",
                    },
                    "count_only": {
                        "type": "boolean",
                        "description": "只返回命中数量与淘汰拆分，不返回候选明细。用来低成本试探条件宽窄。",
                    },
                    "note": {
                        "type": "string",
                        "description": "这次筛选想验证什么，一句话。会展示给用户看，让他知道你做了什么。",
                    },
                    "relaxation_reason": {
                        "type": "string",
                        "description": (
                            "仅放宽时必填：引用此前真实查询的召回量或 excluded_by_condition，"
                            "解释为什么放宽。"
                        ),
                    },
                    "based_on_call_index": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "仅放宽时必填：作为依据的同组此前真实查询 call_index。",
                    },
                },
                "required": ["group_id", "conditions"],
            },
        },
    }


DEEP_EVALUATE_CANDIDATES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "deep_evaluate_candidates",
        "description": (
            "冻结筛选并对全部真实初筛批次的候选并集做一次深评。"
            "候选池、当前需求快照和业务参数均由代码持有，你不传候选 id。"
            "至少形成一个非 count_only 的真实候选批次后才能调用，全程最多一次。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
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

def _int_argument(raw: Any, default: int) -> int:
    """模型给整数参数时经常写成字符串或小数，读不出来就退回默认值。"""
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def build_agent_tools(
    db: Session,
    groups: list[CompiledGroup] | None = None,
) -> list[dict[str, Any]]:
    """本轮下发给模型的工具集。search_targets 的 schema 依赖运行时的行业字典。"""
    return [
        build_search_targets_tool(db, groups),
        GET_TARGET_DETAIL_TOOL,
        DEEP_EVALUATE_CANDIDATES_TOOL,
        ASK_USER_TOOL,
    ]


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
        target_facts_fn: Any,
        step_sink: Any = None,
        screen_targets_fn: Any = screen_targets,
        intent_snapshot: dict[str, Any] | None = None,
        deep_eval_fn: Any = None,
    ) -> None:
        self._db = db
        # facts 的格式化注入而不是直接 import，避免 recommendation_flow <-> 本模块
        # 的循环依赖；初筛本身是 screening_sql 那个无依赖的叶子模块，直接调。
        self._target_facts_fn = target_facts_fn
        self._screen_targets_fn = screen_targets_fn
        # 每记录一步就回调一次。handler 用它把过程写进消息表并提交，
        # 前端轮询才能在 agent 还在跑的时候看到「已筛选 2 次」。
        self._step_sink = step_sink
        self.intent_snapshot = dict(intent_snapshot or {})
        self.compiled_groups = compile_condition_groups(self.intent_snapshot)
        self._deep_eval_fn = deep_eval_fn
        self.search_calls: list[dict[str, Any]] = []
        self.detail_target_ids: list[str] = []
        self.ask_user_payload: dict[str, Any] | None = None
        self.last_candidates: list[dict[str, Any]] = []
        self.candidates_by_id: dict[str, dict[str, Any]] = {}
        self.policy_errors: list[dict[str, Any]] = []
        self.deep_eval_called = False
        self.screening_frozen = False
        self.deep_eval_result: dict[str, Any] | None = None
        self.final_output_contract: dict[str, Any] | None = None
        self.final_output_normalization_notes: list[str] = []
        self._tool_started_at: float | None = None

    def _emit_step(self, step: dict[str, Any]) -> None:
        if self._step_sink is None:
            return
        payload = dict(step)
        payload.setdefault(
            "duration_ms",
            max(0, int((time.perf_counter() - self._tool_started_at) * 1000))
            if self._tool_started_at is not None
            else 0,
        )
        try:
            self._step_sink(payload)
        except Exception:  # noqa: BLE001 - 进度回显失败不该拖垮整次推荐
            pass

    # -- dispatch ---------------------------------------------------------
    def execute(self, call: ToolCall) -> Any:
        self._tool_started_at = time.perf_counter()
        try:
            if call.name == "search_targets":
                return self._search_targets(call.arguments)
            if call.name == "get_target_detail":
                return self._get_target_detail(call.arguments)
            if call.name == "deep_evaluate_candidates":
                return self._deep_evaluate_candidates()
            if call.name == "ask_user":
                return self._ask_user(call.arguments)
            return {"error": f"unknown tool: {call.name}"}
        finally:
            self._tool_started_at = None

    @property
    def should_stop(self) -> bool:
        """ask_user ends the turn — there is nothing to do until the user replies."""
        return self.ask_user_payload is not None

    # -- tools ------------------------------------------------------------
    def _search_targets(self, arguments: dict[str, Any]) -> Any:
        if self.screening_frozen:
            return self._policy_error(
                "screening_frozen",
                "深评已经调用，筛选阶段已冻结，不能再调用 search_targets。",
                tool_name="search_targets",
            )
        if len(self.search_calls) >= MAX_SEARCH_CALLS:
            return {
                "error": f"已达到本次会话的筛选次数上限（{MAX_SEARCH_CALLS} 次）。"
                         "请基于已有结果给出推荐，不要再调用 search_targets。"
            }
        limit = _int_argument(arguments.get("limit"), DEFAULT_SEARCH_RESULTS_PER_CALL)
        limit = max(1, min(limit, MAX_SEARCH_RESULTS_PER_CALL))
        offset = max(0, _int_argument(arguments.get("offset"), 0))
        count_only = bool(arguments.get("count_only"))
        raw_conditions = arguments.get("conditions")
        if not isinstance(raw_conditions, dict):
            raw_conditions = arguments.get("filters")
        call_index = len(self.search_calls) + 1
        plan = validate_search_call(
            arguments.get("group_id"),
            raw_conditions,
            self.search_calls,
            groups=self.compiled_groups,
            count_only=count_only,
            relaxation_reason=arguments.get("relaxation_reason"),
            based_on_call_index=arguments.get("based_on_call_index"),
        )
        if not plan.valid:
            record = {
                "call_index": call_index,
                "valid": False,
                "group_id": plan.group_id or None,
                "note": str(arguments.get("note") or "").strip() or None,
                "count_only": count_only,
                "error_code": plan.error_code,
                "error": plan.error,
            }
            self.search_calls.append(record)
            self.policy_errors.append(record)
            self._emit_step({"kind": "search_rejected", **record})
            return plan.error_payload()

        result = self._screen_targets_fn(
            self._db, plan.conditions, limit=limit, offset=offset, count_only=count_only
        )

        record = {
            "call_index": call_index,
            "valid": True,
            "group_id": plan.group_id,
            "note": str(arguments.get("note") or "").strip() or None,
            "filters": result.conditions,
            "count_only": count_only,
            "eligible_count": result.matched,
            "returned_count": result.returned_count,
            "excluded_by_condition": result.excluded_by_condition,
            "full_conditions": plan.full_conditions,
            "relaxed_fields": list(plan.relaxed_fields),
            "relaxation_reason": plan.relaxation_reason,
            "based_on_call_index": plan.based_on_call_index,
            "injected_exclusion_fields": list(plan.injected_exclusion_fields),
            "candidate_ids": [str(row.get("id")) for row in result.rows if row.get("id")],
        }
        self.search_calls.append(record)
        self._emit_step({"kind": "search", **record})

        if not count_only:
            self._register_candidates(result.rows)
        return {
            **result.as_tool_result(),
            "call_index": call_index,
            "group_id": plan.group_id,
            "full_conditions": plan.full_conditions,
            "relaxed_fields": list(plan.relaxed_fields),
        }

    def _register_candidates(self, rows: list[dict[str, Any]]) -> None:
        """登记候选，附上代码算出的 facts 与「别的买家在深入推进」警示。

        摘要给模型看，facts 给写作环节回填数字用 —— 正文里的数字永远来自这里，
        不来自模型重打的那一遍。
        """
        candidates: list[dict[str, Any]] = []
        ids = [str(row.get("id") or "") for row in rows if row.get("id")]
        deep_progress_ids = self._targets_in_deep_progress(ids) if ids else set()
        for row in rows:
            key = str(row.get("id") or "")
            if not key:
                continue
            candidate = {
                "seller_target_id": key,
                "seller_target_name": row.get("target_name"),
                "facts": self._target_facts_fn(dict(row)),
                "seller_target_has_other_deep_progress": key in deep_progress_ids,
            }
            candidates.append(candidate)
            # 已经取过详情的标的不要被摘要覆盖回去。首见为准是对的，候选内容在多次
            # 查询之间没有差异，改成后见覆盖只会让结果不可复现。命中来源由每批
            # candidate_ids 在汇总时计算，不靠覆盖候选正文。
            self.candidates_by_id.setdefault(key, candidate)
        self.last_candidates = candidates

    def _get_target_detail(self, arguments: dict[str, Any]) -> Any:
        if self.screening_frozen:
            return self._policy_error(
                "screening_frozen",
                "深评已经调用，筛选阶段已冻结，不能再调用 get_target_detail。",
                tool_name="get_target_detail",
            )
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
        self._emit_step({"kind": "detail", "count": len(wanted), "total": len(self.detail_target_ids)})
        return payload

    def candidate_pool(self) -> CandidatePool:
        """The current union. count_only and rejected calls contribute nothing."""
        return build_deep_eval_pool(self.search_calls)

    def _deep_evaluate_candidates(self) -> dict[str, Any]:
        if self.deep_eval_called:
            return self._policy_error(
                "deep_eval_already_called",
                "deep_evaluate_candidates 全程最多调用一次。",
                tool_name="deep_evaluate_candidates",
            )
        pool = self.candidate_pool()
        if not pool.candidate_ids:
            return self._policy_error(
                "deep_eval_requires_real_candidates",
                "没有非 count_only 真实候选，不能调用深评。",
                tool_name="deep_evaluate_candidates",
            )

        # Once a real pool reaches this point, success and failure have the
        # same state transition: screening is frozen and deep eval is spent.
        self.deep_eval_called = True
        self.screening_frozen = True
        candidates = {
            candidate_id: {
                **dict(self.candidates_by_id[candidate_id]),
                **pool.source_for(candidate_id),
            }
            for candidate_id in pool.candidate_ids
            if candidate_id in self.candidates_by_id
        }
        try:
            if self._deep_eval_fn is None:
                raise RuntimeError("深评执行器未配置")
            result = self._deep_eval_fn(candidates_by_id=candidates, candidate_pool=pool)
            if not isinstance(result, dict):
                raise RuntimeError("深评执行器返回的不是对象")
        except Exception as exc:  # noqa: BLE001 - controlled tool failure must freeze and return a status
            result = {
                "deep_eval_status": "unavailable",
                "ranked": [],
                "dropped": [],
                "uncovered": [],
                "fallback_reason": None,
                "notes": [f"深评执行失败：{type(exc).__name__}: {exc}"],
            }

        result = self._attach_pool_to_deep_eval(result, pool)
        self.deep_eval_result = result
        self._emit_step(
            {
                "kind": "deep_eval",
                "deep_eval_status": result.get("deep_eval_status"),
                **pool.stats(),
            }
        )
        return result

    def run_deep_eval_if_needed(self) -> dict[str, Any]:
        """Handler fallback for an agent that forgot the mandatory tool."""
        if self.deep_eval_called:
            return self.deep_eval_result or {
                "deep_eval_status": "unavailable",
                "ranked": [],
                "dropped": [],
                "uncovered": [],
                "notes": ["深评已调用但没有留下结果"],
            }
        return self._deep_evaluate_candidates()

    @staticmethod
    def _attach_pool_to_deep_eval(
        result: dict[str, Any],
        pool: CandidatePool,
    ) -> dict[str, Any]:
        enriched = dict(result)
        for bucket in ("ranked", "dropped"):
            items: list[dict[str, Any]] = []
            for raw in enriched.get(bucket) or []:
                if not isinstance(raw, dict):
                    continue
                candidate_id = str(raw.get("id") or "")
                items.append({**raw, **pool.source_for(candidate_id)})
            enriched[bucket] = items
        enriched["candidate_pool"] = pool.stats()
        # An ok result already carries sources on every ranked/dropped item;
        # duplicating all 40 candidates at the top level can double the tool
        # payload.  Degraded results have no ranked list, so they keep the
        # source map needed for SQL-order fallback.
        if enriched.get("deep_eval_status") != "ok":
            enriched["candidate_sources"] = pool.selected_sources()
        return enriched

    def _policy_error(
        self,
        code: str,
        message: str,
        *,
        tool_name: str,
    ) -> dict[str, Any]:
        record = {"tool": tool_name, "code": code, "message": message}
        self.policy_errors.append(record)
        self._emit_step({"kind": "tool_rejected", **record})
        return {"error": record}

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
        pool = self.candidate_pool()
        return {
            "search_calls": self.search_calls,
            "detail_target_ids": self.detail_target_ids,
            "candidate_pool": pool.stats(),
            "candidate_sources": pool.selected_sources(),
            "policy_errors": self.policy_errors,
            "screening_frozen": self.screening_frozen,
            "deep_eval_called": self.deep_eval_called,
            "asked_user": self.ask_user_payload is not None,
            "final_output_contract": self.final_output_contract,
            "final_output_normalization_notes": self.final_output_normalization_notes,
        }


def tool_result_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
