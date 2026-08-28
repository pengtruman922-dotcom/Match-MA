"""Per-group supplementary information that structured fields cannot express.

Three layers feed a recommendation. Canonical facts live in the entity's own
columns and tags. This module owns one “其他” supplementary block per
information group
per entity, each with its own source and as-of date — and builds the third:
the trimmed text actually sent to deep eval, budgeted per section rather than
sliced off the front of one long document.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.routes.utils import write_action_log
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID
from backend.app.registry.indicators import indicator_by_column

# 更新记录里画像字段的前缀。画像不是实体的列，靠这个前缀和普通字段区分，
# 回滚时据此走 entity_profile_section 的版本恢复而不是 update 某一列。
PROFILE_SECTION_FIELD_PREFIX = "profile_section."

# 栏目由指标对照表倒推：每一栏都有明确的买家诉求作为对手方，
# 没有对手方的维度不设栏，避免画像变成又一份越写越长的公司简介。
PROFILE_SECTIONS: tuple[tuple[str, str, int], ...] = (
    # (section_code, 中文栏目名, 送深评时的字符预算)
    ("identity", "身份与地区", 200),
    # 2026-08-07 改名：原「业务与产品」那一栏实测被写成了 business_summary 的
    # 另一种说法（23 个样本里高度重复 2 个，字面不同的抽样看也是同一件事换个
    # 说法），存量整体作废。改叫「产业优势」之后它有了明确对象 ——
    # 这家公司凭什么比同行强 —— 并接管了原「技术与团队」栏的产能、资质、
    # 技术路线与核心团队，预算按两栏之和给。
    ("business_product", "产业优势", 600),
    ("ops_quality", "经营质量", 300),
    ("deal_terms", "交易属性与出售诉求", 400),
)

# 买家侧同一个道理：每个需求模块配一块「其他」，装该模块里标准化不了、
# 也不适合拿去初筛的说法。栏目码和模块 key 对齐（registry.BUYER_GROUPS）。
BUYER_PROFILE_SECTIONS: tuple[tuple[str, str, int], ...] = (
    ("intent_scope", "行业与地区·其他", 300),
    ("intent_financial", "经营与财务·其他", 300),
    ("intent_deal", "交易与能力要求·其他", 400),
)

# 每一栏该装什么。原来五栏共用一句「只写结构化字段装不下的定性判断」，
# 于是「产业优势」这类内容随机落位 —— 实测水晶光电的产业地位描述落进了技术与团队栏。
# 这段文案同时喂给信息页的输入框和解析/调研提示词的栏目说明，是同一份真源。
PROFILE_SECTION_HINTS: dict[str, str] = {
    "identity": "主体层面的补充：曾用名、实际控制人、股权结构、注册地与办公地不一致等。",
    "business_product": (
        "这家公司凭什么比同行强：产业链位置、市场地位与排名、技术与研发能力、"
        "专利与资质、关键产能与资产、核心团队、主要客户与合作关系。"
        "不要复述业务摘要 —— 做什么生意是「业务摘要」字段的事。"
    ),
    "ops_quality": "经营质量的定性判断：增长与波动、盈利质量、客户集中度、周期性。财务数字留在字段里。",
    "deal_terms": "交易配合度与出售诉求里字段装不下的部分：卖方动机、时间要求、交割条件、已知风险的进展。",
    "intent_scope": "行业与地区上标准化不了、也不适合拿去初筛的说法。",
    "intent_financial": "经营与财务上标准化不了、也不适合拿去初筛的说法。",
    "intent_deal": "交易与能力要求上标准化不了、也不适合拿去初筛的说法。",
}

_SECTIONS_BY_ENTITY: dict[str, tuple[tuple[str, str, int], ...]] = {
    "seller_target": PROFILE_SECTIONS,
    "buyer_intent": BUYER_PROFILE_SECTIONS,
}

PROFILE_SECTION_CODES = tuple(code for code, _, _ in PROFILE_SECTIONS)
# 退役栏目码的落点。chain_position（产业链位置）在栏目改名成「产业优势」之后
# 反而名副其实了；tech_team 是 2026-08-07 并进来的。
PROFILE_SECTION_ALIASES = {
    "chain_position": "business_product",
    "tech_team": "business_product",
    "sell_intent_risk": "deal_terms",
}

# 两侧的栏目码不重叠，所以展示用的标签表可以合成一张，调用方不必先知道实体。
PROFILE_SECTION_LABELS = {
    code: label for code, label, _ in (*PROFILE_SECTIONS, *BUYER_PROFILE_SECTIONS)
}

PROFILE_SECTION_BUDGETS = {
    code: budget for code, _, budget in (*PROFILE_SECTIONS, *BUYER_PROFILE_SECTIONS)
}

PROFILE_TOTAL_BUDGET = sum(budget for _, _, budget in PROFILE_SECTIONS)


def profile_sections_for(entity_type: str) -> tuple[tuple[str, str, int], ...]:
    """某个实体有哪几块「其他」。未登记的实体没有画像栏目，不是报错。"""
    return _SECTIONS_BY_ENTITY.get(entity_type, ())


def profile_section_codes(entity_type: str) -> tuple[str, ...]:
    return tuple(code for code, _, _ in profile_sections_for(entity_type))

PROFILE_CLAUSE_SPLIT_PATTERN = re.compile(r"[，,；;。\n]+")
DEAL_TERMS_NOISE_TERMS = ("融资阶段", "融资规模", "融资金额", "估值", "营业收入", "营收", "净利润")

INFO_STATUS_LABELS = {
    "not_found": "（暂无信息）",
    "not_applicable": "（不适用）",
}


def normalize_profile_section_items(
    values: Any,
    *,
    entity_type: str = "seller_target",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate profile sections emitted by a parser or research node.

    Profile text is deliberately qualitative. Empty rows, unknown section
    codes and non-object values are dropped before they can reach the profile
    table; duplicate sections keep the first supported claim so one LLM call
    cannot overwrite itself nondeterministically.
    """
    if not isinstance(values, list):
        return [], [] if values is None else ["profile_sections:not_a_list"]
    allowed_codes = profile_section_codes(entity_type)
    normalized: list[dict[str, Any]] = []
    notes: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            notes.append(f"profile_sections[{index}]:not_an_object")
            continue
        raw_section_code = str(value.get("section_code") or "").strip()
        section_code = PROFILE_SECTION_ALIASES.get(raw_section_code, raw_section_code)
        if section_code not in allowed_codes:
            notes.append(f"profile_sections[{index}]:unknown_section:{section_code[:50]}")
            continue
        if section_code in seen:
            notes.append(f"profile_sections[{index}]:duplicate_section:{section_code}")
            continue
        content_text = str(value.get("content_text") or "").strip()
        if not content_text:
            notes.append(f"profile_sections[{index}]:empty_content:{section_code}")
            continue
        cleaned_content = _clean_profile_content(section_code, content_text)
        if cleaned_content != content_text:
            notes.append(f"profile_sections[{index}]:removed_cross_layer_noise:{section_code}")
        if not cleaned_content:
            notes.append(f"profile_sections[{index}]:empty_after_cleaning:{section_code}")
            continue
        raw_as_of_date = str(value.get("as_of_date") or "").strip()[:10]
        as_of_date = None
        if raw_as_of_date:
            try:
                as_of_date = date.fromisoformat(raw_as_of_date).isoformat()
            except ValueError:
                notes.append(
                    f"profile_sections[{index}]:invalid_as_of_date:{raw_as_of_date}"
                )
        normalized.append(
            {
                "section_code": section_code,
                "content_text": cleaned_content[:2000],
                "source_excerpt": str(value.get("source_excerpt") or "").strip()[:2000] or None,
                "as_of_date": as_of_date,
            }
        )
        seen.add(section_code)
    return normalized, notes


