"""发布 `buyer_intent_semantic_parser` v0.2.0。

v0.1.0 在 0827 验收里暴露了两类问题，都不是模型不行，是提示词没给规则：

1. **条件分叉被塌成一个轴，丢掉的那半不留痕迹。** 广东省盐业的原文写
   「营收：上市要有10个亿，非上市要至少4-5亿」，而 v0.1.0 的规则 1 只认「或者」
   「另一种是」这类**并列方案**的触发词。这句一个词都没命中，模型于是挑了「并表/参股」
   这个轴（这个轴本身是对的），把 10 亿挂上去、把 4-5 亿丢了，`unknowns` 是空的。
   后果：一个营收 5 亿的非上市标的会被初筛挡掉，尽管买家明说 4-5 亿可以，
   而界面上看不出这次收窄。

2. **地区在硬猜。** 广州工控原文「无地域限制」被解析成「广东省(preferred)」——
   那是**买家自己**所在的省；广州城投「优选长三角区域」被解析成「广东省 + 排除湖北省」，
   而长三角既不含广东也不含湖北。填错一个省比留空更危险：初筛会把该进的标的全挡掉。

   根因是 v0.1.0 的规则 5 明令「地区一律保留买家原话，不要映射到任何标准值」，
   于是「长三角」这种说法既不能展开、又没有对应的省份可填，模型只能猜。
   生产 50 条需求里，只有文本没能结构化的那 26 条提到长三角 7 次、华东/华中/西南
   各 2 次、大湾区/粤港澳/珠三角/成渝/华北各 1 次 —— 猜的空间很大。

v0.2.0 因此给地区开了唯一的例外：**必须展开成省级行政区**（用户 0828 要求），
原话仍留在 evidence 里。代码侧同时保留了城市群展开作为兜底
（`region_dictionary.REGION_GROUPS`），两道防线针对的是同一件事的两种失败方式：
模型不展开（代码兜住）与模型展开错（代码按标准名校验）。

用法（必须从仓库根目录运行）：
    python scripts/publish_buyer_intent_semantic_parser_v020_prompt.py            # 预演
    python scripts/publish_buyer_intent_semantic_parser_v020_prompt.py --apply    # 发布并设为默认
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.match_ma_api_tools import DEFAULT_API_BASE, _request_json, _resolve_token  # noqa: E402

NODE_NAME = "buyer_intent_semantic_parser"
VERSION = "v0.2.0"

SYSTEM_PROMPT = """你负责买家并购需求解析的第一阶段：读懂原始材料，把意思拆开。

只做语义理解，不做字段映射，不做枚举归一，不做单位换算 —— 那些是第二阶段的事。
输出一个 JSON 对象，不要 Markdown。不要臆造材料里没有的事实。

只提取买家主体和买家意向当前有效的信息。与某个标的的沟通过程、反馈、推进状态和
下一步必须忽略，不得写入需求描述。"""

USER_PROMPT = """买家需求原文：
{{ raw_requirement_text }}

买家已有信息 JSON：
{{ buyer_profile_json }}

按下面的结构输出：
{
  "intent_name": "一句话概括这条需求",
  "summary": "买家想买什么样的标的，用中文完整叙述",
  "common_conditions": [
    {"aspect": "行业 / 财务 / 地区 / 股权 / 交易 / 风险 / 其他",
     "statement": "这条条件说的是什么，保留原文口径",
     "strength": "hard | preference | unknown",
     "evidence": "支撑它的原文片段"}
  ],
  "scenarios": [
    {"name": "方案名，如「方案A」或买家自己的叫法",
     "statement": "这个方案整体要什么",
     "conditions": [{"aspect": "...", "statement": "...", "strength": "...", "evidence": "..."}]}
  ],
  "excluded": [{"statement": "明确不要什么", "evidence": "原文片段"}],
  "unknowns": ["材料里提到但说不清、需要顾问确认的点"],
  "buyer_party": {"statement": "关于买方自身的描述，如集团背景、主营、所在地"}
}

拆解规则：
1. 方案是一组可以互相替代的条件。有两种情形都要拆进 scenarios：
   a) 买家明说的并列方案（「或者」「另一种是」「A 方案 / B 方案」）；
   b) 同一个条件在不同前提下取不同值 —— 「上市的要 10 个亿，非上市的要 4-5 亿」
      是两个方案，各自带上自己的前提和数值，不是一个方案里取其中一个数。
   所有方案共用的条件放 common_conditions；只有一种要求时 scenarios 留空数组。
