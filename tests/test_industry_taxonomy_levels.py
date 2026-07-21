from backend.app.services.industry_taxonomy import (
    DEFAULT_L1_TERMS,
    classify_terms,
    industry_l1_prompt_list,
)

TERM_LEVELS = {
    "能源": ("l1", "能源"),
    "风电": ("l2", "能源"),
    "光伏": ("l2", "能源"),
    "新能源": ("l2", "能源"),
    "房地产与建筑": ("l1", "房地产与建筑"),
    "医药健康": ("alias", "医药与健康"),
}


def test_classify_terms_recovers_the_level_each_term_was_written_at() -> None:
    buckets = classify_terms(["风电", "房地产与建筑", "醋酸下游"], TERM_LEVELS)

    assert buckets["l1"] == ["房地产与建筑"]
    assert buckets["l2"] == ["风电"]
    # 字典里没有的产品级说法留给深评，不进 SQL 精确匹配
    assert buckets["unresolved"] == ["醋酸下游"]


def test_aliases_fall_through_to_descriptive_matching() -> None:
    """别名只告诉我们 L1 名字，拿它当赛道精确匹配会误判，交给描述文本兜底。"""
    buckets = classify_terms(["医药健康"], TERM_LEVELS)

    assert buckets["l1"] == []
    assert buckets["l2"] == []
    assert buckets["unresolved"] == ["医药健康"]


def test_classify_terms_deduplicates_and_ignores_blanks() -> None:
    buckets = classify_terms(["风电", "风电", "", None, "  "], TERM_LEVELS)

    assert buckets["l2"] == ["风电"]
    assert buckets["l1"] == []
    assert buckets["unresolved"] == []


def test_classify_terms_tolerates_non_list_input() -> None:
    assert classify_terms(None, TERM_LEVELS) == {"l1": [], "l2": [], "unresolved": []}


class _EmptyScalars:
    def scalars(self):
        return self

    def all(self) -> list[str]:
        return []


class _EmptyIndustryDb:
    def execute(self, _statement, _params):
        return _EmptyScalars()


def test_prompt_list_uses_full_canonical_fallback_when_dictionary_is_empty() -> None:
    assert industry_l1_prompt_list(_EmptyIndustryDb()) == "、".join(DEFAULT_L1_TERMS)