def _clean_profile_content(section_code: str, content_text: str) -> str:
    """Keep profile sections qualitative and dimension-specific.

    The model occasionally repeats financing/valuation facts in deal_terms or
    treats financial investors as members of the operating team. Those facts
    remain in the canonical/document layer and should not pollute semantic
    matching dimensions.

    团队那条规则随栏目合并搬到了 business_product：财务股东不是管理或研发团队，
    这一点在「产业优势」这个语义下同样成立 —— 一家公司的优势不是它的出资人名单。
    """
    if section_code not in {"deal_terms", "business_product"}:
        return content_text
    kept: list[str] = []
    for clause in PROFILE_CLAUSE_SPLIT_PATTERN.split(content_text):
        clause = clause.strip()
        if not clause:
            continue
        if section_code == "deal_terms" and any(term in clause for term in DEAL_TERMS_NOISE_TERMS):
            continue
        if section_code == "business_product" and "股东" in clause and not any(
            term in clause for term in ("团队", "创始人", "高管", "管理层")
        ):
            continue
        kept.append(clause)
    return "；".join(kept)


def load_profile_sections(
    db: Session,
    *,
    entity_type: str,
    entity_ids: list[Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Load the current section per entity, keyed by entity id then section.

    Accepting supersedes, so one accepted row per section is the normal state.
    The ordering is a safety net for rows that predate that rule, and it sorts
    by when the revision was accepted rather than by as_of_date — a researched
    date is often the page's publication date rather than the fact's, and it
    must not decide which revision the consultant sees.

    Dates come back as text on purpose: callers hand these rows straight to
    JSONB binds (research proposals, ai_trace payloads) and a raw date object
    aborts the whole job there. The order by is table-qualified for the same
    reason — a bare name would bind to the ::text output alias and silently
    turn the sort into a lexicographic one.
    """
    if not entity_ids:
        return {}
    rows = db.execute(
        text(
            """
            select
              entity_id, section_code, info_status, content_text,
              source_type, source_url,
              as_of_date::text as as_of_date,
              updated_at::text as updated_at
            from entity_profile_section
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = any(:entity_ids)
              and deleted_at is null
              and review_status in ('accepted', 'auto_accepted')
            order by entity_id, section_code, entity_profile_section.updated_at desc
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_ids": [str(value) for value in entity_ids],
        },
    ).mappings().all()

    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        entity_key = str(row["entity_id"])
        sections = grouped.setdefault(entity_key, {})
        # 已排序，同一栏目的第一行就是当前值
        sections.setdefault(row["section_code"], dict(row))
    return grouped


