"""Research output handling and the two tools the agent drives."""

import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from backend.app.jobs.handlers.research import (
    RESEARCH_TOOLS,
    MAX_SEARCH_RESULTS_PER_CALL,
    ResearchTools,
    _current_profiles_for_prompt,
    _financial_period_from_label,
    _prepare_research_claims,
    _should_auto_accept_research_proposal,
    _structured_fact_relation,
    normalize_research_output,
    research_source_type,
)
from backend.app.services.search_providers import SearchError, SearchHit


def _profile_claim(**overrides) -> dict:
    claim = {
        "section_code": "business_product",
        "content_text": "核心产品为偏光膜，供货给面板厂",
        "sources": ["https://www.szse.cn/disclosure/a"],
        "relation": "supplement",
        "confidence": 0.9,
    }
    claim.update(overrides)
    return claim


def test_claims_without_a_source_url_are_dropped() -> None:
    """无法追溯到页面的建议对复核者没有意义。"""
    claims, notes = normalize_research_output(
        {
            "profile_sections": [
                _profile_claim(),
                _profile_claim(section_code="tech_team", content_text="行业第一", sources=[]),
            ]
        }
    )

    assert [claim["section_code"] for claim in claims] == ["business_product"]
    assert claims[0]["sources"] == ["https://www.szse.cn/disclosure/a"]
    assert any("tech_team:missing_sources" in note for note in notes)


def test_field_level_excerpt_survives_normalization() -> None:
    claims, _ = normalize_research_output(
        {
            "structured_facts": [
                {
                    "field_path": "current_revenue_yuan",
                    "value": {"value": "2102873724.18", "unit": "元"},
                    "sources": ["https://static.cninfo.com.cn/report.pdf"],
                    "source_title": "2024 年年度报告",
                    "source_excerpt": "营业收入 2,102,873,724.18 元",
                    "as_of_date": "2024-12-31",
                    "period_label": "2024年度",
                }
            ]
        }
    )

    assert claims[0]["source_title"] == "2024 年年度报告"
    assert claims[0]["source_excerpt"] == "营业收入 2,102,873,724.18 元"


def test_structured_relation_uses_financial_period_before_value() -> None:
    assert _structured_fact_relation(
        field_path="current_revenue_yuan",
        current_value=100,
        new_value=100,
        current_period="2024-12-31",
        new_period="2025-12-31",
    ) == "temporal_update"
    assert _structured_fact_relation(
        field_path="current_revenue_yuan",
        current_value=100,
        new_value=120,
        current_period="2024-12-31",
        new_period="2024-12-31",
    ) == "same_period_conflict"


def test_auto_accept_boundary_requires_trusted_primary_source() -> None:
    assert _should_auto_accept_research_proposal(
        {"conflict_kind": "consistent", "source_type": "public_web"}
    ) is True
    assert _should_auto_accept_research_proposal(
        {"conflict_kind": "supplement", "source_type": "regulatory_disclosure"}
    ) is True
    assert _should_auto_accept_research_proposal(
        {"conflict_kind": "supplement", "source_type": "public_web"}
    ) is False
    assert _should_auto_accept_research_proposal(
        {"conflict_kind": "same_period_conflict", "source_type": "regulatory_disclosure"}
    ) is False


class _CurrentFactsDb:
    def __init__(self, row: dict) -> None:
        self.row = row

    def execute(self, *args, **kwargs):
        row = self.row

        class _Result:
            def mappings(self):
                return self

            def one_or_none(self):
                return row

        return _Result()


def _finance_claim(field_path: str, value: int, period: str) -> dict:
    return {
        "proposal_kind": "structured_fact",
        "field_path": field_path,
        "value": {"value": value, "unit": "元"},
        "as_of_date": period,
        "relation": "supplement",
    }


