"""调研链路上「产出被静默丢弃」的四条线。

依据是生产实测（2026-07-23 ~ 08-03，49 次调研 / 38 次映射的 result_json），
每条都对应一个真实发生过的丢弃，不是假想：

- 映射节点收到买卖两侧合成的栏目表，输出 intent_* 栏目，被下游按
  unknown_section 丢掉 14 次；
- 一次调研里 4 个核心财务字段同时因「缺少合法财务期间截止日」报废，
  而模型给了 period_label；
- agent 的标的视图是 12 列手写，看不到自己能写的 25 个字段；
- 多值闭集列没有形状说明，模型容易回单值字符串。
"""

from __future__ import annotations

import inspect
from datetime import date
from uuid import UUID

from backend.app.jobs.handlers.research import (
    PROFILE_SECTION_CATALOG,
    _claim_financial_period,
    _get_research_target,
    _handle_seller_target_research,
    _prepare_research_claims,
)
from backend.app.jobs.handlers.research_map import _mapping_context
from backend.app.registry.indicators import seller_target_fact_columns
from backend.app.services.profile_sections import profile_sections_for
from backend.app.services.research_apply import (
    RESEARCH_AGENT_STRUCTURED_FIELDS,
    RESEARCH_STRUCTURED_FIELDS,
)


class _RecordingDb:
    """记下执行过的 SQL，并对任何查询返回同一行。"""

    def __init__(self, row: dict | None = None) -> None:
        self.row = row if row is not None else {}
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        row = self.row

        class _Result:
            def mappings(self):
                return self

            def one_or_none(self):
                return row

            def scalars(self):
                return self

            def all(self):
                return []

        return _Result()


# --- 映射上下文 ---------------------------------------------------------


def test_mapping_catalog_never_offers_buyer_sections_to_a_target_run() -> None:
    # PROFILE_SECTION_LABELS 是买卖两侧合成的展示表。喂给标的的映射节点，
    # 模型就会输出 intent_scope / intent_financial / intent_deal，
    # 而 normalize_profile_section_items 按实体判定，照单丢弃。
    context = _mapping_context(_RecordingDb(), report={"report_text": "x"})
    codes = {item["code"] for item in context["profile_section_catalog"]}
    assert codes == {code for code, _, _ in profile_sections_for("seller_target")}
    assert not codes & {"intent_scope", "intent_financial", "intent_deal"}


def test_multi_value_fields_tell_the_mapper_to_emit_an_array() -> None:
    context = _mapping_context(_RecordingDb(), report={"report_text": "x"})
    multi = [item for item in context["writable_fields"] if item.get("multi_value")]
    assert multi, "注册表里的闭集多值列没有出现在映射字段目录中"
    for entry in multi:
        assert entry["allowed_values"], f"{entry['field_path']} 没带取值字典"
        # 「不要输出空数组」这条必须在：空数组在重大风险上的含义是「未核查」，
        # 是系统的默认状态，不是模型能得出的结论。
        assert "数组" in entry["note"] and "空数组" in entry["note"]


def test_mapping_field_catalog_covers_everything_the_agent_may_emit() -> None:
    context = _mapping_context(_RecordingDb(), report={"report_text": "x"})
    assert {item["field_path"] for item in context["writable_fields"]} == (
        RESEARCH_AGENT_STRUCTURED_FIELDS
    )


# --- agent 自己的目录（缺陷的源头，不只是映射节点）-----------------------


def test_agent_section_catalog_is_target_side_only() -> None:
    # 映射节点的目录修好之后，如果 agent 这边还在发买家栏目码，报告里照样会有
    # intent_*，映射只是原样转发 —— 源头在这里。
    codes = {entry["code"] for entry in PROFILE_SECTION_CATALOG}
    assert codes == {code for code, _, _ in profile_sections_for("seller_target")}
    assert not codes & {"intent_scope", "intent_financial", "intent_deal"}


