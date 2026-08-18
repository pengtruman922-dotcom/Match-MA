"""发布 `recommendation_agent_to_target` v0.2.0（4B 受控编排 + 深评回灌）。

Prompt 走 API，不写数据库迁移。默认只做本地或只读检查；只有显式 `--apply`
才会创建/启用版本。必须从仓库根目录运行，token 读取 `.match-ma-local-auth.json`。
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
for path in (str(REPO_ROOT), str(SCRIPT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from prompt_publish_utils import (  # noqa: E402
    PromptVersionConflict,
    ensure_prompt_version_compatible,
    validate_prompt_contract,
    validate_render_preview,
)

API_BASE = "https://match-ma-production.up.railway.app/api/v1"
NODE_NAME = "recommendation_agent_to_target"
VERSION = "v0.2.0"


SYSTEM_PROMPT = """你是 Match-MA 的推荐编排 Agent，为买家寻找标的。

你只负责编排，不重新解析需求、不接触全库、不重算数据库事实：

- 当前需求的唯一结构化基线是 `intent_snapshot`；可调用的组和 `group_id` 只来自 `search_group_catalog`。
- `search_targets` 执行纯 SQL 初筛；你根据真实召回量和 `excluded_by_condition` 决定是否放宽。
- `deep_evaluate_candidates` 对全部真实批次的去重候选池做一次定性深评；它是最终收尾前的必经工具。
- 名称、金额、比例等事实由代码回填。你不能编造 id、数字或候选。

只在完成工具编排后输出一个 JSON 对象，不要 Markdown、不要代码块。"""


USER_PROMPT_TEMPLATE = """# 本轮编排上下文

{{ recommendation_context_json }}

# 最近 5 轮已完成对话

{{ history_context }}

# 硬规则

1. **只读当前快照。** 不从用户原话或历史重新发明结构化条件。`parser_status` 非 ok 时只能使用 `fallback-0` 空组做无条件初筛，或在确实无法收敛时 `ask_user`。
2. **每组先完整真实筛。** 每个 group 的第一次 `count_only=false` 调用必须带上该组全部 required + preferred 条件。`group_id` 必须用目录中的值，不同组不得拼接。
3. `count_only=true` 只做试探，不会形成候选，也不能替代每组的第一次完整真实筛。
4. 召回不足时先看 `excluded_by_condition`，优先移除 preferred。required 通常保留；只有此前同组真实召回过少且你能引用该调用时才考虑放宽。
5. 放宽调用必须给 `relaxation_reason` 与 `based_on_call_index`。数值下限只能降低，上限只能提高；枚举、能力、行业、地区只能保留原值或整项移除，不能换成快照外的新值。
6. 排除行业与重大风险由代码强制注入，永不放宽。不要尝试删除、缩小或换值。
7. 每次 SQL 都独立返回该条件下真实前 20；不要要求排除前批 id。全部非 count_only 批次由代码在深评前按 id 求并集，最多 40 家并跨 group 公平收口。
8. 形成真实候选后必须调用一次 `deep_evaluate_candidates`。调用后筛选冻结，不再调用 `search_targets` 或 `get_target_detail`。
9. `deep_eval_status=ok` 时，重点与备选的 id 只能来自 `ranked`，绝不能来自 `dropped` 或候选池外。先读逐条定性判定、风险、信息缺口和筛选来源，再选重点/备选/追问建议。
10. `deep_eval_status=unavailable` 或 `schema_mismatch` 时不中断本轮，也不要伪装成 ok；明确写出降级，可依据 SQL 初筛顺序收尾。
11. `group_hit_count` 表示命中过几个不同需求组，是强信号；`search_hit_count` 只表示同一或不同策略中重复出现，不能冒充多方案命中。
12. 放宽 required 才出现的候选必须如实写“放宽补充/需核实/仅供参考”，不得宣称满足原 required。

# 最终 JSON（只有看过深评结果后才输出）

{
  "understanding": "一句话复述当前需求，不编数字",
  "deep_eval_status": "ok | unavailable | schema_mismatch",
  "recommended": [
    {
      "id": "来自 ranked（降级时来自真实候选池）",
      "reason_points": ["定性选择理由，最多 5 条"],
      "watch_out": "风险、信息缺口或放宽状态"
    }
  ],
  "runner_ups": [
    {
      "id": "来自 ranked（降级时来自真实候选池）",
      "name": "候选清单中的名称",
      "note": "为什么作为备选"
    }
  ],
  "follow_up_suggestions": ["下一轮可直接发送的短句"]
}

