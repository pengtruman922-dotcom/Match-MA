from backend.app.services.profile_sections import (
    PROFILE_SECTIONS,
    PROFILE_SECTION_CODES,
    PROFILE_TOTAL_BUDGET,
    buyer_party_fact_block,
    load_profile_sections,
    normalize_profile_section_items,
    render_profile_text,
    upsert_profile_section,
)


def _section(code: str, content: str, status: str = "filled") -> dict:
    return {"section_code": code, "info_status": status, "content_text": content}


def test_every_section_has_a_budget_and_a_label() -> None:
    # 2026-08-07：tech_team 并入 business_product，后者改名「产业优势」并拿走
    # 两栏预算之和（400 + 300 → 600）。见 标的指标体系二轮施工单0807.md。
    assert len(PROFILE_SECTIONS) == 4
    assert PROFILE_TOTAL_BUDGET == 1500
    assert set(PROFILE_SECTION_CODES) == {
        "identity",
        "business_product",
        "ops_quality",
        "deal_terms",
    }


def test_render_budgets_each_section_instead_of_cutting_one_long_document() -> None:
    """按栏目分配预算：任何一栏写得再长，也不会把后面的栏目挤没。"""
    sections = {
        "business_product": _section("business_product", "业" * 900),
        "deal_terms": _section("deal_terms", "原股东拟出让 60%，接受产业买家"),
    }

    rendered = render_profile_text(sections)

    assert "【产业优势】" in rendered
    # 靠后的栏目仍然出现，不会因为前一栏超长被截断掉
    assert "【交易属性与出售诉求】原股东拟出让 60%，接受产业买家" in rendered
    assert "业" * 600 in rendered
    assert "业" * 601 not in rendered
    assert "…" in rendered


def test_render_keeps_section_order_stable() -> None:
    sections = {code: _section(code, f"{code} 内容") for code, _, _ in PROFILE_SECTIONS}

    lines = render_profile_text(sections).split("\n")

    assert [line.split("】")[0].lstrip("【") for line in lines] == [label for _, label, _ in PROFILE_SECTIONS]


def test_no_information_is_explicit_rather_than_an_empty_string() -> None:
    """深评必须分得清'没查到'和'不适用'——空字符串两者都表达不了。"""
    sections = {
        "business_product": _section("business_product", "", status="not_found"),
        "deal_terms": _section("deal_terms", "", status="not_applicable"),
    }

    rendered = render_profile_text(sections)

    assert "【产业优势】（暂无信息）" in rendered
    assert "【交易属性与出售诉求】（不适用）" in rendered


def test_render_returns_empty_when_no_sections_exist() -> None:
    assert render_profile_text(None) == ""
    assert render_profile_text({}) == ""


def _buyer_party_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "business_tags_json": ["储能系统", "充电桩"],
        "business_summary": "省属能源平台，主业为风光电站开发与运营。",
        "ownership_type": "state_owned",
        "listed_status": "listed",
        "listing_exchange": "sse",
        "stock_code": "600000",
        "location_province": "湖北省",
        "location_city": "武汉市",
        "location_district": None,
        "market_cap_yuan": 26_000_000_000,
        "market_cap_as_of": "2026-08-20",
        "valuation_yuan": None,
        "valuation_date": None,
        "current_revenue_yuan": 5_800_000_000,
        "current_operating_cash_flow_yuan": 420_000_000,
        "financial_period_label": "2025年度",
        "supplementary_summary": "存在一宗未决诉讼，金额约 3000 万元。",
    }
    row.update(overrides)
    return row


class _Db:
    statement = ""

    def __init__(self, row: dict[str, object] | None = None) -> None:
        self.row = row if row is not None else _buyer_party_row()

    def execute(self, statement, params):
        self.statement = str(statement)
        outer = self

        class _Result:
            def mappings(self):
                return self

            def one_or_none(self):
                return outer.row

        return _Result()


def test_buyer_party_block_carries_business_facts_without_identity() -> None:
    db = _Db()
    block = buyer_party_fact_block(db, "8ff4bc53-047c-47be-b9b8-a3c465a519a1")

    assert "主营业务：储能系统、充电桩" in block
    assert "省属能源平台" in block
    assert "企业性质：国企" in block
    assert "上市状态：已上市（上交所600000）" in block
    assert "所在地区：湖北省 武汉市" in block
    # 财务数字必须带时间：不知道哪天的市值判断不了「买得起吗」。
    assert "市值：260亿元，2026-08-20" in block
    assert "经营情况：营收 58亿元，经营现金流 4.2亿元（2025年度）" in block
    assert "补充信息：存在一宗未决诉讼" in block
    # 身份字段不进块：它服务于协同性判断，不用于指名买家
    assert "buyer_name" not in db.statement
    # 通讯录与运营备注也不进块：这个块是给模型判断产业协同的，不是通讯录
    assert "contact_name" not in db.statement
    assert "contact_info_json" not in db.statement
    assert "notes" not in db.statement


def test_market_value_shows_valuation_for_unlisted_buyers() -> None:
    """市值与估值是一个展示位：上市看市值，非上市看估值。"""
    db = _Db(
        _buyer_party_row(
            listed_status="unlisted",
            listing_exchange=None,
            stock_code=None,
            market_cap_yuan=None,
            market_cap_as_of=None,
            valuation_yuan=1_200_000_000,
            valuation_date="2025年一季度",
        )
    )
    block = buyer_party_fact_block(db, "8ff4bc53-047c-47be-b9b8-a3c465a519a1")

    assert "估值：12亿元，2025年一季度" in block
    assert "市值" not in block