def render_profile_text(
    sections: dict[str, dict[str, Any]] | None,
    *,
    entity_type: str = "seller_target",
) -> str:
    """Compose the deep-eval profile with a budget per section.

    Cutting one long document at a fixed offset drops whichever sections happen
    to be last; budgeting per section keeps every dimension represented even
    when one of them is verbose.
    """
    if not sections:
        return ""
    parts: list[str] = []
    for code, label, budget in profile_sections_for(entity_type):
        row = sections.get(code)
        if not row:
            continue
        status = str(row.get("info_status") or "filled")
        if status != "filled":
            parts.append(f"【{label}】{INFO_STATUS_LABELS.get(status, '（暂无信息）')}")
            continue
        content = str(row.get("content_text") or "").strip()
        if not content:
            continue
        trimmed = content[:budget]
        if len(content) > budget:
            trimmed += "…"
        parts.append(f"【{label}】{trimmed}")
    return "\n".join(parts)


# 买家列表那盏「就绪」灯认哪些字段。
#
# 它问的**不是**「块里有没有字」，而是「够不够判断」—— 这两个问题不一样。早期把它们
# 混成一个，结果是生产里 32 条亮灯中 19 条只有一个省份，块里就一行「所在地区：上海市」：
# 灯说「资料已补全」，模型拿到的却判断不了任何东西。**灯亮着却什么都没进模型，比灯不亮
# 更坏** —— 前者让人以为这个买家已经能匹配了。
#
# 所以就绪判定是块读取字段的**真子集**（被排除的见 BUYER_PARTY_READINESS_EXCLUDED）。
# 留下的每一个都能独立支撑一类判断：做什么、什么性质、多大。
#
# 每种类型的「没填」长得不一样，所以判定按列写死在这里，不给调用方留手写第二份的
# 余地：jsonb 数组的空是 `[]` 不是 null，text 的空可能是 ''，而两个枚举列 not null
# default 'unknown' —— `unknown` 不是 null，但对「这里有没有信息」两者等价。
BUYER_PARTY_READINESS_SQL_BY_FIELD: dict[str, str] = {
    "business_tags_json": "jsonb_array_length(coalesce({alias}.business_tags_json, '[]'::jsonb)) > 0",
    "business_summary": "coalesce({alias}.business_summary, '') <> ''",
    "supplementary_summary": "coalesce({alias}.supplementary_summary, '') <> ''",
    "market_cap_yuan": "{alias}.market_cap_yuan is not null",
    "valuation_yuan": "{alias}.valuation_yuan is not null",
    "current_revenue_yuan": "{alias}.current_revenue_yuan is not null",
    "current_operating_cash_flow_yuan": "{alias}.current_operating_cash_flow_yuan is not null",
    "ownership_type": "coalesce({alias}.ownership_type, 'unknown') <> 'unknown'",
    "listed_status": "coalesce({alias}.listed_status, 'unknown') <> 'unknown'",
}

