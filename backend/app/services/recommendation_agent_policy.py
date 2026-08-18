"""Hard policy for recommendation-agent screening and candidate pooling.

The main agent may choose *when* to relax a condition, but it cannot invent a
condition, mix two demand groups, relax in the wrong numeric direction, or
drop an exclusion.  Those rules live here as pure functions so the stateful
tool executor only has to record calls and run SQL.

This module is deliberately a leaf: it depends on the parsed intent snapshot
and ``screening_schema`` only.  It never imports a job handler or the agent
tool executor.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from backend.app.services.screening_schema import SCREENING_FIELDS_BY_COLUMN


DEEP_EVAL_POOL_LIMIT = 40

# A required condition is normally retained.  At five or fewer real matches
# there may not be enough material for a 3-6 item recommendation, so the agent
# may relax it *if* it cites that real call.  The agent still decides whether
# the trade-off is sensible; code only verifies that the decision has a real,
# low-recall basis.
REQUIRED_RELAXATION_MAX_MATCHES = 5

ENFORCED_EXCLUSION_COLUMNS = (
    "excluded_industries_json",
    "unacceptable_risk_flags_json",
)


@dataclass(frozen=True)
class CompiledGroup:
    group_id: str
    label: str
    baseline_conditions: dict[str, Any]
    strength: dict[str, str]
    exclusion_conditions: dict[str, Any]
    fallback: bool = False

    @property
    def full_conditions(self) -> dict[str, Any]:
        return {**deepcopy(self.baseline_conditions), **deepcopy(self.exclusion_conditions)}

    def as_context_dict(self) -> dict[str, Any]:
        """The serialisable group catalog shown to the main agent."""
        return {
            "group_id": self.group_id,
            "label": self.label,
            "conditions": deepcopy(self.baseline_conditions),
            "strength": deepcopy(self.strength),
            "enforced_exclusions": deepcopy(self.exclusion_conditions),
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class ValidatedSearchPlan:
    valid: bool
    group_id: str
    conditions: dict[str, Any]
    full_conditions: bool
    relaxed_fields: tuple[str, ...]
    relaxation_reason: str | None
    based_on_call_index: int | None
    injected_exclusion_fields: tuple[str, ...] = ()
    error_code: str | None = None
    error: str | None = None

    def error_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.error_code or "invalid_search_call",
                "message": self.error or "筛选调用不符合当前需求快照。",
                "group_id": self.group_id or None,
            }
        }


@dataclass(frozen=True)
class CandidatePool:
    candidate_ids: tuple[str, ...]
    candidate_sources: dict[str, dict[str, Any]]
    raw_occurrences: int
    unique_before_cap: int
    unique_after_cap: int
    capped: bool
    limit: int

    def source_for(self, candidate_id: str) -> dict[str, Any]:
        return deepcopy(self.candidate_sources.get(candidate_id) or {})

    def selected_sources(self) -> dict[str, dict[str, Any]]:
        return {candidate_id: self.source_for(candidate_id) for candidate_id in self.candidate_ids}

    def stats(self) -> dict[str, Any]:
        return {
            "raw_occurrences": self.raw_occurrences,
            "unique_before_cap": self.unique_before_cap,
            "unique_after_cap": self.unique_after_cap,
            "capped": self.capped,
            "limit": self.limit,
        }


def compile_condition_groups(intent_snapshot: Any) -> list[CompiledGroup]:
    """Compile a safe, deterministic group catalog from the parser snapshot.

    Group ids are code-owned (``group-1`` ...); the parser and the main agent
    cannot pick identities that collide.  A degraded/empty snapshot gets one
    ``fallback-0`` group whose baseline is empty.  Global exclusions are
    compiled separately and injected into every SQL call, including fallback.
    """
    snapshot = intent_snapshot if isinstance(intent_snapshot, dict) else {}
    exclusions = _compile_exclusions(snapshot.get("exclusions"))
    raw_groups = snapshot.get("condition_groups")
    if not isinstance(raw_groups, list):
        raw_groups = []

    compiled: list[CompiledGroup] = []
    for index, raw_group in enumerate(raw_groups, start=1):
        if not isinstance(raw_group, dict):
            continue
        raw_conditions = raw_group.get("conditions")
        if not isinstance(raw_conditions, dict):
            continue
        conditions = {
            str(column): deepcopy(value)
            for column, value in raw_conditions.items()
            if str(column) in SCREENING_FIELDS_BY_COLUMN and str(column) not in ENFORCED_EXCLUSION_COLUMNS
        }
        if not conditions:
            continue
        raw_strength = raw_group.get("strength") if isinstance(raw_group.get("strength"), dict) else {}
        strength = {
            column: (
                str(raw_strength.get(column) or "").strip().lower()
                if str(raw_strength.get(column) or "").strip().lower() in {"required", "preferred"}
                else "required"
            )
            for column in conditions
        }
        compiled.append(
            CompiledGroup(
                group_id=f"group-{len(compiled) + 1}",
                label=str(raw_group.get("label") or "").strip() or f"方案{index}",
                baseline_conditions=conditions,
                strength=strength,
                exclusion_conditions=deepcopy(exclusions),
            )
        )

    if compiled:
        return compiled
    return [
        CompiledGroup(
            group_id="fallback-0",
            label="无结构化条件",
            baseline_conditions={},
            strength={},
            exclusion_conditions=deepcopy(exclusions),
            fallback=True,
        )
    ]


def validate_search_call(
    group_id: Any,
    conditions: Any,
    prior_calls: list[dict[str, Any]],
    *,
    groups: list[CompiledGroup],
    count_only: bool,
    relaxation_reason: Any = None,
    based_on_call_index: Any = None,
) -> ValidatedSearchPlan:
    """Validate one proposed search without touching SQL or mutable state."""
    key = str(group_id or "").strip()
    by_id = {group.group_id: group for group in groups}
    group = by_id.get(key)
    if group is None:
        return _invalid(key, "unknown_group", "group_id 不在本轮当前需求快照中。")
    if not isinstance(conditions, dict):
        return _invalid(key, "conditions_not_object", "conditions 必须是对象。")

    proposed = {str(column): deepcopy(value) for column, value in conditions.items()}
    allowed = set(group.baseline_conditions) | set(group.exclusion_conditions)
    outside = sorted(set(proposed) - allowed)
    if outside:
        return _invalid(
            key,
            "field_outside_group",
            f"这些字段不属于 {key}，不能跨组拼接或新增：{outside}",
        )

    injected: list[str] = []
    for column, value in group.exclusion_conditions.items():
        if column in proposed and not _same_value(proposed[column], value):
            return _invalid(
                key,
                "exclusion_modified",
                f"排除项 {column} 由代码强制执行，不能删除、缩小或改值。",
            )
        if column not in proposed:
            injected.append(column)
        proposed[column] = deepcopy(value)

    if group.fallback and any(column not in group.exclusion_conditions for column in proposed):
        return _invalid(key, "fallback_conditions_forbidden", "fallback 空组不能编造结构化条件。")

    relaxed: list[str] = []
    for column, baseline in group.baseline_conditions.items():
        if column not in proposed:
            relaxed.append(column)
            continue
        current = proposed[column]
        if _same_value(current, baseline):
            continue
        field = SCREENING_FIELDS_BY_COLUMN[column]
        if field.value_type != "number":
            return _invalid(
                key,
                "condition_value_changed",
                f"{column} 只能保留原值或整项移除，不能换成快照外的新值。",
            )
        try:
            before = float(baseline)
            after = float(current)
        except (TypeError, ValueError):
            return _invalid(key, "invalid_numeric_relaxation", f"{column} 的数值无法比较。")
        if field.operator == "gte" and after > before:
            return _invalid(
                key,
                "wrong_relaxation_direction",
                f"{column} 是下限，放宽只能降低，不能从 {before:g} 提高到 {after:g}。",
            )
        if field.operator == "lte" and after < before:
            return _invalid(
                key,
                "wrong_relaxation_direction",
                f"{column} 是上限，放宽只能提高，不能从 {before:g} 降低到 {after:g}。",
            )
        if field.operator not in {"gte", "lte"}:
            return _invalid(
                key,
                "condition_value_changed",
                f"{column} 不是可单向放宽的数值门槛，只能保留或整项移除。",
            )
        relaxed.append(column)

    # The first *real* batch for every group must exercise the complete
    # baseline. count_only probes do not satisfy this invariant.
    prior_real = [
        call
        for call in prior_calls
        if call.get("valid") is not False
        and not call.get("count_only")
        and call.get("group_id") == key
        and call.get("eligible_count") is not None
    ]
    if not count_only and not prior_real and relaxed:
        return _invalid(
            key,
            "first_real_search_must_be_full",
            "每组第一次非 count_only 真实查询必须使用完整基线条件。",
        )

    reason = str(relaxation_reason or "").strip() or None
    basis_index = _optional_positive_int(based_on_call_index)
    if relaxed:
        if not reason or basis_index is None:
            return _invalid(
                key,
                "relaxation_basis_required",
                "放宽必须同时提供 relaxation_reason 和 based_on_call_index。",
            )
        basis = next(
            (
                call
                for call in prior_real
                if _optional_positive_int(call.get("call_index")) == basis_index
            ),
            None,
        )
        if basis is None:
            return _invalid(
                key,
                "invalid_relaxation_basis",
                "based_on_call_index 必须指向同组此前一次有效的非 count_only 真实查询。",
            )
        basis_conditions = basis.get("filters") if isinstance(basis.get("filters"), dict) else {}
        for column in relaxed:
            if column not in basis_conditions:
                return _invalid(
                    key,
                    "relaxation_field_not_tested",
                    f"依据调用 {basis_index} 没有实际筛过 {column}，不能拿它作为放宽依据。",
                )
            if group.strength.get(column, "required") != "required":
                continue
            matched = _optional_nonnegative_int(basis.get("eligible_count"))
            if matched is None or matched > REQUIRED_RELAXATION_MAX_MATCHES:
                return _invalid(
                    key,
                    "required_relaxation_without_low_recall",
                    f"required 条件 {column} 只有在此前真实召回不超过 "
                    f"{REQUIRED_RELAXATION_MAX_MATCHES} 家时才可放宽；依据调用召回={matched}。",
                )

    return ValidatedSearchPlan(
        valid=True,
        group_id=key,
        conditions=proposed,
        full_conditions=not relaxed,
        relaxed_fields=tuple(relaxed),
        relaxation_reason=reason if relaxed else None,
        based_on_call_index=basis_index if relaxed else None,
        injected_exclusion_fields=tuple(injected),
    )


def build_deep_eval_pool(
    search_batches: list[dict[str, Any]],
    *,
    limit: int = DEEP_EVAL_POOL_LIMIT,
) -> CandidatePool:
    """Union real batches and cap them fairly only at the deep-eval boundary.

    Every batch retains its true SQL order.  If the union exceeds the cap, the
    selector alternates groups; within each group it alternates that group's
    batches in call order.  No SQL query excludes ids from an earlier batch.
    """
    safe_limit = max(0, int(limit))
    real_batches = [
        batch
        for batch in search_batches
        if batch.get("valid") is not False and not batch.get("count_only")
    ]

    sources: dict[str, dict[str, Any]] = {}
    raw_occurrences = 0
    group_order: list[str] = []
    batches_by_group: dict[str, list[list[str]]] = {}
    for batch in real_batches:
        group_id = str(batch.get("group_id") or "").strip()
        if not group_id:
            continue
        raw_ids = batch.get("candidate_ids")
        if not isinstance(raw_ids, list):
            raw_ids = []
        ids: list[str] = []
        seen_in_batch: set[str] = set()
        for value in raw_ids:
            candidate_id = str(value or "").strip()
            if not candidate_id or candidate_id in seen_in_batch:
                continue
            seen_in_batch.add(candidate_id)
            ids.append(candidate_id)
        raw_occurrences += len(ids)
        if group_id not in batches_by_group:
            group_order.append(group_id)
            batches_by_group[group_id] = []
        batches_by_group[group_id].append(ids)

        call_index = _optional_positive_int(batch.get("call_index"))
        hit = {
            "call_index": call_index,
            "group_id": group_id,
            "full_conditions": bool(batch.get("full_conditions")),
            "applied_conditions": deepcopy(batch.get("filters") or {}),
            "relaxed_fields": list(batch.get("relaxed_fields") or []),
            "relaxation_reason": batch.get("relaxation_reason") or None,
            "based_on_call_index": batch.get("based_on_call_index"),
        }
        for candidate_id in ids:
            source = sources.setdefault(
                candidate_id,
                {
                    "matched_group_ids": [],
                    "matched_search_call_ids": [],
                    "screening_hits": [],
                },
            )
            if group_id not in source["matched_group_ids"]:
                source["matched_group_ids"].append(group_id)
            if call_index is not None and call_index not in source["matched_search_call_ids"]:
                source["matched_search_call_ids"].append(call_index)
            source["screening_hits"].append(deepcopy(hit))

    for source in sources.values():
        source["group_hit_count"] = len(source["matched_group_ids"])
        source["search_hit_count"] = len(source["matched_search_call_ids"])

    unique_ids = list(sources)
    if len(unique_ids) <= safe_limit:
        selected = unique_ids
    else:
        selected = _fair_candidate_ids(
            group_order=group_order,
            batches_by_group=batches_by_group,
            limit=safe_limit,
        )

    return CandidatePool(
        candidate_ids=tuple(selected),
        candidate_sources=sources,
        raw_occurrences=raw_occurrences,
        unique_before_cap=len(unique_ids),
        unique_after_cap=len(selected),
        capped=len(unique_ids) > len(selected),
        limit=safe_limit,
    )


def _compile_exclusions(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    compiled: dict[str, Any] = {}
    industries = _unique_strings(data.get("industries"))
    risks = _unique_strings(data.get("risk_flags"))
    if industries:
        compiled["excluded_industries_json"] = industries
    if risks:
        compiled["unacceptable_risk_flags_json"] = risks
    return compiled


def _unique_strings(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else ([raw] if raw not in (None, "") else [])
    result: list[str] = []
    for value in values:
        text_value = str(value or "").strip()
        if text_value and text_value not in result:
            result.append(text_value)
    return result


def _invalid(group_id: str, code: str, message: str) -> ValidatedSearchPlan:
    return ValidatedSearchPlan(
        valid=False,
        group_id=group_id,
        conditions={},
        full_conditions=False,
        relaxed_fields=(),
        relaxation_reason=None,
        based_on_call_index=None,
        error_code=code,
        error=message,
    )


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        if isinstance(right, (int, float)) and not isinstance(right, bool):
            return float(left) == float(right)
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(_same_value(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        # All list-shaped screening conditions are OR sets (industry, enum,
        # region alternatives). Reordering the same values is not a change.
        unmatched = list(right)
        for value in left:
            match = next((index for index, other in enumerate(unmatched) if _same_value(value, other)), None)
            if match is None:
                return False
            unmatched.pop(match)
        return not unmatched
    return left == right


def _optional_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_nonnegative_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _fair_candidate_ids(
    *,
    group_order: list[str],
    batches_by_group: dict[str, list[list[str]]],
    limit: int,
) -> list[str]:
    positions = {
        group_id: [0 for _ in batches_by_group.get(group_id, [])]
        for group_id in group_order
    }
    batch_cursors = {group_id: 0 for group_id in group_order}
    selected: list[str] = []
    selected_set: set[str] = set()

    def take_one(group_id: str) -> str | None:
        batches = batches_by_group.get(group_id) or []
        if not batches:
            return None
        # Each visit starts at the next batch. Exhausted batches and ids that
        # another group already selected are skipped deterministically.
        attempts_without_progress = 0
        while attempts_without_progress < len(batches):
            batch_index = batch_cursors[group_id] % len(batches)
            batch_cursors[group_id] = (batch_index + 1) % len(batches)
            batch = batches[batch_index]
            position = positions[group_id][batch_index]
            while position < len(batch):
                candidate_id = batch[position]
                position += 1
                positions[group_id][batch_index] = position
                if candidate_id not in selected_set:
                    return candidate_id
            attempts_without_progress += 1
        return None

    while len(selected) < limit:
        progressed = False
        for group_id in group_order:
            candidate_id = take_one(group_id)
            if candidate_id is None:
                continue
            selected.append(candidate_id)
            selected_set.add(candidate_id)
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected
