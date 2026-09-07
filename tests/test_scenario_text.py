"""多方案「其他要求」的输出层去重（2026-09-07）。

守的是两条：只有**每个**方案都有的句子才被提出来；提出来的句子不能在方案里再出现一遍。
"""

from backend.app.services.scenario_text import (
    dedupe_scenario_requirements,
    split_requirement_sentences,
)

NANNING_LISTED = (
    "1. 地域偏好：长江以南优先。\n"
    "2. 股权与控制：要求实控权（股权比例、决策权比例），能够实现并表。\n"
    "3. 交易方式：老股转让、定增。\n"
    "4. 风险容忍：不接受标的公司有重大风险（涉诉、冻结、执行、违规违法）。\n"
    "5. 溢价：接受 20% 以内溢价，要求经营稳定无退市风险。"
)
NANNING_UNLISTED = (
    "1. 地域偏好：长江以南优先。\n"
    "2. 股权与控制：要求实控权（股权比例、决策权比例），能够实现并表。\n"
    "3. 交易方式：老股转让、定增。\n"
    "4. 风险容忍：不接受标的公司有重大风险（涉诉、冻结、执行、违规违法）。\n"
    "5. 经营稳定可自我平衡。"
)


def test_sentences_shared_by_every_scenario_are_hoisted_once() -> None:
    shared, remaining = dedupe_scenario_requirements([NANNING_LISTED, NANNING_UNLISTED])

    assert shared == [
        "地域偏好：长江以南优先",
        "股权与控制：要求实控权（股权比例、决策权比例），能够实现并表",
        "交易方式：老股转让、定增",
        "风险容忍：不接受标的公司有重大风险（涉诉、冻结、执行、违规违法）",
    ]
    assert remaining == ["溢价：接受 20% 以内溢价，要求经营稳定无退市风险", "经营稳定可自我平衡"]


def test_a_sentence_missing_from_one_scenario_stays_in_the_others() -> None:
    """三个方案里两个写了「控股并表优先」、一个没写 —— 那不是共同要求。"""
    shared, remaining = dedupe_scenario_requirements(
        ["控股并表优先；保留管理团队", "控股并表优先；保留管理团队", "保留管理团队"]
    )

    assert shared == ["保留管理团队"]
    assert remaining == ["控股并表优先", "控股并表优先", None]


def test_single_scenario_and_empty_scenarios_are_left_alone() -> None:
    assert dedupe_scenario_requirements(["控股并表优先"]) == ([], ["控股并表优先"])
    assert dedupe_scenario_requirements([]) == ([], [])
    # 有一个方案没写其他要求，就没有「各方案都有」这回事，什么都不提。
    assert dedupe_scenario_requirements(["控股并表优先", None]) == ([], ["控股并表优先", None])


def test_numbering_and_punctuation_do_not_break_the_comparison() -> None:
    """同一句话一个方案写「1. 」序号、另一个写「（一）」，比对时都要认成同一句。"""
    shared, _ = dedupe_scenario_requirements(["1. 要求控股并表。", "（一）要求控股、并表"])

    assert shared == ["要求控股并表"]


def test_split_keeps_the_sentence_text_without_its_number() -> None:
    assert split_requirement_sentences("1. 地域：广东优先；2、上市优先\n三、可接受溢价") == [
        "地域：广东优先",
        "上市优先",
        "可接受溢价",
    ]