本包还不做最终 3–6 家的代码归一；不要为了凑固定数量从 dropped 捞回候选，也不要把深评机械截成前 5。"""


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["understanding", "deep_eval_status", "recommended", "runner_ups", "follow_up_suggestions"],
    "properties": {
        "understanding": {"type": ["string", "null"]},
        "deep_eval_status": {
            "type": "string",
            "enum": ["ok", "unavailable", "schema_mismatch"],
        },
        "recommended": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "reason_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "watch_out": {"type": ["string", "null"]},
                },
            },
        },
        "runner_ups": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": ["string", "null"]},
                    "note": {"type": ["string", "null"]},
                },
            },
        },
        "follow_up_suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 4,
        },
    },
}

EXPECTED_VARIABLES = validate_prompt_contract(
    node_name=NODE_NAME,
    system_prompt=SYSTEM_PROMPT,
    user_prompt_template=USER_PROMPT_TEMPLATE,
)


def ensure_existing_version_compatible(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return ensure_prompt_version_compatible(
        rows,
        version=VERSION,
        system_prompt=SYSTEM_PROMPT,
        user_prompt_template=USER_PROMPT_TEMPLATE,
        output_schema=OUTPUT_SCHEMA,
        variables=EXPECTED_VARIABLES,
    )


def _api_client():
    import match_ma_api_tools as api

    return api


def _payload() -> dict[str, Any]:
    return {
        "node_name": NODE_NAME,
        "version": VERSION,
        "name": "推荐编排 Agent·为买家找标的 v0.2.0（受控筛选 + 深评回灌）",
        "description": "4B：只读需求快照，分组完整初筛，依据真实信号放宽，深评后收尾。",
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt_template": USER_PROMPT_TEMPLATE,
        "output_schema_json": OUTPUT_SCHEMA,
        "variables_json": list(EXPECTED_VARIABLES),
        "is_active": True,
        "is_default": True,
        "metadata_json": {"source": "scripts/publish_recommendation_agent_v020_prompt.py"},
    }


def _run(args: argparse.Namespace) -> None:
    print(f"[OK] 本地变量集合与 NodeSpec 一致：{list(EXPECTED_VARIABLES)}")
    if args.check:
        print(f"[check] {NODE_NAME} {VERSION}；未访问 API，未 apply")
        return
    api = _api_client()
    token = api._resolve_token(args.api_base)
    if args.render_preview:
        preview = api._request_json(
            args.api_base,
            "POST",
            "/model-config/prompts/render-preview",
            token=token,
            json_body={"system_prompt": SYSTEM_PROMPT, "user_prompt_template": USER_PROMPT_TEMPLATE},
        )
        rendered_system, rendered_user = validate_render_preview(
            preview,
            expected_variables=EXPECTED_VARIABLES,
        )
        print(f"[OK] render-preview 已替换全部 {len(EXPECTED_VARIABLES)} 个双花括号变量")
        print((rendered_system + "\n" + rendered_user)[:1200])
        print("[render-preview] 只读渲染完成；未 apply")
        return
    rows = api._request_json(
        args.api_base,
        "GET",
        "/model-config/prompts",
        token=token,
        query={"node_name": NODE_NAME, "include_inactive": "true"},
    )
    existing = ensure_existing_version_compatible(rows if isinstance(rows, list) else rows.get("items", []))
    if existing is not None:
        print(f"[exists-identical] {NODE_NAME} {VERSION} 正文/schema/变量一致，不会重复创建")
        if args.apply and (not existing.get("is_active") or not existing.get("is_default")):
            updated = api._request_json(
                args.api_base,
                "PATCH",
                f"/model-config/prompts/{existing['id']}",
                token=token,
                json_body={"is_active": True, "is_default": True},
            )
            print(f"[activated] id={updated.get('id')}")
        else:
            print("[no-op] 未改生产 Prompt")
        return
    if args.dry_run:
        print(f"[dry-run] {NODE_NAME}: 将创建 {VERSION} 并设为默认；未 apply")
        return
    created = api._request_json(
        args.api_base,
        "POST",
        "/model-config/prompts",
        token=token,
        json_body=_payload(),
    )
    print(f"[created] {NODE_NAME} {VERSION} id={created.get('id')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=API_BASE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--render-preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        _run(args)
    except (PromptVersionConflict, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
