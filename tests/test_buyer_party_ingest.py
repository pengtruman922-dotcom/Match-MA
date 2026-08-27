"""买家主体灌入链的守卫。

这条链上真正值得钉住的不是「能不能跑通」，而是几个**取舍**：契约必须从注册表
派生（手写第二份必然漂）、归一节点不裁决真冲突（让模型在两个来源之间选一个
本质是让模型猜）、改名永远走复核（改错不报错，只会让人找不到东西）。
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from backend.app.jobs.handlers.research import ResearchTools
from backend.app.jobs.handlers.buyer_party_ingest import (
    LLM_QUEUE_NAME,
    NORMALIZE_JOB_TYPE,
    PARSE_JOB_TYPE,
    RESEARCH_JOB_TYPE,
    RESEARCH_OUTCOMES,
    RESEARCH_QUEUE_NAME,
    _buyer_name_claims,
    _build_research_context,
    _buyer_party_field_contract,
    _claims_from_parse_output,
    _claims_from_research_result,
    _collect_information_gaps,
    _is_empty_value,
    _reconcile_buyer_party_claims,
    _research_outcome,
    _should_auto_accept,
    buyer_party_refresh_targets,
    normalize_buyer_party_output,
)
from backend.app.jobs.retry_policy import RESEARCH_JOB_TYPES
from backend.app.services.buyer_party_processing_state import (
    RESEARCH_OUTCOME_LABELS,
    _status_label,
)
from backend.app.registry.indicators import writable_columns
from backend.app.services.research_apply import (
    BUYER_PARTY_MODEL_PARSE_FIELDS,
    BUYER_PARTY_MODEL_RESEARCH_FIELDS,
    BUYER_PARTY_PROPOSABLE_FIELDS,
    BUYER_PARTY_TIME_COMPANION_FIELDS,
    ResearchApplyError,
    apply_research_proposal,
    normalize_structured_fact,
)

EMPTY_PARTY = {
    "buyer_name": "北控",
    "ownership_type": "unknown",
    "listed_status": "unknown",
    "market_cap_yuan": None,
    "market_cap_as_of": None,
    "current_revenue_yuan": None,
    "financial_period_label": None,
    "business_summary": None,
}


def _claim(**overrides):
    claim = {
        "field_path": "ownership_type",
        "value": "state_owned",
        "source_type": "web",
        "period_label": None,
        "as_of_date": None,
        "sources": ["https://example.com/a"],
        "source_title": "示例",
        "source_excerpt": "买家性质：央企医药龙头",
        "alternative": None,
        "validation_error": None,
    }
    claim.update(overrides)
    return claim


# ---------------------------------------------------------------------------
# 契约从注册表派生
# ---------------------------------------------------------------------------


def test_contracts_are_derived_from_the_registry_not_hand_written() -> None:
    """一个字段名都不该手写。

    注册表已经把可写来源编码好了：``stock_code`` / ``listing_exchange`` 的
    ``writable_by`` 不含 parse（需求材料里基本不会有股票代码），联系人三列不含
    research（只能来自非公开渠道）。这两条业务规则的落点就是这里。
    """
    parse_columns = {item["field_path"] for item in _buyer_party_field_contract(BUYER_PARTY_MODEL_PARSE_FIELDS)}
    research_columns = {
        item["field_path"] for item in _buyer_party_field_contract(BUYER_PARTY_MODEL_RESEARCH_FIELDS)
    }

    assert parse_columns == BUYER_PARTY_MODEL_PARSE_FIELDS
    assert research_columns == BUYER_PARTY_MODEL_RESEARCH_FIELDS
    assert BUYER_PARTY_MODEL_PARSE_FIELDS <= writable_columns("parse", "buyer_party")
    assert BUYER_PARTY_MODEL_RESEARCH_FIELDS <= writable_columns("research", "buyer_party")

    for column in ("stock_code", "listing_exchange"):
        assert column not in parse_columns
    for column in ("contact_name", "contact_info_json", "our_contact_name"):
        assert column not in research_columns


def test_time_companion_columns_are_not_offered_to_the_model() -> None:
    """市值日期 / 财务期间 / 估值时点由代码从事实自己的期间元数据派生。

    列进「你可以写的字段」，模型就会把它们当普通字段单独输出，于是同一份财务
    快照出现两条可能互相矛盾的提案。
    """
    assert BUYER_PARTY_TIME_COMPANION_FIELDS == {
        "market_cap_as_of",
        "valuation_date",
        "financial_period_label",
    }
    offered = BUYER_PARTY_MODEL_PARSE_FIELDS | BUYER_PARTY_MODEL_RESEARCH_FIELDS
    assert not (offered & BUYER_PARTY_TIME_COMPANION_FIELDS)


def test_yuan_fields_carry_their_time_companion_in_the_contract() -> None:
    contract = {
        item["field_path"]: item
        for item in _buyer_party_field_contract(BUYER_PARTY_MODEL_RESEARCH_FIELDS)
    }
    assert contract["market_cap_yuan"]["time_companion"] == "market_cap_as_of"
    assert contract["current_revenue_yuan"]["time_companion"] == "financial_period_label"
    assert "每股经营现金流" in contract["current_operating_cash_flow_yuan"]["note"]


def test_unknown_counts_as_empty_for_gap_detection() -> None:
    """``unknown`` 不是 ``null``，但「这个字段有没有值」两者必须等价。

    不等价的话，企业性质与上市状态这两个缺口调研永远看不到。
    """
    assert _is_empty_value("ownership_type", "unknown") is True
    assert _is_empty_value("listed_status", "unknown") is True
    assert _is_empty_value("business_summary", "unknown") is False
    assert _is_empty_value("market_cap_yuan", None) is True


# ---------------------------------------------------------------------------
# 归一输出的过滤
# ---------------------------------------------------------------------------


def test_normalization_drops_what_cannot_be_reviewed() -> None:
    claims, notes = normalize_buyer_party_output(
        {
            "structured_facts": [
                {"field_path": "not_a_column", "value": "x", "source_type": "web", "sources": ["https://a"]},
                {"field_path": "ownership_type", "value": "state_owned", "source_type": "guess"},
                # 调研可写但材料不可写：股票代码在需求材料里基本不会有。
                {"field_path": "stock_code", "value": "600000", "source_type": "material"},
                # web 条目没有链接 = 不可追溯，丢掉。
                {"field_path": "business_summary", "value": "做医药流通", "source_type": "web"},
                {"field_path": "listed_status", "value": "", "source_type": "web", "sources": ["https://a"]},
            ]
        }
    )

    assert claims == []
    assert any("unsupported_field" in note for note in notes)
    assert any("unknown_source_type" in note for note in notes)
    assert any("source_may_not_write" in note for note in notes)
    assert any("missing_sources" in note for note in notes)
    assert any("empty_value" in note for note in notes)


def test_material_claims_need_no_url_but_do_need_an_excerpt() -> None:
    claims, _ = normalize_buyer_party_output(
        {
            "structured_facts": [
                {
                    "field_path": "ownership_type",
                    "value": "state_owned",
                    "source_type": "material",
                    "source_excerpt": "买家性质：央企医药龙头",
                },
                {"field_path": "business_summary", "value": "医药流通", "source_type": "material"},
            ]
        }
    )

    assert [item["field_path"] for item in claims] == ["ownership_type", "business_summary"]
    assert claims[0]["validation_error"] is None
    # 没有原文摘录的条目留下来但不可自动写入：顾问看得到它，只是要自己核。
    assert claims[1]["validation_error"]


# ---------------------------------------------------------------------------
# 三条代码规则
# ---------------------------------------------------------------------------


def test_small_numeric_differences_are_not_a_conflict() -> None:
    """解析「约 180 亿」和调研「181.3 亿」不该变成一条待办。"""
    claims = _reconcile_buyer_party_claims(
        party=dict(EMPTY_PARTY),
        claims=[
            _claim(
                field_path="market_cap_yuan",
                value={"value": 181.3, "unit": "亿元"},
                as_of_date="2026-08-22",
                alternative={
                    "field_path": "market_cap_yuan",
                    "value": {"value": 180, "unit": "亿元"},
                    "source_type": "material",
                    "period_label": None,
                    "as_of_date": "2026-08-22",
                    "sources": [],
                    "source_excerpt": "市值约 180 亿",
                },
            )
        ],
    )

    assert claims[0]["conflict_kind"] == "supplement"
    # 一致时取有来源链接的那个：可追溯的证据比同一句话更有用。
    assert claims[0]["source_type"] == "web"
    assert "同一个值" in claims[0]["cross_source_note"]


def test_the_later_period_wins_when_the_two_sources_disagree_in_time() -> None:
    claims = _reconcile_buyer_party_claims(
        party={**EMPTY_PARTY, "current_revenue_yuan": 1, "financial_period_label": "2023年度"},
        claims=[
            _claim(
                field_path="current_revenue_yuan",
                value={"value": 58, "unit": "亿元"},
                period_label="2024年度",
                alternative={
                    "field_path": "current_revenue_yuan",
                    "value": {"value": 51, "unit": "亿元"},
                    "source_type": "material",
                    "period_label": "2023年度",
                    "as_of_date": None,
                    "sources": [],
                    "source_excerpt": "2023 年营收 51 亿",
                },
            )
        ],
    )

    assert claims[0]["period_label"] == "2024年度"
    assert claims[0]["conflict_kind"] == "temporal_update"


def test_a_real_conflict_is_never_arbitrated() -> None:
    """两边同期、都有证据、值不同 —— 落成待复核，两条来源都留着。

    归一节点没有额外信息，让它在两个来源之间选一个，本质是让模型猜。
    """
    claims = _reconcile_buyer_party_claims(
        party=dict(EMPTY_PARTY),
        claims=[
            _claim(
                value="state_owned",
                alternative={
                    "field_path": "ownership_type",
                    "value": "private",
                    "source_type": "material",
                    "period_label": None,
                    "as_of_date": None,
                    "sources": [],
                    "source_excerpt": "买家是一家民营企业",
                },
            )
        ],
    )

    assert claims[0]["conflict_kind"] == "same_period_conflict"
    assert claims[0]["alternative"]["value"] == "private"
    assert _should_auto_accept(claims[0]) is False


def test_an_older_period_may_not_overwrite_a_newer_one() -> None:
    claims = _reconcile_buyer_party_claims(
        party={**EMPTY_PARTY, "current_revenue_yuan": 100, "financial_period_label": "2024年度"},
        claims=[_claim(field_path="current_revenue_yuan", value={"value": 51, "unit": "亿元"}, period_label="2023年度")],
    )

    assert claims[0]["conflict_kind"] == "same_period_conflict"
    assert "早于当前已记录的期间" in claims[0]["validation_error"]


def test_financial_facts_without_a_period_are_rejected_not_written() -> None:
    """没有时间的财务数字是不可用的，所以时间不是可选项。"""
    claims = _reconcile_buyer_party_claims(
        party=dict(EMPTY_PARTY),
        claims=[_claim(field_path="market_cap_yuan", value={"value": 180, "unit": "亿元"})],
    )

    assert claims[0]["validation_error"]
    assert _should_auto_accept(claims[0]) is False


# ---------------------------------------------------------------------------
# 自动采纳四档
# ---------------------------------------------------------------------------


def test_empty_field_with_one_clear_source_is_auto_accepted() -> None:
    claims = _reconcile_buyer_party_claims(party=dict(EMPTY_PARTY), claims=[_claim()])

    assert claims[0]["conflict_kind"] == "supplement"
    assert _should_auto_accept(claims[0]) is True


def test_conflicting_with_the_current_value_waits_for_a_human() -> None:
    claims = _reconcile_buyer_party_claims(
        party={**EMPTY_PARTY, "ownership_type": "private"},
        claims=[_claim(value="state_owned")],
    )

    assert claims[0]["conflict_kind"] == "same_period_conflict"
    assert _should_auto_accept(claims[0]) is False


def test_renaming_the_buyer_always_waits_for_a_human() -> None:
    """改错名字影响所有关联需求、撮合关系和搜索，**而且不会报错**。"""
    claims = _reconcile_buyer_party_claims(
        party={**EMPTY_PARTY, "buyer_name": "北控"},
        claims=[_claim(field_path="buyer_name", value="北京控股集团有限公司")],
    )

    assert claims[0]["conflict_kind"] == "same_period_conflict"
    assert _should_auto_accept(claims[0]) is False
    # 即使归一节点把它算成补充，也不许自动落库。
    assert _should_auto_accept({**claims[0], "conflict_kind": "supplement"}) is False


def test_only_financial_fields_auto_accept_a_temporal_update() -> None:
    financial = _claim(
        field_path="current_revenue_yuan",
        value={"value": 58, "unit": "亿元"},
        period_label="2024年度",
        conflict_kind="temporal_update",
    )
    narrative = _claim(field_path="business_summary", value="换了一段说法", conflict_kind="temporal_update")

    assert _should_auto_accept(financial) is True
    assert _should_auto_accept(narrative) is False


def test_a_web_claim_without_a_source_is_never_auto_accepted() -> None:
    assert _should_auto_accept(_claim(conflict_kind="supplement", sources=[])) is False
    assert _should_auto_accept(_claim(conflict_kind="supplement", source_excerpt="")) is False


# ---------------------------------------------------------------------------
# 过期刷新与队列
# ---------------------------------------------------------------------------


def test_market_cap_goes_stale_after_a_week_and_valuation_never_does() -> None:
    today = date(2026, 8, 25)
    fresh = {
        "listed_status": "listed",
        "market_cap_as_of": date(2026, 8, 22),
        "financial_period_label": "2026年半年度",
        "valuation_yuan": None,
    }
    stale = {**fresh, "market_cap_as_of": date(2026, 8, 1)}

    assert buyer_party_refresh_targets(fresh, today=today) == []
    assert buyer_party_refresh_targets(stale, today=today) == ["market_cap_yuan"]
    # 非上市公司没有行情，市值不进刷新清单。
    unlisted = {**stale, "listed_status": "unlisted"}
    assert "market_cap_yuan" not in buyer_party_refresh_targets(unlisted, today=today)
    # 估值是非公开信息，公网查不到，永远不自动刷新。
    assert "valuation_yuan" not in buyer_party_refresh_targets(stale, today=today)


def test_a_new_reporting_period_is_checked_by_period_not_by_days() -> None:
    today = date(2026, 8, 25)
    old_report = {"listed_status": "unlisted", "market_cap_as_of": None, "financial_period_label": "2024年度"}

    assert buyer_party_refresh_targets(old_report, today=today) == [
        "current_revenue_yuan",
        "current_operating_cash_flow_yuan",
    ]


def test_only_research_uses_the_research_queue() -> None:
    """秒级解析放进 research 队列会排在十分钟级的调研后面。"""
    assert (PARSE_JOB_TYPE, LLM_QUEUE_NAME) == ("buyer_party_parse", "llm")
    assert (NORMALIZE_JOB_TYPE, LLM_QUEUE_NAME) == ("buyer_party_normalize", "llm")
    assert (RESEARCH_JOB_TYPE, RESEARCH_QUEUE_NAME) == ("buyer_party_research", "research")


def test_expensive_ingest_jobs_do_not_replay_on_every_failure() -> None:
    """调研一次是好几次搜索加多轮模型调用，规范化重跑会再插一份提案。

    两者都只该在「大概会自己好起来」的失败上重试，所以它们进
    ``RESEARCH_JOB_TYPES``；解析便宜且幂等，留给通用重试。
    """
    assert RESEARCH_JOB_TYPE in RESEARCH_JOB_TYPES
    assert NORMALIZE_JOB_TYPE in RESEARCH_JOB_TYPES
    assert PARSE_JOB_TYPE not in RESEARCH_JOB_TYPES


def test_the_package_re_exports_the_three_handlers() -> None:
    """``handlers/__init__`` 的 re-export 是 worker、路由与测试的依赖，别删。"""
    from backend.app.jobs import handlers

    for name in (
        "_handle_buyer_party_parse",
        "_handle_buyer_party_research",
        "_handle_buyer_party_normalize",
    ):
        assert hasattr(handlers, name), name


# ---------------------------------------------------------------------------
# 写回：提案按自己的 entity_type 落地，按自己的 source_type 取写入权限
# ---------------------------------------------------------------------------


def _proposal(**overrides):
    proposal = {
        "id": uuid4(),
        "entity_type": "buyer_party",
        "entity_id": uuid4(),
        "job_id": uuid4(),
        "proposal_kind": "structured_fact",
        "field_path": "ownership_type",
        "proposed_value_json": {"value": "state_owned"},
        "conflict_kind": "supplement",
        "period_label": None,
        "as_of_date": None,
        "source_type": "material",
        "source_url": None,
        "source_title": None,
        "source_excerpt": "买家性质：央企医药龙头",
    }
    proposal.update(overrides)
    return proposal


class _NoDb:
    def execute(self, *args, **kwargs):
        raise AssertionError("这些守卫必须在碰数据库之前就拦下来")


def test_buyer_party_has_no_profile_sections() -> None:
    """两个业务字段（标签 + 说明）就是全部，买家主体不设画像栏。"""
    with pytest.raises(ResearchApplyError):
        apply_research_proposal(
            _NoDb(),
            _proposal(proposal_kind="profile_section", field_path=None, section_code="business_product"),
            user_id=uuid4(),
        )


def test_a_proposal_with_an_unknown_source_cannot_claim_write_authority() -> None:
    """material → parse、web → research。判不出来就不写，而不是随便挑一个。"""
    with pytest.raises(ResearchApplyError):
        apply_research_proposal(_NoDb(), _proposal(source_type="public_web"), user_id=uuid4())


def test_a_time_companion_column_is_not_a_standalone_proposal() -> None:
    with pytest.raises(ResearchApplyError):
        apply_research_proposal(
            _NoDb(),
            _proposal(field_path="financial_period_label", proposed_value_json={"value": "2024年度"}),
            user_id=uuid4(),
        )


def test_an_unsupported_entity_is_refused_rather_than_written_to_the_wrong_table() -> None:
    with pytest.raises(ResearchApplyError):
        apply_research_proposal(_NoDb(), _proposal(entity_type="buyer_intent"), user_id=uuid4())


# ---------------------------------------------------------------------------
# 归一化：按提案自己的实体解释字段
# ---------------------------------------------------------------------------


def test_money_units_are_converted_by_code_not_by_the_model() -> None:
    """差一个数量级是一万倍，进了筛选完全看不出来。"""
    assert normalize_structured_fact(
        None, "market_cap_yuan", {"value": 180, "unit": "亿元"}, entity="buyer_party"
    ) == 18_000_000_000


def test_business_tags_accept_an_array_and_a_bare_string() -> None:
    assert normalize_structured_fact(
        None, "business_tags_json", ["医药流通", " 中药 "], entity="buyer_party"
    ) == ["医药流通", "中药"]
    assert normalize_structured_fact(
        None, "business_tags_json", "医药流通", entity="buyer_party"
    ) == ["医药流通"]


def test_contact_info_is_an_object_column_not_an_array() -> None:
    """注册表里的 json 列几乎都存数组，联系方式是唯一的对象列。"""
    assert normalize_structured_fact(
        None, "contact_info_json", "13800000000", entity="buyer_party"
    ) == {"text": "13800000000"}
    assert normalize_structured_fact(
        None, "contact_info_json", {"phone": "010-1234"}, entity="buyer_party"
    ) == {"phone": "010-1234"}


def test_an_illegal_listed_status_is_refused() -> None:
    with pytest.raises(ResearchApplyError):
        normalize_structured_fact(None, "listed_status", "ipo_soon", entity="buyer_party")


def test_every_research_outcome_has_something_to_show_the_consultant() -> None:
    """「主体无法确认」必须能在界面上和「查不到公开信息」分开。

    分不开的话，agent 会对同一个买家反复空跑、烧光预算，而顾问只看到一句
    「没查到」。这里把终态集合与文案表钉在一起。
    """
    assert RESEARCH_OUTCOMES == set(RESEARCH_OUTCOME_LABELS)
    assert "subject_unresolved" in RESEARCH_OUTCOMES


# ---------------------------------------------------------------------------
# 0827：主体判断交回给 agent，收口按来源数条件启动
# ---------------------------------------------------------------------------


def test_the_buyer_chain_hands_subject_judgement_back_to_the_agent() -> None:
    """代码不再用子串匹配判断「这条结果是不是同一家公司」。

    0721 方案 §2.7 已经论证过：代码只能做机械匹配，而区分两家同名公司需要的
    信息常常压根不在那个页面上。买家侧更极端 —— 名字是顾问手输的简称，
    实测「上海鼎汇实业集团」4 次检索 40 条结果命中 0 条，fetch_page 全被拒。
    """
    tools = ResearchTools({}, "key", subject_names=["上海鼎汇实业集团"], subject_gate=False)

    assert tools._subject_anchors == []
    assert tools._matches_subject("上海鼎汇实业有限公司", "") is True
    assert tools.early_stop_reason is None
    # 标的侧不受影响：闸门默认还在，该不该拆是另一单。
    seller = ResearchTools({}, "key", subject_names=["上海鼎汇实业集团"])
    assert seller._matches_subject("上海鼎汇实业有限公司", "") is False


def test_outcome_reads_the_agents_verdict_not_the_hit_rate() -> None:
    assert _research_outcome({"subject_resolved": False}, parsed_ok=True) == "subject_unresolved"
    assert _research_outcome(
        {"subject": {"status": "ambiguous"}}, parsed_ok=True
    ) == "subject_unresolved"
    # 认出了主体但确实没有公开信息 —— 和「没认出这家公司」是两回事。
    assert _research_outcome({"subject_resolved": True, "findings": []}, parsed_ok=True) == "no_public_information"
    assert _research_outcome(
        {"subject_resolved": True, "findings": [{"field_path": "market_cap_yuan"}]}, parsed_ok=True
    ) == "found"
    assert _research_outcome(None, parsed_ok=False) == "failed"


def test_research_findings_translate_into_claims_without_a_second_model_call() -> None:
    """调研的 findings 本来就是 claim 形状，单来源时代码直接接住。"""
    claims = _claims_from_research_result(
        {
            "findings": [
                {
                    "field_path": "ownership_type",
                    "value": "state_owned",
                    "sources": ["https://example.com/a"],
                    "source_excerpt": "国资委下属企业",
                },
                # 没有来源的 web 条目不可追溯，照样丢掉。
                {"field_path": "business_summary", "value": "医药流通"},
            ]
        }
    )

    assert [item["field_path"] for item in claims] == ["ownership_type"]
    assert claims[0]["source_type"] == "web"


def test_parse_output_translates_into_claims_by_joining_fields_and_evidence() -> None:
    claims = _claims_from_parse_output(
        {
            "fields": {"ownership_type": "private", "business_summary": "做医药流通"},
            "evidence": [{"field": "ownership_type", "quote": "买家是一家民营企业"}],
        }
    )

    by_field = {item["field_path"]: item for item in claims}
    assert by_field["ownership_type"]["source_excerpt"] == "买家是一家民营企业"
    assert by_field["ownership_type"]["validation_error"] is None
    # 拼不上证据的字段仍然保留，只是不可自动写入 —— 顾问看得到、可以自己核。
    assert by_field["business_summary"]["validation_error"]


def test_the_resolved_official_name_becomes_a_rename_proposal_in_the_same_run() -> None:
    """agent 自己判断搜到的公司是不是同一家，认出来就在同一轮里交回工商全称。

    不需要「先提改名 → 人采纳 → 再跑第二轮」。但落库仍然走复核：
    改错名字影响所有关联需求、撮合关系和搜索，而且不会报错。
    """
    claims = _buyer_name_claims(
        {"buyer_name": "上海鼎汇实业集团"},
        parse_output={},
        research_result={
            "subject": {"resolved_name": "上海鼎汇实业集团有限公司", "status": "confirmed", "note": "工商登记确认"},
            "findings": [{"field_path": "ownership_type", "sources": ["https://example.com/a"]}],
        },
    )

    assert len(claims) == 1
    assert claims[0]["field_path"] == "buyer_name"
    assert claims[0]["value"] == "上海鼎汇实业集团有限公司"
    assert claims[0]["sources"] == ["https://example.com/a"]
    prepared = _reconcile_buyer_party_claims(
        party={**EMPTY_PARTY, "buyer_name": "上海鼎汇实业集团"}, claims=claims
    )
    assert _should_auto_accept(prepared[0]) is False


def test_an_unconfirmed_subject_never_proposes_a_rename() -> None:
    assert _buyer_name_claims(
        {"buyer_name": "上海鼎汇实业集团"},
        parse_output={},
        research_result={"subject": {"resolved_name": "上海鼎汇实业有限公司", "status": "unresolved"}},
    ) == []


def test_the_model_may_not_write_the_name_from_the_fields_block() -> None:
    """名字在主体块里已经说过一次，fields 里再说一次就会出现两条互相矛盾的改名。"""
    assert "buyer_name" not in BUYER_PARTY_MODEL_PARSE_FIELDS
    assert "buyer_name" not in BUYER_PARTY_MODEL_RESEARCH_FIELDS
    # 但它仍然是一条合法提案 —— 只是作者是代码，不是模型。
    assert "buyer_name" in BUYER_PARTY_PROPOSABLE_FIELDS
    claims, notes = normalize_buyer_party_output(
        {"structured_facts": [{"field_path": "buyer_name", "value": "X", "source_type": "material"}]}
    )
    assert claims == []
    assert any("unsupported_field" in note for note in notes)


def test_gaps_survive_a_run_that_found_nothing() -> None:
    """主体没认出来时，agent 报的 not_found 仍然要落成缺口。

    它是「以后一键去补全」的依据；丢掉它，界面上就只剩一句「没查到」。
    """
    gaps = _collect_information_gaps(
        model_gaps=None,
        parse_result={},
        research_result={"not_found": ["market_cap_yuan", "current_revenue_yuan"]},
        party=dict(EMPTY_PARTY),
    )

    assert [item["field"] for item in gaps] == ["market_cap_yuan", "current_revenue_yuan"]
    assert all(item["reason"] for item in gaps)


def test_an_unconfirmed_subject_says_the_fields_were_never_searched() -> None:
    """主体没认出来时这些字段其实没被查过。

    说成「查过但没有公开信息」会让顾问以为这家公司公开信息就是这么少，
    从而不去补工商全称 —— 而补全称正是这一轮唯一的出路。
    """
    gaps = _collect_information_gaps(
        model_gaps=None,
        parse_result={},
        research_result={"not_found": ["market_cap_yuan"], "research_outcome": "subject_unresolved"},
        party=dict(EMPTY_PARTY),
    )

    assert "主体未确认" in gaps[0]["reason"]


def test_a_run_that_wrote_nothing_does_not_call_itself_complete() -> None:
    """「跑完了」和「补到了」是两件事，绿标说反话比不显示更糟。"""
    assert _status_label(
        "succeeded", research_outcome="subject_unresolved", written_count=0, normalize_finished=True
    ) == "未能确认主体"
    assert _status_label(
        "succeeded", research_outcome="no_public_information", written_count=0, normalize_finished=True
    ) == "没查到可用信息"
    assert _status_label(
        "succeeded", research_outcome="found", written_count=4, normalize_finished=True
    ) == "已补全"


def test_the_researcher_is_given_values_not_just_field_names() -> None:
    """只给字段名，模型只能凭猜写值。

    实测「深圳绿源」那轮 agent 写了 ownership_type="民营企业"、
    listed_status="未上市"，两条都被枚举校验丢掉。v0.1 时代看不出来 ——
    归一节点总会跑而它手里有闭集；改成条件启动之后，单来源就没人翻译了。
    """
    context = _build_research_context(
        party={"buyer_name": "X", "aliases_json": [], "listed_status": "unknown"},
        mode="fill",
        parse_output={},
        refresh_fields=None,
        max_tool_calls=12,
    )

    fields = {item["field_path"]: item for item in context["writable_fields"]}
    assert set(fields) == BUYER_PARTY_MODEL_RESEARCH_FIELDS
    assert [option["value"] for option in fields["ownership_type"]["allowed_values"]] == [
        "state_owned",
        "private",
        "foreign",
        "other",
        "unknown",
    ]
    # 金额形状与时间伴生列也要跟着字段一起交代，否则财务数字写不进来。
    assert fields["market_cap_yuan"]["time_companion"] == "market_cap_as_of"
    assert "亿元" in fields["market_cap_yuan"]["note"]
    assert set(context["enum_contract"]) == {"ownership_type", "listed_status", "listing_exchange"}
