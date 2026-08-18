"""为 `recommendation_deep_eval_to_target` 发布 v0.2.0 提示词（对话链路的新形态深评）。

**走 API，不写迁移** —— 迁移只管 schema，提示词新建/回滚都即时生效。

v0.1.0（`seed_v01_prompts.py` 那份）是从共用深评复制来的旧形态：分档 A/B/C、按
分片提交、输出 `{"results": [{"index": …, "grade": …}]}`。v0.2.0 换成阶段三定下的
形态，三处不同：

1. **不评级、不打分，只排序。** 分档是绝对判断（要求模型心里有一把看不见的标尺），
   排序是相对判断（两两比较），LLM 对后者稳定得多。
2. **不分片，整体提交。** 取消分档之后分片就不成立了：纯排序时 A 片的 rank 1 和
   B 片的 rank 1 谁靠前没有任何依据。
3. **逐条判定定性诉求**，键用原文。它是排序的依据，不是装饰 —— 用户问「为什么
   这家排第一」，答案就是三条诉求全部符合。

发布之后不需要发版：代码侧（`backend/app/services/recommendation_deep_eval.py`）
已经按这份 schema 归一化，模型返回旧形态会被判成 `schema_mismatch` 而不是静默错一轮。

用法（必须从仓库根目录运行，token 读 `.match-ma-local-auth.json`）：
    python scripts/publish_deep_eval_v020_prompt.py --dry-run
    python scripts/publish_deep_eval_v020_prompt.py --render-preview
    python scripts/publish_deep_eval_v020_prompt.py --apply
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

API_BASE = "https://match-ma-production.up.railway.app/api/v1"

NODE_NAME = "recommendation_deep_eval_to_target"
VERSION = "v0.2.0"


SYSTEM_PROMPT = """你是 Match-MA 的并购撮合分析师。这一轮固定的是买家需求，候选是标的。

你的工作只有一件：**逐条判定买家的定性诉求，然后按匹配程度把候选从最合适排到最不合适。**

三条边界，先记住再动手：

1. **硬条件已经在数据库层筛过了。** 你看到的每一家都已经满足了行业、地区、营收、
   估值、控股、上市状态这类可量化的门槛，不要再判一遍，更不要因为「营收只比门槛高
   一点」「PE 略高」这类理由扣分 —— 门槛之上的差距不是你要衡量的东西。
2. **不评级、不打分。** 不要输出 A/B/C，不要输出 0-100 的分数，只输出名次。
3. **只用给你的材料。** 材料里没有的事实一律不要补全、不要推测。缺信息就写进
   info_gaps，判不了就判「无法判断」。

输出一个 JSON 对象，不要 Markdown、不要代码块围栏。"""


USER_PROMPT_TEMPLATE = """推荐方向：{{ mode }}

# 买家这一轮的需求

{{ anchor_context }}

# 需要你逐条判定的定性诉求

{{ qualitative_requirements_json }}

这些是翻不成数据库条件、只能靠读材料判断的要求。它们是这次排序的**主要依据**。

# 候选清单

{{ candidates_json }}

字段说明：
- `id` —— 原样引用，不要改写、不要重编号
- `hit_count` —— 这家被几组筛选条件命中。命中多组说明它同时满足买家的多套方案，
  是更强的候选；`0` 表示它不是筛出来的，是按名字直接调出来的
- `facts` —— 代码算出的硬数据，可直接引用
- `profile` —— 分栏画像。标着「暂无画像信息」的，是我们库里还没录，**不是这家公司
  没有这些东西**

# 输出格式

{
  "ranked": [
    {
      "id": "候选清单里的 id，原样抄",
      "rank": 1,
      "qualitative_verdicts": {
        "定性诉求原文，一个字都不要改": "符合"
      },
      "fit_points": ["为什么它排这个位置，一句一条，最多 5 条"],
      "risks": "主要风险或不确定点，没有就写 暂无",
      "info_gaps": "要判准还缺什么信息，没有就写 暂无"
    }
  ],
  "dropped": [
    {"id": "…", "reason": "明显不符合在哪里，一句话"}
  ]
}

# 规则

1. **逐条判定。** `qualitative_verdicts` 的键必须是上面「定性诉求」里的**原文**，
   一字不差地抄过来。不要改写成你觉得更顺的说法，不要合并两条，不要自己加一条 ——
   自创的键会被丢弃。定性诉求为空时，`qualitative_verdicts` 就写成 {}。
2. **判定只有三个取值**：`符合` / `不符合` / `无法判断`。没有第四个，也没有「基本符合」
   「较为符合」这类中间态。
3. **`无法判断` 是正确答案，不是失败。** 材料里没写、画像是空的、只能靠公司名猜 ——
   这些一律判 `无法判断`。猜出来的「符合」比诚实的「无法判断」有害得多：客户经理会
   拿着它去跟客户说话。
4. **排序是判定的结果，不是你的偏好。** 符合的条数多、且符合的是买家说得更重的那几条，
   就排在前面；判定情况相同时，`hit_count` 高的排前面。同一条诉求上，`符合` 一定
   优于 `无法判断`，`无法判断` 一定优于 `不符合`。