# 块会读、但**刻意不算就绪**的字段。列出来是为了让「漏接一个新字段」和「有意排除」
# 在测试里分得开：前者是 bug，后者是决定。
BUYER_PARTY_READINESS_EXCLUDED: frozenset[str] = frozenset(
    {
        # 只知道买家在上海，判断不了它和标的有没有产业协同，也判断不了它吃得下多大。
        "location_province",
        "location_city",
        "location_district",
        # 这两个是「上市状态」那一行的后缀，不独立成立。
        "listing_exchange",
        "stock_code",
    }
)


def buyer_party_readiness_sql(alias: str) -> str:
    """「这个买家的自身情况够不够进深评」的布尔表达式。"""
    return " or ".join(
        expression.format(alias=alias) for expression in BUYER_PARTY_READINESS_SQL_BY_FIELD.values()
    )


def buyer_party_fact_block(db: Session, buyer_party_id: Any) -> str:
    """A few lines of the buyer's own business, for synergy questions.

    Requirements like 北控's "与现有业务有关联性" or 北京工控's "强链补链" cannot be
    judged without knowing what the buyer already does. Identity fields are left
    out — the block exists to support the judgement, not to name the buyer.

    联系人 / 联系方式 / notes 都**不进**这个块：前两者是通讯录，后者是运营
    备注。这个块是给模型判断产业协同、财务赋能与决策效率用的，买家自己的
    「风险或其他可能影响并购的重要信息」由 supplementary_summary 承担。
    """
    if not buyer_party_id:
        return ""
    row = db.execute(
        text(
            """
            select business_tags_json, business_summary, ownership_type,
                   listed_status, listing_exchange, stock_code,
                   location_province, location_city, location_district,
                   market_cap_yuan, market_cap_as_of,
                   valuation_yuan, valuation_date,
                   current_revenue_yuan, current_operating_cash_flow_yuan,
                   financial_period_label, supplementary_summary
            from buyer_party
            where id = :buyer_party_id
              and team_id = :team_id
              and workspace_id = :workspace_id
              and deleted_at is null
            """
        ),
        {
            "buyer_party_id": buyer_party_id,
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
        },
    ).mappings().one_or_none()
    if row is None:
        return ""
    location = " ".join(
        value
        for value in (row["location_province"], row["location_city"], row["location_district"])
        if value
    )
    ownership = _buyer_party_enum_label("ownership_type", row["ownership_type"])
    listing = _listed_status_line(row)
    lines = [
        f"主营业务：{'、'.join(row['business_tags_json'] or [])}" if row["business_tags_json"] else None,
        f"业务说明：{row['business_summary']}" if row["business_summary"] else None,
        f"企业性质：{ownership}" if ownership else None,
        f"上市状态：{listing}" if listing else None,
        f"所在地区：{location}" if location else None,
        _market_value_line(row),
        _operating_line(row),
        f"补充信息：{row['supplementary_summary']}" if row["supplementary_summary"] else None,
    ]
    body = "\n".join(line for line in lines if line)
    return f"【买方自身情况（供协同性判断）】\n{body}" if body else ""