def test_financial_guard_blocks_older_and_mixed_period_claims() -> None:
    current = {
        "current_revenue_yuan": Decimal("100"),
        "current_net_profit_yuan": Decimal("10"),
        "financial_period_end_date": date(2025, 12, 31),
    }
    older = _prepare_research_claims(
        _CurrentFactsDb(current),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[_finance_claim("current_revenue_yuan", 90, "2024-12-31")],
    )
    assert "早于当前期间" in older[0]["validation_error"]

    mixed = _prepare_research_claims(
        _CurrentFactsDb({**current, "financial_period_end_date": date(2024, 12, 31)}),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[
            _finance_claim("current_revenue_yuan", 120, "2025-12-31"),
            _finance_claim("current_net_profit_yuan", 12, "2025-09-30"),
        ],
    )
    assert all("期间不一致" in claim["validation_error"] for claim in mixed)


def test_financial_guard_uses_legacy_display_period_until_machine_date_exists() -> None:
    current = {
        "current_revenue_yuan": Decimal("100"),
        "financial_period_label": "2024年度",
        "financial_period_end_date": None,
    }
    newer = _prepare_research_claims(
        _CurrentFactsDb(current),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[_finance_claim("current_revenue_yuan", 120, "2025-12-31")],
    )
    assert newer[0]["relation"] == "temporal_update"
    assert "validation_error" not in newer[0]
    assert newer[0]["current_value_json"]["financial_period_end_date"] == "2024-12-31"

    older = _prepare_research_claims(
        _CurrentFactsDb(current),
        target_id=UUID("11111111-1111-1111-1111-111111111111"),
        claims=[_finance_claim("current_revenue_yuan", 90, "2023-12-31")],
    )
    assert "早于当前期间 2024-12-31" in older[0]["validation_error"]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("2024年年度报告", "2024-12-31"),
        ("2025年一季度", "2025-03-31"),
        ("2025 半年度", "2025-06-30"),
        ("2025Q3", "2025-09-30"),
        ("截至2025年", None),
    ],
)
def test_financial_period_label_fallback_is_deliberately_narrow(label: str, expected: str | None) -> None:
    assert _financial_period_from_label(label) == expected


def test_structured_facts_are_limited_to_the_whitelist() -> None:
    """0728 起财务数字对调研开放；报价这类只存在于卖方私下诉求的字段仍然关闭。

    公开渠道根本查不到报价，放开它等于逼 agent 编一个。
    """
    claims, notes = normalize_research_output(
        {
            "structured_facts": [
                {"field_path": "industry_pairs_json", "value": [{"l1": "信息技术与通信", "l2": "偏光膜"}], "sources": ["https://a.com/x"]},
                {"field_path": "current_revenue_yuan", "value": 100, "sources": ["https://a.com/x"]},
                {"field_path": "asking_price_yuan", "value": 100, "sources": ["https://a.com/x"]},
            ]
        }
    )

    assert [claim["field_path"] for claim in claims] == ["industry_pairs_json", "current_revenue_yuan"]
    assert any("unsupported_field:asking_price_yuan" in note for note in notes)


def test_relation_is_decided_by_code_against_the_current_revision() -> None:
    """判断两段话说的是不是同一期，是比较不是判断。

    提示词从来没要求过 relation，于是每条建议都回落成 supplement，
    界面上永远只会显示「补充信息」，「与当前信息冲突」不可能出现。
    """
    current = {
        "business_product": {"content_text": "旧的业务描述", "as_of_date": "2024-12-31"},
        "tech_team": {"content_text": "团队自研", "as_of_date": None},
        "ops_quality": {"content_text": "旧的经营描述", "as_of_date": "2024-12-31"},
    }
    claims, _ = normalize_research_output(
        {
            "profile_sections": [
                # 新一期 → 时效更新
                _profile_claim(content_text="新的业务描述", as_of_date="2025-12-31"),
                # 内容与在档的一字不差 → 一致
                _profile_claim(section_code="tech_team", content_text="团队自研"),
                # 同一期却说得不一样 → 冲突，需要人看一眼
                _profile_claim(section_code="ops_quality", content_text="客户集中", as_of_date="2024-12-31"),
                # 在档没有内容 → 补充
                _profile_claim(section_code="deal_terms", content_text="控股权可让"),
            ]
        },
        current_profiles=current,
    )

    assert [(claim["section_code"], claim["relation"]) for claim in claims] == [
        ("business_product", "temporal_update"),
        ("tech_team", "consistent"),
        ("ops_quality", "same_period_conflict"),
        ("deal_terms", "supplement"),
    ]


