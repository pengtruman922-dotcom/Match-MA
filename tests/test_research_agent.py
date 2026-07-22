"""Research output handling and the two tools the agent drives."""

from backend.app.jobs.handlers.research import (
    RESEARCH_TOOLS,
    MAX_SEARCH_RESULTS_PER_CALL,
    ResearchTools,
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
                _profile_claim(section_code="chain_position", content_text="行业第一", sources=[]),
            ]
        }
    )

    assert [claim["section_code"] for claim in claims] == ["business_product"]
    assert claims[0]["sources"] == ["https://www.szse.cn/disclosure/a"]
    assert any("chain_position:missing_sources" in note for note in notes)


def test_structured_facts_are_limited_to_the_whitelist() -> None:
    """数值字段本轮不开放：写错的代价和纠错难度都高一档。"""
    claims, notes = normalize_research_output(
        {
            "structured_facts": [
                {"field_path": "industry_secondary", "value": "偏光膜", "sources": ["https://a.com/x"]},
                {"field_path": "current_revenue_yuan", "value": 100, "sources": ["https://a.com/x"]},
            ]
        }
    )

    assert [claim["field_path"] for claim in claims] == ["industry_secondary"]
    assert any("unsupported_field:current_revenue_yuan" in note for note in notes)


def test_relation_comes_from_the_model_and_falls_back_when_unusable() -> None:
    """时效与冲突由 LLM 判断；代码只校验取值在闭集内。"""
    claims, notes = normalize_research_output(
        {
            "profile_sections": [
                _profile_claim(relation="temporal_update"),
                _profile_claim(section_code="tech_team", content_text="团队自研", relation="有点像"),
                _profile_claim(section_code="ops_quality", content_text="客户集中", relation=None),
            ]
        }
    )

    assert [claim["relation"] for claim in claims] == ["temporal_update", "supplement", "supplement"]
    assert any("unknown_relation" in note for note in notes)


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
