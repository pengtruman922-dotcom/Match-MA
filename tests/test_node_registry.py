"""固定 AI 节点目录的守卫。

节点集合、类型、职责由 `backend/app/registry/nodes.py` 固定。本文件保证：
1. 目录本身自洽（标签、类型、代跑关系）；
2. 目录与运行时常量一致；
3. 节点名字面量不在目录之外重新扩散 —— 这是「规范化」不会在半年后重新腐坏的
   唯一机制。历史教训：meta.py 里两处硬编码的 8 节点清单在无人察觉的情况下
   系统性低报了指标，正是因为没有任何东西比对它们和真实节点集。
"""

from __future__ import annotations

import pathlib
import re

import pytest

from backend.app.api.routes.model_config import NODE_TYPES
from backend.app.jobs.handlers.recommendation import (
    DEEP_EVAL_FALLBACK_NODE,
    DEEP_EVAL_NODE_BY_MODE,
)
from backend.app.registry.nodes import (
    DOMAINS,
    LIFECYCLES,
    NODES,
    PROMPT_VARIABLE_LABELS,
    UNDERSTUDY_KINDS,
    active_node_names,
    all_node_names,
    must_configure_node_names,
    node_by_name,
    prompt_required_node_names,
    report_writer_node_by_type,
    retired_node_names,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# 2026-07-31 生产实测：model_node_config 的 15 条记录 + 代码已引用但尚未建配置的 4 个。
# 目录是固定的，新增节点必须同时改这里 —— 这正是「节点由代码决定」的落点。
EXPECTED_NODE_NAMES = frozenset({
    "seller_target_parser",
    "seller_target_update_parser",
    "seller_target_researcher",
    "seller_target_research_mapper",
    "buyer_intent_parser",
    "buyer_intent_semantic_parser",
    "buyer_intent_normalizer",
    "buyer_intent_update_parser",
    "recommendation_deep_eval",
    "recommendation_deep_eval_to_target",
    "recommendation_deep_eval_to_buyer",
    "recommendation_agent_to_target",
    "recommendation_answer_writer_to_target",
    "recommendation_query_parser",
    "recommendation_target_report_writer",
    "recommendation_buyer_report_writer",
    "recommendation_report_writer",
    "ocr_attachment_parser",
    "relation_followup_draft_parser",
    "business_update_extractor",
    "embedding_seller_doc",
    "embedding_buyer_intent",
    "recommendation_reranker",
})

EXPECTED_RETIRED = frozenset({
    "recommendation_report_writer",
    "embedding_seller_doc",
    "embedding_buyer_intent",
    "recommendation_reranker",
})


def test_registry_covers_the_fixed_catalog() -> None:
    assert all_node_names() == EXPECTED_NODE_NAMES
    assert retired_node_names() == EXPECTED_RETIRED
    assert len(NODES) == len(EXPECTED_NODE_NAMES), "节点名重复"


@pytest.mark.parametrize("spec", NODES, ids=lambda spec: spec.node_name)
def test_every_node_has_a_chinese_label(spec) -> None:
    # 直接防住「设置页显示裸英文名」这类回归。
    assert spec.label.strip()
    assert any(ord(ch) > 0x7F for ch in spec.label), f"{spec.node_name} 的 label 没有中文"
    assert spec.description.strip()


@pytest.mark.parametrize("spec", NODES, ids=lambda spec: spec.node_name)
def test_node_enum_fields_are_in_range(spec) -> None:
    assert spec.domain in DOMAINS
    assert spec.lifecycle in LIFECYCLES
    assert spec.node_type in NODE_TYPES


@pytest.mark.parametrize("spec", NODES, ids=lambda spec: spec.node_name)
def test_understudy_references_resolve(spec) -> None:
    if spec.understudy is None:
        assert spec.understudy_kind is None
        assert spec.understudy_group == ()
        return
    assert node_by_name(spec.understudy) is not None, "代跑节点必须也在目录内"
    assert spec.understudy_kind in UNDERSTUDY_KINDS
    for sibling in spec.understudy_group:
        assert node_by_name(sibling) is not None
        assert sibling != spec.node_name


def test_and_group_is_symmetric() -> None:
    # "and" 组必须互相声明，否则设置页会对其中一个说错话
    # （只配一个等于没配，两个节点的提示必须一致）。
    for spec in NODES:
        if spec.understudy_kind != "and":
            continue
        assert spec.understudy_group, f"{spec.node_name} 声明了 and 关系却没有同组节点"
        for sibling_name in spec.understudy_group:
            sibling = node_by_name(sibling_name)
            assert sibling is not None
            assert sibling.understudy_kind == "and"
            assert sibling.understudy == spec.understudy
            assert spec.node_name in sibling.understudy_group


def test_deep_eval_mode_keys_match_the_runtime_contract() -> None:
    """方向标识写错会让深评静默退回共用节点 —— 这里把契约钉死。

    recommendation.py 的 DEEP_EVAL_NODE_BY_MODE 现在派生自注册表，所以不能再
    拿它俩互相比对；改为断言方向取值本身，一个拼写错误就会被抓住。
    """
    assert set(DEEP_EVAL_NODE_BY_MODE) == {"buyer_to_target", "target_to_buyer"}
    directional = {
        spec.node_name for spec in NODES
        if spec.understudy_kind == "solo" and spec.understudy == DEEP_EVAL_FALLBACK_NODE
    }
    assert directional == set(DEEP_EVAL_NODE_BY_MODE.values())
    assert node_by_name(DEEP_EVAL_FALLBACK_NODE) is not None
    for spec in NODES:
        if spec.recommendation_mode:
            assert spec.understudy_kind == "solo", "方向节点必须是独立代跑，不是 and 组"


def test_report_types_route_to_two_dedicated_nodes() -> None:
    assert report_writer_node_by_type() == {
        "buyer_facing_target_report": "recommendation_target_report_writer",
        "seller_facing_buyer_report": "recommendation_buyer_report_writer",
    }


def test_prompt_variables_have_labels() -> None:
    missing = {
        (spec.node_name, name)
        for spec in NODES
        for name in spec.prompt_variables
        if name not in PROMPT_VARIABLE_LABELS
    }
    assert not missing, f"变量缺中文说明：{sorted(missing)}"


def test_nodes_without_prompt_declare_no_variables() -> None:
    for spec in NODES:
        if not spec.prompt_required:
            assert spec.prompt_variables == (), f"{spec.node_name} 不需要 Prompt 却声明了变量"


def test_prompt_required_covers_active_llm_nodes() -> None:
    # 这个集合是 meta.py 健康检查的数据源。收编前它硬编码了 8 个节点，
    # 漏掉 recommendation_query_parser / seller_target_researcher /
    # seller_target_research_mapper，导致指标长期低报。
    required = prompt_required_node_names()
    assert required <= active_node_names()
    assert "recommendation_query_parser" in required
    assert "seller_target_researcher" in required
    assert "seller_target_research_mapper" in required
    assert "ocr_attachment_parser" not in required


def test_must_configure_excludes_nodes_that_have_an_understudy() -> None:
    """健康检查的口径：有代跑节点的那批不算必配，否则会把正常系统报成 degraded。"""
    required = must_configure_node_names()
    assert required <= prompt_required_node_names()
    for spec in NODES:
        if spec.understudy is not None:
            assert spec.node_name not in required
    # 旧共用报告节点退役、两个专属报告节点接替，必配总数净增 1；
    # 推荐 Agent 与回答撰写各一个正向节点，且刻意没有代跑，再净增 2。
    assert len(required) == 14
    assert "buyer_intent_semantic_parser" not in required
    assert "recommendation_deep_eval_to_target" not in required
    assert "recommendation_deep_eval" in required


# ---------------------------------------------------------------------------
# 字面量守卫
# ---------------------------------------------------------------------------

SCAN_ROOTS = ("backend/app", "frontend/src")
SCAN_SUFFIXES = {".py", ".ts", ".tsx"}
REGISTRY_PATH = "backend/app/registry/nodes.py"

# 当前仍在目录之外出现节点名字面量的文件。**只允许删除条目，不允许新增。**
# 新增节点或新写节点名时，请从 registry/nodes.py 引用常量，不要往这里加行。
#
# 标注含义：
#   [收编] 属于本轮要收编的目录知识（清单 / 标签 / 代跑映射）
#   [自称] handler 引用自己的节点名，不构成重复的目录知识，暂不收编
#   [路由] 分发器列举它路由到的节点，同样只此一处
#   [数据] 持久化到库里的溯源标签，恰好与节点名同字符串，改了会与历史数据对不上
#   [退役] 随《退役 AI 节点与代码清除》单一并处理
KNOWN_LITERAL_SITES: dict[str, frozenset[str]] = {
    # [自称] 三处针对单个节点的健康检查（深评 / OCR / 业务更新兜底 prompt）。
    # 原来还有三份清单式的硬编码（必配节点 ×2、退役节点 ×1），已收编进注册表。
    "backend/app/api/routes/meta.py": frozenset({
        "business_update_extractor", "ocr_attachment_parser", "recommendation_deep_eval",
    }),
    # [路由] 业务更新按绑定对象三选一。这三个名字全仓库只出现在这里，
    # 不构成重复的目录知识；换成常量只是多一层间接，不产生保障。
    "backend/app/jobs/handlers/business_update.py": frozenset({
        "business_update_extractor", "buyer_intent_update_parser", "seller_target_update_parser",
    }),
    # [数据] parsed_requirement_json 的 source 溯源标签，写进买家需求存量数据。
    # 它不是节点引用 —— 换成注册表调用会改变已落库的字符串语义。
    "backend/app/jobs/handlers/buyer_intent_parse.py": frozenset({"buyer_intent_parser"}),
    # [自称] handler / service 引用自己那一个节点
    "backend/app/api/routes/background_jobs.py": frozenset({"recommendation_deep_eval"}),
    "backend/app/api/routes/seller_targets.py": frozenset({"seller_target_parser"}),
    "backend/app/jobs/handlers/attachment_ocr.py": frozenset({"ocr_attachment_parser"}),
    "backend/app/jobs/handlers/dispatch.py": frozenset({"recommendation_deep_eval"}),
    "backend/app/jobs/handlers/relation_followup.py": frozenset({"relation_followup_draft_parser"}),
    "backend/app/jobs/handlers/seller_target_parse.py": frozenset({"seller_target_parser"}),
    "backend/app/services/recommendation_conditions.py": frozenset({"recommendation_query_parser"}),
    "backend/app/services/recommendation_flow.py": frozenset({"recommendation_deep_eval"}),
    "backend/app/jobs/handlers/research.py": frozenset({
        "seller_target_research_mapper", "seller_target_researcher",
    }),
    # [自称] trace 写入时把 node_name 写死在 INSERT 里。
    # recommendation_reranker 是特例：每次深评都会写一条挂着这个名字的 trace，
    # 实际干活的是深评 LLM —— 见《退役 AI 节点与代码清除》单。
    "backend/app/jobs/handlers/traces.py": frozenset({
        "business_update_extractor", "buyer_intent_parser", "recommendation_reranker",
        "seller_target_parser",
    }),
    # [退役] 随退役清除单处理
    "backend/app/jobs/handlers/search_embedding.py": frozenset({
        "embedding_buyer_intent", "embedding_seller_doc",
    }),
}


def _scan_node_name_literals() -> dict[str, frozenset[str]]:
    names = all_node_names()
    found: dict[str, frozenset[str]] = {}
    for root in SCAN_ROOTS:
        for path in (REPO_ROOT / root).rglob("*"):
            if path.suffix not in SCAN_SUFFIXES or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative == REGISTRY_PATH:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = {name for name in names if re.search(rf"""['"]{re.escape(name)}['"]""", text)}
            if hits:
                found[relative] = frozenset(hits)
    return found


def test_node_name_literals_do_not_spread() -> None:
    """精确棘轮：扫描结果必须与 KNOWN_LITERAL_SITES 完全相等。

    多出来 = 有人在目录之外新写了节点名，改从 registry/nodes.py 引用。
    少了 = 已经收编完成，请同步删掉对应条目（保持棘轮不腐坏）。
    """
    actual = _scan_node_name_literals()

    new_files = sorted(set(actual) - set(KNOWN_LITERAL_SITES))
    assert not new_files, (
        f"这些文件新引入了节点名字面量，请改从 backend/app/registry/nodes.py 引用：{new_files}"
    )

    cleaned_files = sorted(set(KNOWN_LITERAL_SITES) - set(actual))
    assert not cleaned_files, (
        f"这些文件已经不含节点名字面量，请从 KNOWN_LITERAL_SITES 删除：{cleaned_files}"
    )

    for relative in sorted(actual):
        added = sorted(actual[relative] - KNOWN_LITERAL_SITES[relative])
        removed = sorted(KNOWN_LITERAL_SITES[relative] - actual[relative])
        assert not added, f"{relative} 新增了节点名字面量：{added}"
        assert not removed, f"{relative} 已收编 {removed}，请同步更新 KNOWN_LITERAL_SITES"
