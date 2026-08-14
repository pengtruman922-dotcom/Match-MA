"""级别与它的「E 细分原因」这一对列的唯一派生点。

0814 起标的与买家需求都由级别 A-E 表达是否参与推荐：E 不进推荐，A-D 进。
原来的 `seller_target.lifecycle_status` / `buyer_intent.status` 不删，降级成
E 的细分原因（已售出/已停售、暂停推荐/结束推荐），因此两列严格双向绑定：

    grade ∈ {A,B,C,D}  ⟺  reason = active
    grade = 'E'        ⟺  reason ≠ active

不变式同时落在数据库（`chk_*_grade_*`）。约束是兜底，这里是唯一允许决定这一对
取值的地方 —— 任何写入方都不许自己拼组合，否则就会重演 recommendation_status
那次事故：一列（这里是一对列）只有一条窄路径正确置位，其余路径静默漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

GRADES: frozenset[str] = frozenset({"A", "B", "C", "D", "E"})
BLOCKED_GRADE = "E"
# 新录入的实体没有明确级别时的级别。**只在实体创建这一个点生效**：解析路径
# 一律不许拿它做兜底，否则重新解析会把顾问设成 D 的标的打回 C。
DEFAULT_GRADE = "C"


@dataclass(frozen=True)
class GradeSpec:
    grade_column: str
    reason_column: str
    active_reason: str
    # 只给了裸 E、没说为什么时用的原因。取弱的一侧：模型说「已售出」会被中文词
    # 映射直接接住，只有材料说「不再推荐」但没说原因时才会走到这里，默认成
    # 「已成交」等于凭空声称一笔交易。
    default_blocked_reason: str
    blocked_reasons: frozenset[str]


SELLER_GRADE = GradeSpec(
    grade_column="target_grade",
    reason_column="lifecycle_status",
    active_reason="active",
    default_blocked_reason="off_market",
    blocked_reasons=frozenset({"sold", "off_market"}),
)

BUYER_GRADE = GradeSpec(
    grade_column="intent_grade",
    reason_column="status",
    active_reason="active",
    default_blocked_reason="paused",
    blocked_reasons=frozenset({"paused", "closed"}),
)


# 运行时提示词可编辑，模型给中文还是给枚举码都得接住。这份表是 lifecycle_status
# 的唯一中文映射，`_normalize_field_value` 与 `_lifecycle_status_from_changes`
# 共用 —— 通用的 ENUM_VALUE_ALIASES 装不下它，因为「已成交」在关系状态里是
# deal_closed、在标的这里是 sold，同一个词在两张表里含义不同。
LIFECYCLE_STATUS_ALIASES: dict[str, str] = {
    "sold": "sold",
    "已售出": "sold",
    "已成交": "sold",
    "off_market": "off_market",
    "已停售": "off_market",
    "停售": "off_market",
    "暂停出售": "off_market",
    "不再出售": "off_market",
    "no": "off_market",
    "active": "active",
    "在售": "active",
}


def normalize_grade(value: Any) -> str | None:
    """A-E 之外一律返回 None。字母大小写不敏感，其余不做猜测。"""
    if not isinstance(value, str):
        return None
    grade = value.strip().upper()
    return grade if grade in GRADES else None


def normalize_lifecycle_status(value: Any) -> str | None:
    if value is None:
        return None
    return LIFECYCLE_STATUS_ALIASES.get(str(value).strip().lower())


def resolve_grade_pair(
    spec: GradeSpec,
    changes: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    allow_reactivation: bool,
) -> dict[str, str]:
    """把一批变更里的级别列与原因列收敛成自洽的一对。

    返回要写的两列；两列都没被提议时返回空字典 —— **「没解析出级别就不改」正是
    靠这个空字典成立的**，调用方不要再加任何默认值兜底。

    ``allow_reactivation`` 是「AI 只能进 E、不能出 E」这条既有不变式的开关：人工
    改级别传 True，解析与业务更新传 False。原本的措辞在 extracted_action_apply
    里是 "A later in-sale signal never reactivates a sold or off-market target
    automatically."，语义原样保留 —— 顺带也回答了「E 之前是 A 级、恢复时记不记得」：
    不记得，出 E 只能由人显式选一个 A-D。
    """
    has_grade = spec.grade_column in changes
    has_reason = spec.reason_column in changes
    if not has_grade and not has_reason:
        return {}

    proposed_grade = normalize_grade(changes.get(spec.grade_column)) if has_grade else None
    proposed_reason = changes.get(spec.reason_column) if has_reason else None
    if isinstance(proposed_reason, str):
        proposed_reason = proposed_reason.strip()
    known_reason = (
        proposed_reason
        if proposed_reason == spec.active_reason or proposed_reason in spec.blocked_reasons
        else None
    )
    if proposed_grade is None and known_reason is None:
        # 两列都给了非法值：交给调用方各自的 rejected_fields 约定去记录，这里
        # 只负责不写。
        return {}

    current_grade = normalize_grade(current.get(spec.grade_column)) or DEFAULT_GRADE

    # 级别优先于原因：两个都给了且互相矛盾时以级别为准，原因按级别重算。原因列
    # 是级别的注解，反过来让注解推翻结论会让「顾问把 E 改回 B」被一句陈旧的
    # 「已停售」悄悄吃掉。
    if proposed_grade is not None:
        grade = proposed_grade
    elif known_reason in spec.blocked_reasons:
        grade = BLOCKED_GRADE
    else:
        grade = current_grade if current_grade != BLOCKED_GRADE else DEFAULT_GRADE

    if current_grade == BLOCKED_GRADE and grade != BLOCKED_GRADE and not allow_reactivation:
        return {}

    if grade == BLOCKED_GRADE:
        if known_reason in spec.blocked_reasons:
            reason = known_reason
        elif current.get(spec.reason_column) in spec.blocked_reasons:
            reason = str(current[spec.reason_column])
        else:
            reason = spec.default_blocked_reason
    else:
        reason = spec.active_reason

    return {spec.grade_column: grade, spec.reason_column: reason}
