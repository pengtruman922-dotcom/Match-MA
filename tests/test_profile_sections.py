from backend.app.services.profile_sections import (
    PROFILE_SECTIONS,
    PROFILE_SECTION_CODES,
    PROFILE_TOTAL_BUDGET,
    buyer_party_fact_block,
    profile_coverage,
    render_profile_text,
)


def _section(code: str, content: str, status: str = "filled") -> dict:
    return {"section_code": code, "info_status": status, "content_text": content}


def test_every_section_has_a_budget_and_a_label() -> None:
    assert len(PROFILE_SECTIONS) == 6
    assert PROFILE_TOTAL_BUDGET == 1900
    assert set(PROFILE_SECTION_CODES) == {
        "business_product",
        "chain_position",
        "tech_team",
        "ops_quality",
        "deal_terms",
        "sell_intent_risk",
    }


def test_render_budgets_each_section_instead_of_cutting_one_long_document() -> None:
    """按栏目分配预算：任何一栏写得再长，也不会把后面的栏目挤没。"""
    sections = {
        "business_product": _section("business_product", "业" * 900),
        "sell_intent_risk": _section("sell_intent_risk", "原股东拟出让 60%，接受产业买家"),
    }

    rendered = render_profile_text(sections)

    assert "【业务与产品】" in rendered
    # 靠后的栏目仍然出现，不会因为前一栏超长被截断掉
    assert "【出售诉求与风险缺口】原股东拟出让 60%，接受产业买家" in rendered
    assert "业" * 400 in rendered
    assert "业" * 401 not in rendered
    assert "…" in rendered


def test_render_keeps_section_order_stable() -> None:
    sections = {code: _section(code, f"{code} 内容") for code, _, _ in PROFILE_SECTIONS}

    lines = render_profile_text(sections).split("\n")

    assert [line.split("】")[0].lstrip("【") for line in lines] == [label for _, label, _ in PROFILE_SECTIONS]


def test_no_information_is_explicit_rather_than_an_empty_string() -> None:
    """深评必须分得清'没查到'和'不适用'——空字符串两者都表达不了。"""
    sections = {
        "tech_team": _section("tech_team", "", status="not_found"),
        "deal_terms": _section("deal_terms", "", status="not_applicable"),
    }

    rendered = render_profile_text(sections)

    assert "【技术与团队能力】（暂无信息）" in rendered
    assert "【交易属性与配合度】（不适用）" in rendered


def test_render_returns_empty_when_no_sections_exist() -> None:
    assert render_profile_text(None) == ""
    assert render_profile_text({}) == ""


def test_coverage_reports_missing_sections_as_research_input() -> None:
    sections = {
        "business_product": _section("business_product", "醋酸下游精细化工"),
        "tech_team": _section("tech_team", "", status="not_found"),
        "deal_terms": _section("deal_terms", "", status="not_applicable"),
    }

    coverage = profile_coverage(sections)

    assert coverage["filled_sections"] == ["业务与产品"]
    # not_applicable 不算缺口；not_found 与完全没写都算
    assert "技术与团队能力" in coverage["missing_sections"]
    assert "产业链位置与行业地位" in coverage["missing_sections"]
    assert "交易属性与配合度" not in coverage["missing_sections"]


def test_buyer_party_block_carries_business_facts_without_identity() -> None:
    class _Result:
        def mappings(self):
            return self

        def one_or_none(self):
            return {
                "buyer_type": "地方国企",
                "group_name": "某产业集团",
                "region_province": "湖北省",
                "main_business": "城市燃气与综合能源服务",
                "capital_strength_summary": "年投资规模 50 亿",
                "profile_summary": "已布局储能、充电桩",
            }

    class _Db:
        statement = ""

        def execute(self, statement, params):
            self.statement = str(statement)
            return _Result()

    db = _Db()
    block = buyer_party_fact_block(db, "8ff4bc53-047c-47be-b9b8-a3c465a519a1")

    assert "现有主业：城市燃气与综合能源服务" in block
    assert "产业布局：已布局储能、充电桩" in block
    # 身份字段不进块：它服务于协同性判断，不用于指名买家
    assert "buyer_name" not in db.statement
    assert "legal_name" not in db.statement


def test_buyer_party_block_is_empty_without_a_party() -> None:
    assert buyer_party_fact_block(None, None) == ""
