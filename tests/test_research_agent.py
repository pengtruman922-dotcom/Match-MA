from backend.app.jobs.handlers.research import (
    build_research_queries,
    classify_research_conflict,
    normalize_research_output,
    research_source_type,
)


def _evidence() -> list[dict]:
    return [
        {
            "evidence_ref": "E1",
            "url": "https://www.szse.cn/disclosure/a",
            "title": "星海新材料公告",
            "snippet": "杭州星海新材料股份有限公司的核心产品为偏光膜，研发团队共80人。",
            "raw_content": "",
            "published_at": "2026-06-01",
            "provider": "test",
            "source_type": "regulatory_disclosure",
            "anchor_matches": [
                {"kind": "name", "value": "杭州星海新材料股份有限公司"},
                {"kind": "region", "value": "杭州"},
            ],
        }
    ]


def test_research_queries_cover_profile_dimensions() -> None:
    queries = build_research_queries(
        {
            "target_subject_name": "杭州星海新材料股份有限公司",
            "registered_city": "杭州市",
        }
    )

    assert len(queries) == 3
    assert all('"杭州星海新材料股份有限公司"' in query for query in queries)
    assert any("产业链" in query for query in queries)
    assert any("核心技术" in query for query in queries)
    assert any("交易" in query for query in queries)


def test_research_output_requires_trusted_evidence_references() -> None:
    claims, notes = normalize_research_output(
        {
            "profile_sections": [
                {
                    "section_code": "business_product",
                    "content_text": "核心产品为偏光膜",
                    "evidence_refs": ["E1"],
                    "evidence_quote": "核心产品为偏光膜",
                    "confidence": 0.9,
                },
                {
                    "section_code": "chain_position",
                    "content_text": "行业第一",
                    "evidence_refs": ["E404"],
                },
            ],
            "structured_facts": [
                {
                    "field_path": "industry_secondary",
                    "value": "偏光膜",
                    "evidence_refs": ["E1"],
                },
                {
                    "field_path": "current_revenue_yuan",
                    "value": 100,
                    "evidence_refs": ["E1"],
                },
            ],
        },
        evidence=_evidence(),
    )

    assert [(claim["proposal_kind"], claim.get("section_code") or claim.get("field_path")) for claim in claims] == [
        ("profile_section", "business_product"),
        ("structured_fact", "industry_secondary"),
    ]
    assert claims[0]["source_excerpt"] == "核心产品为偏光膜"
    assert any("missing_trusted_evidence_ref" in note for note in notes)
    assert any("unsupported_field:current_revenue_yuan" in note for note in notes)


def test_conflict_classification_is_conservative_and_period_aware() -> None:
    assert classify_research_conflict(current_value=None, proposed_value="新信息") == "supplement"
    assert classify_research_conflict(current_value="技术自研", proposed_value=" 技术 自研 ") == "consistent"
    assert classify_research_conflict(
        current_value="2024年行业前三",
        proposed_value="2025年行业第一",
        current_as_of_date="2024-12-31",
        proposed_as_of_date="2025-12-31",
    ) == "temporal_update"
    assert classify_research_conflict(
        current_value="行业前三",
        proposed_value="行业第一",
        current_as_of_date="2025-12-31",
        proposed_as_of_date="2025-12-31",
    ) == "same_period_conflict"


def test_source_authority_recognizes_official_and_regulatory_domains() -> None:
    target = {"website": "https://www.xinghai.com/about"}

    assert research_source_type("https://ir.xinghai.com/a", target=target) == "company_website"
    assert research_source_type("https://www.szse.cn/a", target=target) == "regulatory_disclosure"
    assert research_source_type("https://credit.hangzhou.gov.cn/a", target=target) == "government"
    assert research_source_type("https://news.example.com/a", target=target) == "public_web"