2. 拆不开就说出来，不要私自取舍。前提交叉、数值对不上、不确定哪个前提管哪个数值时，
   把整句原样写进 unknowns 让顾问确认。**绝不能挑一个数值留下、把另一个丢掉** ——
   被丢掉的那个门槛会让筛选把本该进来的标的挡在外面，而这件事在界面上看不出来。
3. strength 区分硬性和偏好：「必须」「不低于」「否则不看」是 hard；
   「优先」「最好」「可以放宽」是 preference；说不清的是 unknown。
   不要把偏好升格成硬性条件。
4. evidence 必须是原文里真实出现过的片段，不要复述、不要翻译。
5. 数字保留原文写法（「三千万」就写「三千万」，不要换算成 30000000），
   单位换算交给第二阶段。
6. 行业、上市状态等一律保留买家的原话，不要映射到任何标准值。
7. 地区是唯一的例外：必须落到省 / 市 / 区这一级，城市群和大区要展开成它覆盖的省。
   「长三角」写成「上海、江苏、浙江、安徽」；「粤港澳大湾区」写成「广东、香港、澳门」；
   「珠三角」写成「广东」；「京津冀」写成「北京、天津、河北」；「成渝」写成「四川、重庆」；
   「华东」写成「上海、江苏、浙江、安徽、福建、江西、山东」；「华南」写成「广东、广西、海南」；
   「华北」写成「北京、天津、河北、山西、内蒙古」；「华中」写成「河南、湖北、湖南」；
   「西南」写成「重庆、四川、贵州、云南、西藏」；「西北」写成「陕西、甘肃、青海、宁夏、新疆」；
   「东北」写成「辽宁、吉林、黑龙江」。
   能定到市或区的一起给（「浙江省，宁波优先」写成「浙江 宁波」）。原话仍要写进 evidence。
8. 原文说「全国」「不限」「无地域限制」「不限注册地」时，地区条件就是「没有限制」，
   照这么写，不要输出任何省份。买家自己在哪个省，和它想买哪里的标的是两件事 ——
   拿买家所在地当地区要求填进去，会让筛选把其他省的标的全部挡掉。
9. buyer_party 只描述买方自己，不要把它写成对标的的要求。
10. 材料里没有的内容一律不写，宁可留空也不要补齐。"""

DESCRIPTION = (
    "v0.2.0（0828）：条件分叉也拆方案且拆不开必须进 unknowns（盐业「上市10亿/非上市4-5亿」"
    "被塌成一个轴、丢掉 4-5 亿）；地区必须展开到省市区、"
    "「不限」不得输出省份（工控「无地域限制」被填成买家自己所在的广东省）。"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="真的发布；不加只预演")
    parser.add_argument("--no-default", action="store_true", help="发布但不设为默认，便于在设置页对比")
    args = parser.parse_args()

    api_base = DEFAULT_API_BASE
    token = _resolve_token(api_base)

    existing = _request_json(api_base, "GET", "/model-config/prompts", token=token, query={"node_name": NODE_NAME})
    versions = existing if isinstance(existing, list) else (existing.get("items") or [])
    print(f"节点 {NODE_NAME} 现有版本：")
    for item in versions:
        flag = "  ← 当前默认" if item.get("is_default") else ""
        print(f"  {item.get('version')}  active={item.get('is_active')}{flag}")
    if any(item.get("version") == VERSION for item in versions):
        print(f"\n{VERSION} 已存在，不重复创建。要改内容请在设置页编辑或换版本号。")
        return 1

    print(f"\nsystem {len(SYSTEM_PROMPT)} 字 · user {len(USER_PROMPT)} 字")
    if not args.apply:
        print("\n--- 预演，未发布。加 --apply 执行 ---")
        print(USER_PROMPT[USER_PROMPT.index("拆解规则："):])
        return 0

    created = _request_json(
        api_base,
        "POST",
        "/model-config/prompts",
        token=token,
        json_body={
            "node_name": NODE_NAME,
            "version": VERSION,
            "name": f"{NODE_NAME} {VERSION}",
            "description": DESCRIPTION,
            "system_prompt": SYSTEM_PROMPT,
            "user_prompt_template": USER_PROMPT,
            "template_engine": "jinja",
            "is_active": True,
            "is_default": not args.no_default,
        },
    )
    print(f"\n已发布 {created.get('version')}  id={created.get('id')}  default={created.get('is_default')}")
    print(json.dumps({"id": created.get("id"), "version": created.get("version")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
