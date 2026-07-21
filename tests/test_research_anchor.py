from backend.app.services.research_anchor import (
    AnchorMatch,
    build_anchors,
    is_evidence_trusted,
    match_anchors,
)
from backend.app.services.search_providers.fetch import html_to_text


ENTITY = {
    "target_name": "杭州星海新材料",
    "target_subject_name": "杭州星海新材料股份有限公司",
    "unified_social_credit_code": "91330100MA2GX8RT7K",
    "official_website": "https://www.xinghai-materials.com/about",
    "legal_representative": "陈立",
}


def test_build_anchors_collects_identifying_features() -> None:
    anchors = build_anchors(ENTITY)

    assert anchors["credit_code"] == ["91330100MA2GX8RT7K"]
    assert "杭州星海新材料股份有限公司" in anchors["name"]
    assert anchors["domain"] == ["xinghai-materials.com"]
    assert anchors["legal_person"] == ["陈立"]


def test_short_names_are_not_used_as_anchors() -> None:
    """"中电""华能"这类短名到处都是，拿它当锚点等于没有锚点。"""
    anchors = build_anchors({"target_name": "中电"})

    assert anchors.get("name") is None


def test_credit_code_alone_identifies_the_entity() -> None:
    matches = match_anchors(
        build_anchors(ENTITY),
        evidence_text="统一社会信用代码 91330100MA2GX8RT7K，主营偏光膜材料",
        source_url="https://news.example.com/a",
    )

    assert AnchorMatch("credit_code", "91330100MA2GX8RT7K") in matches
    assert is_evidence_trusted(matches)


def test_company_own_domain_identifies_the_entity() -> None:
    matches = match_anchors(
        build_anchors(ENTITY),
        evidence_text="公司简介：专注功能性薄膜",
        source_url="https://ir.xinghai-materials.com/notice/2026",
    )

    assert any(match.kind == "domain" for match in matches)
    assert is_evidence_trusted(matches)


def test_a_bare_name_hit_is_not_enough_to_trust_the_page() -> None:
    """同名公司是常态：只凭名字命中就采信，是调研污染数据的头号原因。"""
    matches = match_anchors(
        build_anchors(ENTITY),
        evidence_text="杭州星海新材料股份有限公司获评行业前三",
        source_url="https://unknown-media.example.com/x",
    )

    assert {match.kind for match in matches} == {"name"}
    assert not is_evidence_trusted(matches)


def test_name_plus_legal_person_is_enough() -> None:
    matches = match_anchors(
        build_anchors(ENTITY),
        evidence_text="杭州星海新材料股份有限公司，法定代表人陈立，主营偏光膜",
        source_url="https://unknown-media.example.com/x",
    )

    assert is_evidence_trusted(matches)


def test_unrelated_page_matches_nothing() -> None:
    matches = match_anchors(
        build_anchors(ENTITY),
        evidence_text="某新材料企业完成 B 轮融资",
        source_url="https://other.example.com",
    )

    assert matches == []
    assert not is_evidence_trusted(matches)


def test_html_to_text_strips_scripts_and_collapses_whitespace() -> None:
    html = """
    <html><head><style>.a{color:red}</style><script>var x=1;</script></head>
    <body><h1>公司简介</h1><p>主营&nbsp;偏光膜   材料</p></body></html>
    """

    text_value = html_to_text(html)

    assert "var x" not in text_value
    assert "color:red" not in text_value
    assert "公司简介" in text_value
    assert "主营 偏光膜 材料" in text_value