def _buyer_party_enum_label(column: str, value: Any) -> str | None:
    """枚举中文名来自指标注册表，unknown 与 NULL 一样当没填。

    unknown 不是 null，但对「这里有没有信息」这个问题两者等价 ——
    往深评上下文里塞一行「企业性质：未知」只会占预算。
    """
    if not value or value == "unknown":
        return None
    options = dict(indicator_by_column("buyer_party", column).enum_options or ())
    return options.get(str(value), str(value))


def _listed_status_line(row: Any) -> str | None:
    listed = _buyer_party_enum_label("listed_status", row["listed_status"])
    if not listed:
        return None
    exchange = _buyer_party_enum_label("listing_exchange", row["listing_exchange"])
    suffix = "".join(part for part in (exchange, row["stock_code"]) if part)
    return f"{listed}（{suffix}）" if suffix else listed


def _market_value_line(row: Any) -> str | None:
    """市值与估值是一个展示位：上市看市值，非上市/拟上市看估值。

    数字必须带时间一起给模型 —— 一个不知道哪天的市值判断不了「买得起吗」。
    """
    if row["listed_status"] == "listed" and row["market_cap_yuan"] is not None:
        as_of = f"，{row['market_cap_as_of']}" if row["market_cap_as_of"] else ""
        return f"市值：{_yuan_text(row['market_cap_yuan'])}{as_of}"
    if row["valuation_yuan"] is not None:
        as_of = f"，{row['valuation_date']}" if row["valuation_date"] else ""
        return f"估值：{_yuan_text(row['valuation_yuan'])}{as_of}"
    if row["market_cap_yuan"] is not None:
        as_of = f"，{row['market_cap_as_of']}" if row["market_cap_as_of"] else ""
        return f"市值：{_yuan_text(row['market_cap_yuan'])}{as_of}"
    return None


def _operating_line(row: Any) -> str | None:
    """营收与经营现金流共用一个期间标签：它们来自同一份定期报告。"""
    parts = [
        f"营收 {_yuan_text(row['current_revenue_yuan'])}" if row["current_revenue_yuan"] is not None else None,
        (
            f"经营现金流 {_yuan_text(row['current_operating_cash_flow_yuan'])}"
            if row["current_operating_cash_flow_yuan"] is not None
            else None
        ),
    ]
    body = "，".join(part for part in parts if part)
    if not body:
        return None
    period = f"（{row['financial_period_label']}）" if row["financial_period_label"] else ""
    return f"经营情况：{body}{period}"


def _yuan_text(value: Any) -> str:
    """人民币元 → 亿/万。深评读的是量级，不是小数位。"""
    amount = float(value)
    if abs(amount) >= 100_000_000:
        return f"{amount / 100_000_000:.2f}".rstrip("0").rstrip(".") + "亿元"
    if abs(amount) >= 10_000:
        return f"{amount / 10_000:.2f}".rstrip("0").rstrip(".") + "万元"
    return f"{amount:.2f}".rstrip("0").rstrip(".") + "元"


