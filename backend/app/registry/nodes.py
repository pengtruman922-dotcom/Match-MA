"""The single declaration of Match-MA's fixed AI node catalog.

The set of nodes, their types and their responsibilities are fixed by code.
The database only stores *configuration* for a catalog node (which model, which
parameters); it never decides whether a node exists.  A catalog entry with no
database row is "unconfigured", not "missing".

Every consumer -- the settings page, the health metrics, the job handlers --
derives node names, Chinese labels, node types and understudy relationships
from this module.  It deliberately contains no SQL and no transport code.

`tests/test_node_registry.py` guards the invariant that node-name literals do
not reappear anywhere else in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 业务域，只影响设置页的分组显示，不参与任何能力判断。
DOMAINS: tuple[str, ...] = ("target", "buyer", "recommendation", "common")

# active = 在用；retired = 已退役，设置页不显示，等待《退役 AI 节点与代码清除》单删除。
LIFECYCLES: tuple[str, ...] = ("active", "retired")

# 代跑关系的两种语义，二者的提示文案不能共用模板：
#   and  —— 同组节点必须全部就绪才生效，只配一个等于没配（买家两阶段）
#   solo —— 各自独立，配一个生效一个（推荐的两个方向深评）
UNDERSTUDY_KINDS: tuple[str, ...] = ("and", "solo")


@dataclass(frozen=True)
class NodeSpec:
    node_name: str
    label: str
    domain: str
    # 代码目录声明，数据库只是副本。它决定测试队列路由与设置页能力位，
    # 并且会落进 ai_trace.trace_type，所以不能靠名字猜。
    node_type: str
    description: str
    # handler 实际喂进来的业务数据，面向管理员的中文描述。
    # 与 prompt_variables 是两回事：OCR 没有 Prompt，但有附件输入。
    runtime_inputs: tuple[str, ...] = ()
    # 模板里可用的 {{ variable }}，与 handler 传入的 variables 字典一一对应。
    prompt_variables: tuple[str, ...] = ()
    prompt_required: bool = True
    # 本节点缺配置时替它干活的节点。
    understudy: str | None = None
    understudy_kind: str | None = None
    # 结构化运行参数。目录节点缺配置时由 upsert 端点据此建号，
    # 已有配置的节点以库里的值为准（这里只是「新建时长什么样」）。
    output_mode: str = "json"
    response_format: str | None = "json_object"
    default_temperature: float | None = 0.1
    default_top_p: float | None = 0.9
    default_timeout_seconds: int = 120
    lifecycle: str = "active"
    sort_order: int = 0
    # 推荐方向专属节点的方向标识（buyer_to_target / target_to_buyer）。
    # 只有方向深评节点有值，运行时据此选节点。
    recommendation_mode: str | None = None
    # 与本节点同属一个 "and" 组的其他节点；仅 understudy_kind == "and" 时有值。
    understudy_group: tuple[str, ...] = field(default_factory=tuple)


NODES: tuple[NodeSpec, ...] = (
    # ---- 标的 ----------------------------------------------------------
    NodeSpec(
        node_name="seller_target_parser",
        label="标的新建解析",
        domain="target",
        node_type="llm",
        description="从标的原始材料抽取结构化字段，产出待复核的 extracted_action。",
        runtime_inputs=("标的材料原文（含附件文本）", "标的已有字段上下文"),
        prompt_variables=("raw_target_text", "target_context_json"),
        default_timeout_seconds=90,
        sort_order=10,
    ),
    NodeSpec(
        node_name="seller_target_update_parser",
        label="标的更新解析",
        domain="target",
        node_type="llm",
        description="单标的更新场景的专用解析，只处理该标的的字段变更。",
        runtime_inputs=("用户录入原文（含附件文本）", "业务更新上下文"),
        prompt_variables=("raw_text", "context_json"),
        default_timeout_seconds=300,
        sort_order=20,
    ),
    NodeSpec(
        node_name="seller_target_researcher",
        label="标的 AI 调研",
        domain="target",
        node_type="research",
        description="联网调研标的公开信息，产出调研提案供人工复核。",
        runtime_inputs=("调研上下文（标的画像 + 搜索结果）",),
        prompt_variables=("research_context_json",),
        default_timeout_seconds=900,
        sort_order=30,
    ),
    NodeSpec(
        node_name="seller_target_research_mapper",
        label="调研结果规范化",
        domain="target",
        node_type="parser",
        description="把调研结果映射为标准字段，供人工复核后应用。",
        runtime_inputs=("调研产出与字段映射上下文",),
        prompt_variables=("mapping_context_json",),
        default_temperature=0.0,
        default_timeout_seconds=180,
        sort_order=40,
    ),
    # ---- 买家 ----------------------------------------------------------
    NodeSpec(
        node_name="buyer_intent_parser",
        label="买家新建解析",
        domain="buyer",
        node_type="llm",
        description=(
            "从买家原始材料一步抽取并规范化需求字段。"
            "两阶段节点未同时就绪时，由它替两者代跑。"
        ),
        runtime_inputs=("买家需求原文（含附件文本）", "买家画像上下文", "一级/二级行业字典（自动注入）"),
        prompt_variables=("raw_requirement_text", "buyer_profile_json", "industry_l1_list", "industry_l2_list"),
        default_timeout_seconds=300,
        sort_order=50,
    ),
    NodeSpec(
        node_name="buyer_intent_semantic_parser",
        label="买家需求语义解析",
        domain="buyer",
        node_type="llm",
        description="两阶段解析的第一步：理解原始材料并拆解公共条件、方案、条件作用和证据。",
        runtime_inputs=("买家需求原文（含附件文本）", "买家画像上下文"),
        prompt_variables=("raw_requirement_text", "buyer_profile_json"),
        understudy="buyer_intent_parser",
        understudy_kind="and",
        understudy_group=("buyer_intent_normalizer",),
        default_timeout_seconds=300,
        sort_order=60,
    ),
    NodeSpec(
        node_name="buyer_intent_normalizer",
        label="买家需求字段规范化",
        domain="buyer",
        node_type="llm",
        description="两阶段解析的第二步：结合字段契约、行业字典、行政区划和枚举规则校验标准化。",
        runtime_inputs=("语义解析阶段输出", "买家画像上下文", "字段契约与枚举规则", "行业字典 / 省级区划（自动注入）"),
        prompt_variables=(
            "semantic_parse_json",
            "buyer_profile_json",
            "field_contract_json",
            "industry_l1_list",
            "province_list",
            "enum_contract_json",
        ),
        understudy="buyer_intent_parser",
        understudy_kind="and",
        understudy_group=("buyer_intent_semantic_parser",),
        default_timeout_seconds=300,
        sort_order=70,
    ),
    NodeSpec(
        node_name="buyer_intent_update_parser",
        label="买家基本信息更新解析",
        domain="buyer",
        node_type="llm",
        description="单买家需求更新场景的专用解析，只处理该需求的字段变更。",
        runtime_inputs=("用户录入原文（含附件文本）", "业务更新上下文"),
        prompt_variables=("raw_text", "context_json"),
        default_timeout_seconds=300,
        sort_order=80,
    ),
    # ---- 推荐 ----------------------------------------------------------
    NodeSpec(
        node_name="recommendation_deep_eval",
        label="推荐深度评估",
        domain="recommendation",
        node_type="llm",
        description=(
            "对候选逐个深度评价并给出评级与理由。"
            "方向专属节点未配置时，由它替该方向代跑。"
        ),
        runtime_inputs=("推荐方向", "推荐对象条件与画像", "候选清单分片"),
        prompt_variables=("mode", "anchor_context", "candidates_json"),
        default_temperature=0.2,
        default_timeout_seconds=180,
        sort_order=90,
    ),
    NodeSpec(
        node_name="recommendation_deep_eval_to_target",
        label="推荐深评·为买家找标的",
        domain="recommendation",
        node_type="llm",
        description="固定买家需求，深度评价候选标的。",
        runtime_inputs=("推荐方向", "买家需求条件与画像", "候选标的清单分片"),
        prompt_variables=("mode", "anchor_context", "candidates_json"),
        understudy="recommendation_deep_eval",
        understudy_kind="solo",
        recommendation_mode="buyer_to_target",
        default_temperature=0.2,
        default_timeout_seconds=180,
        sort_order=100,
    ),
    NodeSpec(
        node_name="recommendation_deep_eval_to_buyer",
        label="推荐深评·为标的找买家",
        domain="recommendation",
        node_type="llm",
        description="固定标的画像，深度评价候选买家需求。",
        runtime_inputs=("推荐方向", "标的画像", "候选买家需求清单分片"),
        prompt_variables=("mode", "anchor_context", "candidates_json"),
        understudy="recommendation_deep_eval",
        understudy_kind="solo",
        recommendation_mode="target_to_buyer",
        default_temperature=0.2,
        default_timeout_seconds=180,
        sort_order=110,
    ),
    NodeSpec(
        node_name="recommendation_query_parser",
        label="推荐对话条件解析",
        domain="recommendation",
        node_type="parser",
        description=(
            "把推荐对话里的自然语言消息解析成条件覆盖。"
            "只负责抽取，重筛 / 重评 / 展示过滤 / 提问的路由由代码判定。"
        ),
        runtime_inputs=("推荐方向", "当前生效条件", "用户消息", "一级行业字典（自动注入）"),
        prompt_variables=("mode", "current_conditions_json", "industry_l1_list", "user_message"),
        default_timeout_seconds=30,
        sort_order=120,
    ),
    NodeSpec(
        node_name="recommendation_report_writer",
        label="推荐报告生成",
        domain="recommendation",
        node_type="llm",
        description="根据已选推荐项生成推荐报告正文。",
        runtime_inputs=("报告上下文（会话、已选项、画像）",),
        prompt_variables=("context_json",),
        output_mode="text",
        response_format=None,
        default_temperature=0.3,
        default_timeout_seconds=180,
        sort_order=130,
    ),
    # ---- 通用 ----------------------------------------------------------
    NodeSpec(
        node_name="ocr_attachment_parser",
        label="附件 OCR",
        domain="common",
        node_type="ocr",
        description="调用多模态模型识别附件内容，产出供后续解析使用的文本。",
        runtime_inputs=("附件文件（图片 / PDF 页）",),
        prompt_variables=(),
        prompt_required=False,
        output_mode="mixed",
        response_format=None,
        default_temperature=None,
        default_top_p=None,
        sort_order=140,
    ),
    NodeSpec(
        node_name="relation_followup_draft_parser",
        label="跟进整理",
        domain="common",
        node_type="parser",
        description=(
            "把跟进记录整理成沟通内容与下一步草稿。"
            "不识别或创建关系、不改推进状态、不选择动态类型。"
        ),
        runtime_inputs=("跟进原文（含附件文本）", "关系上下文"),
        prompt_variables=("raw_text", "relation_context_json"),
        default_temperature=0.0,
        default_timeout_seconds=90,
        sort_order=150,
    ),
    NodeSpec(
        node_name="business_update_extractor",
        label="混合更新兼容节点",
        domain="common",
        node_type="llm",
        description=(
            "业务更新的兜底解析：同时绑定标的与买家需求、或两者都未绑定时走这里。"
            "只绑定单个对象时由对应的专用更新解析节点处理。"
        ),
        runtime_inputs=("用户录入原文（含附件文本）", "业务更新上下文"),
        prompt_variables=("raw_text", "context_json"),
        default_timeout_seconds=300,
        sort_order=160,
    ),
    # ---- 已退役 --------------------------------------------------------
    # 设置页不显示。物理清除见《退役 AI 节点与代码清除》单；在那之前保留登记，
    # 以免它们变成「未登记节点」而重新出现在页面上。
    NodeSpec(
        node_name="embedding_seller_doc",
        label="标的文档向量",
        domain="target",
        node_type="embedding",
        description="标的检索文档的向量生成。随推荐 v3 退役，专用 worker 已下线。",
        prompt_required=False,
        lifecycle="retired",
        output_mode="embedding",
        response_format=None,
        default_temperature=None,
        default_top_p=None,
        default_timeout_seconds=60,
        sort_order=900,
    ),
    NodeSpec(
        node_name="embedding_buyer_intent",
        label="买家文档向量",
        domain="buyer",
        node_type="embedding",
        description="买家需求检索文档的向量生成。随推荐 v3 退役，专用 worker 已下线。",
        prompt_required=False,
        lifecycle="retired",
        output_mode="embedding",
        response_format=None,
        default_temperature=None,
        default_top_p=None,
        default_timeout_seconds=60,
        sort_order=910,
    ),
    NodeSpec(
        node_name="recommendation_reranker",
        label="候选重排",
        domain="recommendation",
        node_type="rerank",
        description="候选重排模型。随推荐 v3 退役，深评已取代它，专用 worker 已下线。",
        prompt_required=False,
        lifecycle="retired",
        response_format=None,
        default_temperature=None,
        default_top_p=None,
        default_timeout_seconds=90,
        sort_order=920,
    ),
)


# Prompt 模板变量的中文说明，设置页的变量面板直接渲染。
PROMPT_VARIABLE_LABELS: dict[str, str] = {
    "raw_target_text": "标的材料原文",
    "target_context_json": "标的上下文 JSON",
    "raw_text": "用户录入原文（含附件文本）",
    "context_json": "业务更新上下文 JSON",
    "research_context_json": "调研上下文 JSON",
    "mapping_context_json": "调研结果映射上下文 JSON",
    "relation_context_json": "撮合关系上下文 JSON",
    "raw_requirement_text": "买家需求原文",
    "buyer_profile_json": "买家画像 JSON",
    "semantic_parse_json": "语义解析阶段输出 JSON",
    "field_contract_json": "买家需求统一字段契约 JSON",
    "enum_contract_json": "结构化字段候选值规则 JSON",
    "industry_l1_list": "一级行业字典（渲染时自动注入当前启用清单）",
    "industry_l2_list": "二级行业字典（渲染时自动注入当前启用清单）",
    "province_list": "标准省级行政区划清单",
    "mode": "推荐方向（buyer_to_target / target_to_buyer）",
    "anchor_context": "推荐对象条件与画像文本",
    "candidates_json": "候选清单 JSON",
    "current_conditions_json": "当前生效的推荐条件 JSON",
    "user_message": "用户在推荐对话中输入的消息",
    "report_context_json": "报告上下文 JSON",
    "selected_items_json": "已选推荐项 JSON",
}


_BY_NAME: dict[str, NodeSpec] = {spec.node_name: spec for spec in NODES}


def all_nodes() -> tuple[NodeSpec, ...]:
    """完整目录，含已退役节点。"""
    return NODES


def active_nodes() -> tuple[NodeSpec, ...]:
    """设置页展示的目录，按 sort_order 排序。"""
    return tuple(sorted(
        (spec for spec in NODES if spec.lifecycle == "active"),
        key=lambda spec: spec.sort_order,
    ))


def node_by_name(node_name: str) -> NodeSpec | None:
    """未登记节点返回 None —— 调用方必须照常显示，不得据此过滤。"""
    return _BY_NAME.get(node_name)


def all_node_names() -> frozenset[str]:
    return frozenset(_BY_NAME)


def active_node_names() -> frozenset[str]:
    return frozenset(spec.node_name for spec in NODES if spec.lifecycle == "active")


def retired_node_names() -> frozenset[str]:
    return frozenset(spec.node_name for spec in NODES if spec.lifecycle == "retired")


def prompt_required_node_names() -> frozenset[str]:
    """需要发布默认 Prompt 才算就绪的在用节点。健康检查用它，不要再硬编码清单。"""
    return frozenset(
        spec.node_name for spec in NODES
        if spec.lifecycle == "active" and spec.prompt_required
    )


def must_configure_node_names() -> frozenset[str]:
    """必须自己配好模型与 Prompt，否则业务直接断的节点。

    健康检查用它。**排除有代跑节点的那批** —— 它们缺配置时由指定节点顶上，
    是设计允许的状态，算进来会把正常系统报成 degraded。
    """
    return frozenset(
        spec.node_name for spec in NODES
        if spec.lifecycle == "active" and spec.prompt_required and spec.understudy is None
    )


def understudy_nodes() -> tuple[NodeSpec, ...]:
    """有代跑关系的节点，即「代码已引用但可能未建配置」的那批。"""
    return tuple(spec for spec in NODES if spec.understudy is not None)


def buyer_intent_two_stage_node_names() -> tuple[str, ...]:
    """买家两阶段解析的节点，顺序即执行顺序（语义解析 → 字段规范化）。

    两个都就绪才走两阶段，否则整体由 buyer_intent_legacy_node_name() 代跑。
    """
    staged = sorted(
        (spec for spec in NODES if spec.domain == "buyer" and spec.understudy_kind == "and"),
        key=lambda spec: spec.sort_order,
    )
    return tuple(spec.node_name for spec in staged)


def buyer_intent_legacy_node_name() -> str:
    """两阶段未就绪时一步干完的节点。"""
    understudies = {
        spec.understudy for spec in NODES
        if spec.domain == "buyer" and spec.understudy_kind == "and" and spec.understudy
    }
    if len(understudies) != 1:
        raise ValueError(f"买家两阶段的代跑节点必须唯一，实际为 {sorted(understudies)}")
    return understudies.pop()


def buyer_parse_node_names() -> tuple[str, ...]:
    """买家需求解析链路涉及的全部节点，用于按 node_name 过滤 ai_trace。"""
    return (buyer_intent_legacy_node_name(), *buyer_intent_two_stage_node_names())


def deep_eval_node_by_mode() -> dict[str, str]:
    """推荐方向 → 方向专属深评节点。未配置时各自回落到共用深评节点。"""
    return {
        spec.recommendation_mode: spec.node_name
        for spec in NODES
        if spec.recommendation_mode
    }


def deep_eval_understudy_node_name() -> str:
    """方向深评节点未配置时的代跑目标。"""
    understudies = {
        spec.understudy for spec in NODES
        if spec.recommendation_mode and spec.understudy
    }
    if len(understudies) != 1:
        raise ValueError(f"方向深评的代跑节点必须唯一，实际为 {sorted(understudies)}")
    return understudies.pop()


def prompt_variable_label(name: str) -> str:
    return PROMPT_VARIABLE_LABELS.get(name, "")
