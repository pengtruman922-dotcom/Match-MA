-- Match-MA recommendation session condition overrides and query parser node
-- Purpose: store per-session condition overrides accumulated from the chat,
-- and provision the recommendation_query_parser LLM node (initial install;
-- later prompt versions are managed via the Settings UI, not migrations).

begin;

alter table recommendation_session
  add column if not exists condition_overrides_json jsonb not null default '{}'::jsonb;

-- Provision the query parser node by cloning the deep-eval node provider and
-- model so the parser follows whatever chat model the workspace already uses.
insert into model_node_config (
  id, team_id, workspace_id, node_name, node_type, provider_config_id,
  model_name, temperature, top_p, max_tokens, timeout_seconds,
  response_format, output_mode, embedding_dimension,
  is_active, is_default, created_by, metadata_json
)
select
  '00000000-0000-0000-0000-000000004110',
  n.team_id, n.workspace_id, 'recommendation_query_parser', 'parser', n.provider_config_id,
  n.model_name, 0.100, 0.900, 2048, 30,
  'json_object', 'json', null,
  true, true, '00000000-0000-0000-0000-000000000201',
  '{"purpose":"Parse chat messages into structured recommendation condition operations.","has_prompt":true,"queue_name":"sync"}'::jsonb
from model_node_config n
where n.node_name = 'recommendation_deep_eval'
  and n.is_default = true
on conflict (team_id, workspace_id, node_name) where is_default = true do update set
  node_type = excluded.node_type,
  temperature = excluded.temperature,
  top_p = excluded.top_p,
  max_tokens = excluded.max_tokens,
  timeout_seconds = excluded.timeout_seconds,
  response_format = excluded.response_format,
  output_mode = excluded.output_mode,
  is_active = excluded.is_active,
  metadata_json = excluded.metadata_json,
  updated_at = now();

insert into prompt_template (
  id, team_id, workspace_id, node_name, version, name, description,
  system_prompt, user_prompt_template, output_schema_json,
  few_shot_examples_json, template_engine, variables_json,
  is_active, is_default, created_by, metadata_json
)
values (
  '00000000-0000-0000-0000-000000004241',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000101',
  'recommendation_query_parser',
  'v0.1.0',
  '推荐条件解析',
  '把推荐会话中的用户消息解析成结构化条件操作、语义偏好、展示操作或提问。',
  '你负责解析并购撮合平台推荐会话里用户输入的一句话。只输出一个 JSON 对象，不要输出 Markdown。你的任务是提取，不是执行：把消息拆解为结构化条件操作、语义偏好、展示操作和提问，绝不能臆造用户没有表达的条件。无法可靠转成结构化条件的内容一律放进 semantic_preferences 原样保留。',
  '推荐方向：{{ mode }}（buyer_to_target 表示为买家意向筛选卖方标的；target_to_buyer 表示为标的匹配买家意向）

当前生效条件 JSON：
{{ current_conditions_json }}

一级行业封闭清单（industries_json 与 excluded_industries_json 的值必须来自该清单）：
{{ industry_l1_list }}

用户消息：
{{ user_message }}

按如下结构返回 JSON（各数组无内容时输出空数组，question 无内容时输出 null）：
{
  "condition_ops": [
    {"op": "set", "field": "region_scope_summary", "value": "浙江"},
    {"op": "set", "field": "min_net_profit_yuan", "value": 15000000},
    {"op": "remove", "field": "max_pe", "value": null},
    {"op": "exclude", "field": "excluded_industries_json", "value": "房地产与建筑"}
  ],
  "semantic_preferences": ["最好有出海业务"],
  "display_ops": [{"type": "only_grade", "value": "A"}],
  "question": null,
  "reply_summary": "已更新地区与净利润门槛"
}

规则：
1. op 只能取 set、remove、exclude。set 表示设置或替换条件值；remove 表示取消该条件（value 用 null）；exclude 只用于 excluded_industries_json，表示追加一个排除项。
2. field 只能使用以下字段名：industries_json、excluded_industries_json、region_scope_summary、min_net_profit_yuan、min_revenue_yuan、min_valuation_yuan、max_valuation_yuan、max_pe、min_market_cap_yuan、max_market_cap_yuan、requires_control、requires_consolidation、desired_equity_ratio_min、preferred_listed_status、max_debt_ratio。其他任何字段名都不允许。
3. 金额换算成人民币元的数字（如 1500万 输出 15000000，2亿 输出 200000000）。百分比输出数值（51% 输出 51）。
4. industries_json 的 set 操作输出完整替换后的数组，每个值必须从一级行业封闭清单原样复制；用户提到清单外的细分赛道时不要硬归类，放进 semantic_preferences。
5. requires_control 与 requires_consolidation 的值只能取 yes、no、unknown；preferred_listed_status 只能取 listed、unlisted、preparing_listing、pre_ipo、any、unknown。
6. "放宽/取消/不限"某条件时用 remove；给出新数值时用 set 替换。判断相对表述（如"利润放宽到1500万"）时参考当前生效条件 JSON。
7. display_ops 只在用户明确要求筛选当前展示结果时输出，type 只能取 only_grade（value 为 A、B 或 C）或 top_n（value 为数字）。
8. 用户在提问（如"对比第1和第3个""为什么推荐它"）时填入 question 原文；提问不产生 condition_ops。
9. reply_summary 用一句简洁中文概括本次解析出的变化；没有任何可执行内容时如实说明。
10. 只提取消息中明确表达的内容。与筛选无关的闲聊放进 question 或 reply_summary 说明，不要编造条件。',
  '{
    "type": "object",
    "required": ["condition_ops", "semantic_preferences"],
    "properties": {
      "condition_ops": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["op", "field"],
          "properties": {
            "op": {"type": "string", "enum": ["set", "remove", "exclude"]},
            "field": {"type": "string"},
            "value": {}
          }
        }
      },
      "semantic_preferences": {"type": "array", "items": {"type": "string"}},
      "display_ops": {"type": "array"},
      "question": {"type": ["string", "null"]},
      "reply_summary": {"type": ["string", "null"]}
    }
  }'::jsonb,
  '[]'::jsonb,
  'jinja',
  '["mode", "current_conditions_json", "industry_l1_list", "user_message"]'::jsonb,
  true,
  true,
  '00000000-0000-0000-0000-000000000201',
  '{"source":"migration_041_recommendation_condition_overrides"}'::jsonb
)
on conflict (team_id, workspace_id, node_name, version) do update set
  name = excluded.name,
  description = excluded.description,
  system_prompt = excluded.system_prompt,
  user_prompt_template = excluded.user_prompt_template,
  output_schema_json = excluded.output_schema_json,
  few_shot_examples_json = excluded.few_shot_examples_json,
  template_engine = excluded.template_engine,
  variables_json = excluded.variables_json,
  is_active = excluded.is_active,
  is_default = true,
  metadata_json = excluded.metadata_json,
  updated_at = now();

commit;