def test_coverage_list_separates_searched_without_result_from_never_searched() -> None:
    """未检索到的内容 agent 不再输出，所以覆盖清单是唯一的区分依据。"""
    claims, _ = normalize_research_output(
        {"coverage": {"covered": ["identity"], "no_public_information": ["ops_quality"]}}
    )

    assert [(claim["proposal_kind"], claim["section_code"]) for claim in claims] == [
        ("not_found", "ops_quality")
    ]
    # 只在覆盖清单里被点名的栏目才变 not_found，没提到的保持 missing。
    assert all(claim["section_code"] != "identity" for claim in claims)


def test_not_found_sections_become_confirmed_gaps() -> None:
    """「查过但没有」和「从未查过」在推荐里不是一回事。"""
    claims, _ = normalize_research_output({"not_found": ["ops_quality", "ops_quality", "沒這欄"]})

    assert [(claim["proposal_kind"], claim["section_code"]) for claim in claims] == [
        ("not_found", "ops_quality")
    ]
    assert claims[0]["info_status"] == "not_found"


def test_not_found_never_erases_a_section_that_already_has_content() -> None:
    claims, notes = normalize_research_output(
        {"not_found": ["business_product"]},
        current_profiles={"business_product": {"info_status": "filled", "content_text": "已有内容"}},
    )

    assert claims == []
    assert any("already_filled" in note for note in notes)


def test_claims_stay_json_serialisable_when_current_profiles_carry_dates() -> None:
    """生产事故回归：画像行里的 date/datetime 会被原样塞进 JSONB 绑定。

    `Object of type date is not JSON serializable` 在 agent 跑完之后才抛，
    整个事务连同证据、建议和 last_research_at 一起回滚 —— 表现是"点了没反应"。
    """
    current = {
        "business_product": {
            "entity_id": UUID("11111111-1111-1111-1111-111111111111"),
            "info_status": "filled",
            "content_text": "已有内容",
            "as_of_date": date(2026, 7, 24),
            "updated_at": datetime(2026, 7, 24, 7, 48, 53),
        }
    }

    claims, _ = normalize_research_output(
        {"profile_sections": [_profile_claim()]},
        current_profiles=current,
    )

    assert len(claims) == 1
    # 落库前 proposal 的 current_value_json 走 JSONB 绑定，用默认 encoder 才算数。
    json.dumps(claims[0]["current_value_json"])
    json.dumps(_current_profiles_for_prompt(current))


def test_non_object_output_is_rejected_rather_than_guessed_at() -> None:
    claims, notes = normalize_research_output("不是 JSON")

    assert claims == []
    assert notes == ["research_output:not_an_object"]


def test_source_type_recognizes_official_and_regulatory_domains() -> None:
    site = "https://www.xinghai.com/about"

    assert research_source_type("https://ir.xinghai.com/a", target_website=site) == "company_website"
    assert research_source_type("https://www.szse.cn/a", target_website=site) == "regulatory_disclosure"
    assert research_source_type("https://credit.hangzhou.gov.cn/a") == "government"
    assert research_source_type("https://news.example.com/a") == "public_web"


class _FakeCall:
    def __init__(self, name: str, arguments: dict) -> None:
        self.name = name
        self.arguments = arguments


def _hit(url: str, raw_content: str | None = None) -> SearchHit:
    return SearchHit(
        url=url,
        title="星海新材料简介",
        snippet="核心产品为偏光膜。" * 100,
        raw_content=raw_content,
        published_at="2026-06-01",
    )