def test_agent_is_only_offered_fields_the_filter_will_accept() -> None:
    """「你可以写的字段」必须与「写了会被收下的字段」是同一份。

    RESEARCH_STRUCTURED_FIELDS 比 AGENT 版多两个内部字段
    （financial_period_end_date / financial_period_label），它们由代码从每条
    claim 的 period_label 派生。列给 agent 的话它会当普通字段输出，
    normalize_research_output 再按 AGENT 版过滤掉并记 unsupported_field。
    """
    source = inspect.getsource(_handle_seller_target_research)
    assert '"allowed_structured_fields": sorted(RESEARCH_AGENT_STRUCTURED_FIELDS)' in source
    assert RESEARCH_AGENT_STRUCTURED_FIELDS < RESEARCH_STRUCTURED_FIELDS
    assert RESEARCH_STRUCTURED_FIELDS - RESEARCH_AGENT_STRUCTURED_FIELDS == {
        "financial_period_end_date",
        "financial_period_label",
    }


# --- 核心财务的期间 -----------------------------------------------------


def _finance_claim(field_path: str, value: int, **overrides) -> dict:
    return {
        "proposal_kind": "structured_fact",
        "field_path": field_path,
        "value": {"value": value, "unit": "元"},
        "relation": "supplement",
        **overrides,
    }


def test_period_label_backfills_a_missing_machine_date() -> None:
    assert _claim_financial_period({"as_of_date": None, "period_label": "2024年度"}) == "2024-12-31"
    assert _claim_financial_period({"as_of_date": "", "period_label": "2025年三季度"}) == "2025-09-30"
    # 已有合法 ISO 日期时不动它。
    assert _claim_financial_period({"as_of_date": "2025-06-30", "period_label": "2024年度"}) == "2025-06-30"
    # 推不出来仍然是 None：期间不明的财务数字不能进比较，更不能覆盖已有值。
    assert _claim_financial_period({"as_of_date": None, "period_label": "最近一期"}) is None
    assert _claim_financial_period({"as_of_date": None, "period_label": None}) is None


def test_a_whole_financial_snapshot_survives_when_only_period_label_is_given() -> None:
    # 生产里发生过的那一次：4 个字段同时被判「缺少合法财务期间截止日」。
    claims = _prepare_research_claims(
        _RecordingDb({"financial_period_end_date": None}),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[
            _finance_claim("current_revenue_yuan", 120, as_of_date=None, period_label="2024年度"),
            _finance_claim("current_net_profit_yuan", 12, as_of_date=None, period_label="2024年度"),
        ],
    )
    assert not [claim for claim in claims if claim.get("validation_error")]
    assert {claim["as_of_date"] for claim in claims} == {"2024-12-31"}


def test_backfilled_period_still_faces_the_older_period_guard() -> None:
    # 回退推导不是放行：推出来的日期照样参与「不许旧期覆盖新期」。
    claims = _prepare_research_claims(
        _RecordingDb({"financial_period_end_date": date(2025, 12, 31)}),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[_finance_claim("current_revenue_yuan", 90, as_of_date=None, period_label="2024年度")],
    )
    assert "早于当前期间" in claims[0]["validation_error"]


def test_backfilled_period_still_faces_the_mixed_period_guard() -> None:
    claims = _prepare_research_claims(
        _RecordingDb({"financial_period_end_date": None}),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[
            _finance_claim("current_revenue_yuan", 120, as_of_date=None, period_label="2024年度"),
            _finance_claim("current_net_profit_yuan", 12, as_of_date=None, period_label="2025年三季度"),
        ],
    )
    assert all("期间不一致" in claim["validation_error"] for claim in claims)


def test_a_period_that_cannot_be_derived_is_still_rejected() -> None:
    claims = _prepare_research_claims(
        _RecordingDb({"financial_period_end_date": None}),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[_finance_claim("current_revenue_yuan", 120, as_of_date=None, period_label="最近一期")],
    )
    assert "缺少合法财务期间截止日" in claims[0]["validation_error"]


# --- agent 的标的视图 ---------------------------------------------------


def test_research_target_view_is_derived_from_the_registry() -> None:
    # 手写 12 列时，agent 看不到库里已有的值（重复检索）也看不到自己能填的字段。
    db = _RecordingDb({"id": UUID("11111111-1111-1111-1111-111111111111")})
    _get_research_target(db, UUID("11111111-1111-1111-1111-111111111111"))
    sql = db.statements[0]
    for column in seller_target_fact_columns():
        assert f"st.{column}" in sql, f"调研上下文缺列：{column}"
    # agent 能写的字段，它必须都能先看到当前值。
    for column in RESEARCH_AGENT_STRUCTURED_FIELDS:
        assert f"st.{column}" in sql