def test_unknown_enums_are_treated_as_missing() -> None:
    """unknown 不是 null，但对「这里有没有信息」两者等价：不占深评预算。"""
    db = _Db(
        _buyer_party_row(
            ownership_type="unknown",
            listed_status="unknown",
            listing_exchange=None,
            stock_code=None,
            market_cap_yuan=None,
            market_cap_as_of=None,
        )
    )
    block = buyer_party_fact_block(db, "8ff4bc53-047c-47be-b9b8-a3c465a519a1")

    assert "企业性质" not in block
    assert "上市状态" not in block
    assert "主营业务：储能系统、充电桩" in block


def test_buyer_party_block_is_empty_without_a_party() -> None:
    assert buyer_party_fact_block(None, None) == ""


def test_profile_parser_rejects_unknown_duplicate_and_invalid_date_rows() -> None:
    sections, notes = normalize_profile_section_items(
        [
            {
                "section_code": "business_product",
                "content_text": "核心产品为实验室自动化设备",
                "as_of_date": "2026-07-21",
                "confidence": 1.2,
            },
            {"section_code": "business_product", "content_text": "重复内容"},
            {"section_code": "unknown", "content_text": "不应保留"},
            {"section_code": "ops_quality", "content_text": "客户集中度偏高", "as_of_date": "2026年"},
        ]
    )

    assert [item["section_code"] for item in sections] == ["business_product", "ops_quality"]
    assert "confidence" not in sections[0]
    assert sections[1]["as_of_date"] is None
    assert any("duplicate_section" in note for note in notes)
    assert any("unknown_section" in note for note in notes)
    assert any("invalid_as_of_date" in note for note in notes)


def test_a_retired_section_code_lands_in_its_successor() -> None:
    """老提示词还会发 tech_team —— 别名把它接到产业优势，而不是当成未知栏目丢掉。

    提示词是在设置页手工发布的，代码发版与提示词发布之间必然有一段错位期，
    这段时间里模型仍然按旧栏目输出。
    """
    sections, notes = normalize_profile_section_items(
        [{"section_code": "tech_team", "content_text": "光学镀膜年产能 1440 万套"}]
    )

    assert [item["section_code"] for item in sections] == ["business_product"]
    assert sections[0]["content_text"] == "光学镀膜年产能 1440 万套"
    assert not [note for note in notes if "unknown_section" in note]


class _RecordingDb:
    """Records statements instead of running them."""

    def __init__(self, returning: dict | None = None) -> None:
        self.statements: list[tuple[str, dict]] = []
        self._returning = returning or {"id": "row-1", "section_code": "business_product"}

    def execute(self, statement, params=None):
        self.statements.append((str(statement), dict(params or {})))
        outer = self

        class _Result:
            def mappings(self):
                return self

            def one(self):
                return outer._returning

            def all(self):
                return outer._returning if isinstance(outer._returning, list) else []

        return _Result()


def test_accepting_a_section_supersedes_the_current_revision() -> None:
    """接受即当前值。靠 as_of_date 排序决定当前值时，顾问点了「确认」而
    建议没带日期（或日期更早），界面会毫无反应——修改看起来丢失了。"""
    db = _RecordingDb()

    upsert_profile_section(
        db,
        entity_type="seller_target",
        entity_id="11111111-1111-1111-1111-111111111111",
        section_code="business_product",
        info_status="filled",
        content_text="核心团队来自某上市公司研发中心",
        review_status="accepted",
    )

    supersede = [item for item in db.statements if "deleted_at = now()" in item[0]]
    assert len(supersede) == 1
    assert "review_status in ('accepted', 'auto_accepted')" in supersede[0][0]
    assert supersede[0][1]["section_code"] == "business_product"
    assert any("insert into entity_profile_section" in item[0] for item in db.statements)


def test_current_revision_is_the_last_accepted_not_the_newest_dated() -> None:
    """调研给的 as_of_date 常常是网页发布时间而非事实时点，不能用它决定
    顾问看到哪一版。"""
    db = _RecordingDb(returning=[])

    load_profile_sections(db, entity_type="seller_target", entity_ids=["11111111-1111-1111-1111-111111111111"])

    statement = db.statements[0][0]
    # 表限定是必须的：select 里 updated_at 被 ::text 起了同名别名，
    # 裸列名会绑到输出别名上，把时序排序变成字典序。
    assert "order by entity_id, section_code, entity_profile_section.updated_at desc" in statement
    assert "as_of_date desc" not in statement


def test_loaded_sections_carry_dates_as_text_not_date_objects() -> None:
    """画像行会被原样塞进 JSONB 绑定（调研建议、ai_trace），
    一个 date 对象就能让整次 agent 运行回滚。"""
    db = _RecordingDb(returning=[])

    load_profile_sections(db, entity_type="seller_target", entity_ids=["11111111-1111-1111-1111-111111111111"])

    statement = db.statements[0][0]
    assert "as_of_date::text as as_of_date" in statement
    assert "updated_at::text as updated_at" in statement


def test_profile_parser_removes_cross_layer_deal_and_team_noise() -> None:
    sections, notes = normalize_profile_section_items(
        [
            {
                "section_code": "deal_terms",
                "content_text": "融资阶段为A++轮，融资规模5000万，产能落地可谈，接受迁址",
            },
            {
                "section_code": "business_product",
                "content_text": "移液技术100%自研；团队来自中航；股东包括某投资机构",
            },
        ]
    )

    assert sections[0]["content_text"] == "产能落地可谈；接受迁址"
    assert sections[1]["content_text"] == "移液技术100%自研；团队来自中航"
    assert len([note for note in notes if "removed_cross_layer_noise" in note]) == 2