def test_search_returns_snippets_so_the_model_chooses_what_to_read(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.jobs.handlers.research.run_search",
        lambda *args, **kwargs: [_hit("https://a.com/1", raw_content="全文" * 5000)],
    )
    tools = ResearchTools({"model_name": "tavily"}, "key")

    result = tools(_FakeCall("web_search", {"query": "星海新材料 主营业务"}))

    entry = result["results"][0]
    assert "raw_content" not in entry
    assert len(entry["snippet"]) <= 600
    assert entry["full_text_available"] is True
    assert tools.searched_queries == ["星海新材料 主营业务"]


def test_fetch_reuses_page_text_the_search_already_paid_for(monkeypatch) -> None:
    """搜索接口已经返回过正文，再抓一次是白花一次往返。"""
    monkeypatch.setattr(
        "backend.app.jobs.handlers.research.run_search",
        lambda *args, **kwargs: [_hit("https://a.com/1", raw_content="来自搜索接口的正文")],
    )

    def fail_fetch(url, **kwargs):
        raise AssertionError("已有正文时不应发起抓取")

    monkeypatch.setattr("backend.app.jobs.handlers.research.fetch_page_text", fail_fetch)
    tools = ResearchTools({"model_name": "tavily"}, "key")
    tools(_FakeCall("web_search", {"query": "q"}))

    result = tools(_FakeCall("fetch_page", {"url": "https://a.com/1"}))

    assert result["text"] == "来自搜索接口的正文"
    assert result["source"] == "search_provider"


def test_fetch_falls_back_to_crawling_and_reports_failure_to_the_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.jobs.handlers.research.fetch_page_text",
        lambda url, **kwargs: "自建抓取的正文" if url.endswith("/live") else None,
    )
    tools = ResearchTools({"model_name": "tavily"}, "key")

    assert tools(_FakeCall("fetch_page", {"url": "https://a.com/live"}))["source"] == "direct_fetch"
    dead = tools(_FakeCall("fetch_page", {"url": "https://a.com/dead"}))
    assert "无法抓取" in dead["error"]