5. **`rank` 从 1 开始连续编号**，不要跳号、不要重复。
6. **`dropped` 只放明显不符合的**——比如买家明确说不要的行业、明确排除的类型。
   拿不准的、信息不足的**不要剔**，放进 `ranked` 靠后的位置。剔除是很强的动作：
   客户经理宁可看到一家不理想的，也不愿意看到一片空白。
7. **每个候选恰好出现一次**，在 `ranked` 或 `dropped` 里，不要两边都写、不要漏掉。
8. `fit_points` / `risks` / `info_gaps` 用简洁中文，每条不超过 100 字。

# 示例

假设定性诉求是 `["具备地区产业优势", "有成熟的海外仓网络"]`，候选是两家：

{
  "ranked": [
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000001",
      "rank": 1,
      "qualitative_verdicts": {
        "具备地区产业优势": "符合",
        "有成熟的海外仓网络": "无法判断"
      },
      "fit_points": ["画像写明是当地产业集群的链主，配套半径 30 公里内", "被两组条件同时命中"],
      "risks": "客户集中度偏高，前两大客户占比约六成",
      "info_gaps": "海外仓与出口渠道在材料里完全没有提及"
    },
    {
      "id": "a1b2c3d4-0000-0000-0000-000000000002",
      "rank": 2,
      "qualitative_verdicts": {
        "具备地区产业优势": "无法判断",
        "有成熟的海外仓网络": "无法判断"
      },
      "fit_points": ["硬条件全部达标"],
      "risks": "暂无",
      "info_gaps": "画像为空，产业地位与海外布局都无从判断"
    }
  ],
  "dropped": [
    {"id": "a1b2c3d4-0000-0000-0000-000000000003", "reason": "主营是买家明确排除的房地产开发"}
  ]
}

注意第二家：画像为空并不构成剔除的理由，它排在后面、判定写「无法判断」、
缺口写清楚 —— 这比把它剔掉对客户经理有用得多。"""


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["ranked"],
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "rank"],
                "properties": {
                    "id": {"type": "string"},
                    "rank": {"type": "integer", "minimum": 1},
                    # 闭集用 enum 约束。三个取值之外的一律在代码侧归成「无法判断」，
                    # 但先让 schema 说一遍，能省下相当一部分归一化。
                    "qualitative_verdicts": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "string",
                            "enum": ["符合", "不符合", "无法判断"],
                        },
                    },
                    "fit_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                    "risks": {"type": ["string", "null"]},
                    "info_gaps": {"type": ["string", "null"]},
                },
            },
        },
        "dropped": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "reason": {"type": ["string", "null"]},
                },
            },
        },
    },
}


def _api_client():
    """`match_ma_api_tools` 晚绑定：提示词正文要能被测试直接 import，
    而那一步不该顺带把 API 客户端和 token 读取拖进来。"""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import match_ma_api_tools as api

    return api


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=API_BASE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--render-preview", action="store_true",
                       help="服务端渲染一遍，确认四个变量都被替换成了值而不是字面量")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    api = _api_client()
    token = api._resolve_token(args.api_base)

    if args.render_preview:
        preview = api._request_json(
            args.api_base,
            "POST",
            "/model-config/prompts/render-preview",
            token=token,
            json_body={
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt_template": USER_PROMPT_TEMPLATE,
            },
        )
        print("识别到的变量：", preview["variables"])
        rendered = preview["rendered_user_prompt"]
        for name in ("mode", "anchor_context", "candidates_json", "qualitative_requirements_json"):
            marker = "{{ " + name + " }}"
            state = "[FAIL] 仍是字面量" if marker in rendered else "[OK] 已替换成值"
            print(f"  {name}: {state}")
        print("---- 渲染后的 user prompt（前 1200 字）----")
        print(rendered[:1200])
        return

    existing = api._request_json(
        args.api_base, "GET", f"/model-config/prompts?node_name={NODE_NAME}&include_inactive=true", token=token
    )
    rows = existing if isinstance(existing, list) else existing.get("items", [])
    if any(row.get("version") == VERSION for row in rows):
        print(f"[skip] {NODE_NAME} 已有 {VERSION}，现有版本 {[row['version'] for row in rows]}")
        return

    if args.dry_run:
        print(f"[dry-run] {NODE_NAME}: 将创建 {VERSION} 并设为默认")
        print(f"  现有版本：{[row['version'] for row in rows] or '（无）'}")
        print(f"  system {len(SYSTEM_PROMPT)} 字 / user {len(USER_PROMPT_TEMPLATE)} 字")
        print(f"  output_schema: {json.dumps(OUTPUT_SCHEMA, ensure_ascii=False)[:200]}…")
        return

    created = api._request_json(
        args.api_base,
        "POST",
        "/model-config/prompts",
        token=token,
        json_body={
            "node_name": NODE_NAME,
            "version": VERSION,
            "name": "推荐深评·为买家找标的 v0.2.0（逐条判定 + 排序）",
            "description": "对话链路深评：逐条判定定性诉求后重排序，不分档、不分片。",
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt_template": USER_PROMPT_TEMPLATE,
            "output_schema_json": OUTPUT_SCHEMA,
            "is_active": True,
            "is_default": True,
        },
    )
    print(f"[created] {NODE_NAME} {VERSION} id={created.get('id')}")
    print("下一步：用 --render-preview 确认变量被替换成了值，再在推荐对话里发一句带定性诉求的需求。")


if __name__ == "__main__":
    main()