def upsert_profile_section(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    section_code: str,
    info_status: str,
    content_text: str | None,
    source_type: str | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
    source_excerpt: str | None = None,
    as_of_date: Any = None,
    review_status: str = "accepted",
    user_id: Any = None,
) -> dict[str, Any]:
    """Insert a new revision of a section rather than overwriting the old one.

    Accepting always supersedes the current revision. Letting as_of_date decide
    which revision is current makes accepting a proposal a silent no-op
    whenever the incoming date is missing or older than what is on file — the
    consultant clicks 确认 and the panel does not change. Whoever accepted last
    wins; as_of_date stays a display and deep-eval signal only.
    """
    # 栏目按实体分。这里曾经只认卖方五栏，于是买家的三块「其他」在
    # normalize 那关放行、到写库这关被拒 —— 解析走到写入阶段才炸。
    allowed_codes = profile_section_codes(entity_type)
    if section_code not in allowed_codes:
        raise ValueError(f"Unknown {entity_type} profile section: {section_code}")
    superseded = db.execute(
        text(
            """
            update entity_profile_section
            set deleted_at = now(), updated_at = now(), updated_by = :user_id
            where team_id = :team_id
              and workspace_id = :workspace_id
              and entity_type = :entity_type
              and entity_id = :entity_id
              and section_code = :section_code
              and deleted_at is null
              and review_status in ('accepted', 'auto_accepted')
            returning id, info_status, content_text
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "section_code": section_code,
            "user_id": user_id,
        },
    ).mappings().all()
    row = db.execute(
        text(
            """
            insert into entity_profile_section (
              team_id, workspace_id, entity_type, entity_id, section_code,
              info_status, content_text, source_type, source_url, source_title,
              source_excerpt, as_of_date, review_status,
              created_by, updated_by
            )
            values (
              :team_id, :workspace_id, :entity_type, :entity_id, :section_code,
              :info_status, :content_text, :source_type, :source_url, :source_title,
              :source_excerpt, :as_of_date, :review_status,
              :user_id, :user_id
            )
            returning
              id, entity_type, entity_id, section_code, info_status, content_text,
              source_type, source_url, source_title, source_excerpt,
              as_of_date::text as as_of_date, review_status,
              created_at::text as created_at, updated_at::text as updated_at
            """
        ),
        {
            "team_id": DEFAULT_TEAM_ID,
            "workspace_id": DEFAULT_WORKSPACE_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "section_code": section_code,
            "info_status": info_status,
            "content_text": content_text,
            "source_type": source_type,
            "source_url": source_url,
            "source_title": source_title,
            "source_excerpt": source_excerpt,
            "as_of_date": as_of_date,
            "review_status": review_status,
            "user_id": user_id,
        },
    ).mappings().one()
    previous = dict(superseded[0]) if superseded else None
    return {**dict(row), "superseded": previous}


def apply_profile_section(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    section_code: str,
    info_status: str,
    content_text: str | None,
    source_type: str | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
    source_excerpt: str | None = None,
    as_of_date: Any = None,
    review_status: str = "accepted",
    user_id: Any = None,
    log_source_type: str = "direct_api",
    log_source_id: UUID | None = None,
    business_update_id: UUID | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a section and record it where 更新记录 can see it.

    Profile sections live in their own table, so nothing about them reached
    action_application_log — a researched section changed the profile with no
    entry in the update timeline and no way to undo it. Since research is what
    writes most of them, that audit trail is the thing making automatic
    acceptance safe rather than merely convenient.
    """
    row = upsert_profile_section(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        section_code=section_code,
        info_status=info_status,
        content_text=content_text,
        source_type=source_type,
        source_url=source_url,
        source_title=source_title,
        source_excerpt=source_excerpt,
        as_of_date=as_of_date,
        review_status=review_status,
        user_id=user_id,
    )
    previous = row.get("superseded")
    write_action_log(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        field_path=f"{PROFILE_SECTION_FIELD_PREFIX}{section_code}",
        old_value=_profile_log_value(previous),
        new_value=_profile_log_value(row),
        source_type=log_source_type,
        source_id=log_source_id,
        business_update_id=business_update_id,
        applied_by=user_id,
        metadata_json={
            "section_code": section_code,
            "section_label": PROFILE_SECTION_LABELS.get(section_code, section_code),
            "profile_section_id": str(row["id"]),
            "superseded_profile_section_id": str(previous["id"]) if previous else None,
            "source_url": source_url,
            **(extra_metadata or {}),
        },
    )
    return row


def _profile_log_value(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "info_status": row.get("info_status"),
        "content_text": row.get("content_text"),
    }