def test_search_failure_is_returned_to_the_model_not_raised(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise SearchError("配额用尽")

    monkeypatch.setattr("backend.app.jobs.handlers.research.run_search", boom)
    tools = ResearchTools({"model_name": "tavily"}, "key")

    assert "配额用尽" in tools(_FakeCall("web_search", {"query": "q"}))["error"]


def test_search_result_count_is_capped(monkeypatch) -> None:
    seen = {}

    def capture(provider, query, *, max_results, api_key=None):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr("backend.app.jobs.handlers.research.run_search", capture)
    tools = ResearchTools({"model_name": "tavily"}, "key")

    tools(_FakeCall("web_search", {"query": "q", "max_results": 500}))

    assert seen["max_results"] == MAX_SEARCH_RESULTS_PER_CALL


def test_tool_schemas_declare_both_tools() -> None:
    names = [tool["function"]["name"] for tool in RESEARCH_TOOLS]

    assert names == ["web_search", "fetch_page"]
    assert all(tool["type"] == "function" for tool in RESEARCH_TOOLS)


def test_mapping_job_always_uses_the_research_queue() -> None:
    from backend.app.jobs.handlers.research import _enqueue_research_map_job
    from backend.app.jobs.queue import JobClaim

    captured = {}

    class _Db:
        def execute(self, statement, params):
            captured.update(params)

            class _Result:
                @staticmethod
                def scalar_one():
                    return UUID("44444444-4444-4444-4444-444444444444")

            return _Result()

    legacy_parent = JobClaim(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        job_type="seller_target_research",
        queue_name="llm",
        entity_type="seller_target",
        entity_id=UUID("22222222-2222-2222-2222-222222222222"),
        correlation_id=None,
        payload_json={},
        attempt_count=1,
        max_attempts=1,
    )

    _enqueue_research_map_job(
        _Db(),
        job=legacy_parent,
        target_id=legacy_parent.entity_id,
    )

    assert captured["queue_name"] == "research"


def test_structured_fact_validation_raises_a_plain_error_for_the_worker() -> None:
    """调研自己采纳建议，校验失败不能是 HTTPException —— 后台任务里没有请求。"""
    from backend.app.services.research_apply import ResearchApplyError, normalize_structured_fact

    with pytest.raises(ResearchApplyError):
        normalize_structured_fact(None, "listed_status", "差不多上市了")
    with pytest.raises(ResearchApplyError):
        normalize_structured_fact(None, "business_summary", "   ")
    assert normalize_structured_fact(None, "listed_status", "listed") == "listed"


def test_money_units_are_converted_by_code_not_by_the_model() -> None:
    """agent 交出原文数字和单位，换算在这里做。

    差一个数量级是一万倍，而且进了筛选完全看不出来 —— 这种确定性转换
    交给模型算是没有理由的。
    """
    from backend.app.services.research_apply import ResearchApplyError, normalize_structured_fact

    assert normalize_structured_fact(None, "current_revenue_yuan", {"value": "83,200.00", "unit": "万元"}) == 832000000
    assert normalize_structured_fact(None, "market_cap_yuan", {"value": "12.5", "unit": "亿元"}) == 1250000000
    # 不带单位视同元，裸数字也认 —— 规范化节点可能已经折算过。
    assert normalize_structured_fact(None, "valuation_yuan", 832000000) == 832000000
    # 比率有自己的量纲，单位只可能是 % 或倍，绝不能拿来做乘数。
    assert normalize_structured_fact(None, "current_debt_ratio", {"value": "45%", "unit": "%"}) == 45
    assert normalize_structured_fact(None, "pe_ratio", "17.5") == Decimal("17.5")

    with pytest.raises(ResearchApplyError):
        normalize_structured_fact(None, "current_revenue_yuan", {"value": "8.32", "unit": "斤"})
    with pytest.raises(ResearchApplyError):
        normalize_structured_fact(None, "current_revenue_yuan", {"value": "去年三个亿", "unit": "元"})


def test_a_rejected_fact_leaves_the_rest_of_the_run_intact() -> None:
    """一条建议校验不过就留在待复核，不该让整轮调研失败。"""
    from backend.app.services.research_apply import ResearchApplyError, apply_research_proposal

    with pytest.raises(ResearchApplyError):
        apply_research_proposal(
            None,
            {
                "id": "p1",
                "entity_id": "e1",
                "proposal_kind": "structured_fact",
                "field_path": "current_revenue_yuan",
                "proposed_value_json": {"value": "不是数字"},
            },
            user_id="u1",
        )


def test_invalid_legacy_pending_proposal_is_not_actionable_in_the_api() -> None:
    from backend.app.api.routes.research import _proposal_output

    proposal = _proposal_output(
        {
            "id": UUID("11111111-1111-1111-1111-111111111111"),
            "proposal_kind": "structured_fact",
            "field_path": "pe_ratio",
            "proposed_value_json": {"value": "亏损，无有效PE（TTM约-26.08）"},
            "current_value_json": {},
            "section_code": None,
            "anchor_matches_json": [],
        },
        db=object(),
    )

    assert proposal["is_actionable"] is False
    assert "不是数字" in proposal["validation_error"]


def test_field_writer_rejection_is_translated_so_one_bad_value_cannot_abort_the_run() -> None:
    """FieldWriteError 和 ResearchApplyError 是兄弟类。

    不翻译的话它会越过调用方的 per-claim 捕获，一个越界的负债率
    就能把整轮调研连同其他已通过的建议一起回滚。
    """
    from backend.app.services.research_apply import ResearchApplyError, apply_research_proposal

    class _NeverReached:
        def execute(self, *a, **k):
            raise AssertionError("授权校验应该在读库之前就拒绝")

    with pytest.raises(ResearchApplyError):
        apply_research_proposal(
            _NeverReached(),
            {
                "id": "p1",
                "entity_id": "e1",
                "proposal_kind": "structured_fact",
                # 负债率 150% 越界，field_writer 会抛 FieldWriteError
                "field_path": "current_debt_ratio",
                "proposed_value_json": {"value": 150},
            },
            user_id="u1",
        )
