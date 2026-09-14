# -*- coding: utf-8 -*-
"""批量调用 wegent agent，跑「库规模 → 召回率」曲线。

要回答的问题只有一个：**把整个标的库全量丢给 LLM 做业务匹配判断，
规模涨到多少条时它开始漏。**

方法：固定一组标准答案（例如锂电产业链 11 家），只往库里加不相关的干扰项，
把规模从 50 撑到 300。答案不变、噪声变多 —— 这正是真实库增长的样子。

三个必须守住的实验纪律，写在最前面：

1. **切片按名称记答案，按行号交互。** 每个规模的表格都重新编号 1..N，所以
   行号在不同规模之间没有可比性。模型返回行号，工具映射回名称再比对。
2. **同一规模的多次重复用同一份切片。** 否则测到的是数据波动，不是模型波动。
3. **解析失败必须单独记，不能计入漏检。** 解析漏了和模型漏了，方向一样、
   原因完全不同 —— 混在一起会让曲线假性偏低，而且正好偏向我们预期的方向。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MASTER = HERE / "mock_master.json"
QUESTIONS = HERE / "questions.json"
DEFAULT_BASE_URL = "https://ai.mpgroup.cn:3107/api/v1"
DEFAULT_MODEL = "ma-match#标的筛选提示词测试"

LISTED_CN = {"listed": "已上市", "unlisted": "未上市", "pre_ipo": "拟上市"}


# ---------- 数据与切片 ----------

def load_master() -> list[dict[str, Any]]:
    return json.loads(MASTER.read_text(encoding="utf-8"))


def money(w: Any) -> str:
    if w in ("", None, ","):
        return "-"
    try:
        w = float(w)
    except (TypeError, ValueError):
        return "-"
    if abs(w) >= 10000:
        return f"{w / 10000:.2f}".rstrip("0").rstrip(".") + "亿"
    return f"{w:.0f}万"


def build_slice(master: list[dict[str, Any]], size: int, protected: list[str], seed: int):
    """protected 里的标的必然在内，其余用干扰项补到 size，重新编号。

    返回 (rows, row_to_name)。row_to_name 的键是本切片的行号。
    """
    keep = [d for d in master if d["name"] in set(protected)]
    if len(keep) > size:
        raise SystemExit(f"规模 {size} 小于必含答案数 {len(keep)}，无法构造切片。")
    pool = [d for d in master if d["name"] not in set(protected)]
    rng = random.Random(seed)
    rows = keep + rng.sample(pool, size - len(keep))
    rng.shuffle(rows)
    return rows, {i: d["name"] for i, d in enumerate(rows, 1)}


def render_table(rows: list[dict[str, Any]]) -> str:
    # 没有「一级行业」列 —— 真实的标的信息来自年报或企业介绍材料，不存在这种字段。
    # 取而代之的是**标签**：人工录入、多值、会滞后会写错，模型得自己决定信不信。
    out = ["| # | 标的名称 | 标签 | 上市状态 | 营收 | 净利润 | 业务说明 |",
           "|---|---|---|---|---|---|---|"]
    for i, d in enumerate(rows, 1):
        out.append(
            f"| {i} | {d['name']} | {'、'.join(d.get('tags') or []) or '-'} | "
            f"{LISTED_CN.get(d['listed'], '未知')} | {money(d['rev'])} | {money(d['prof'])} | "
            f"{d['summary'] or '（未录入）'} |"
        )
    return "\n".join(out)


# ---------- 调用 ----------

def make_client(base_url: str):
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("缺少依赖：请先运行  pip install openai")
    key = os.environ.get("MA_MATCH_API_KEY")
    if not key:
        # 没设环境变量就当场问，别让人为了跑个测试先去学怎么配环境变量。
        # 只存在本次进程里，不落盘。
        import getpass
        try:
            key = getpass.getpass("请粘贴 API Key（输入时不显示，粘完直接回车）：").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("已取消。")
        if not key:
            raise SystemExit("没有输入 Key。")
        os.environ["MA_MATCH_API_KEY"] = key
        print("（本次运行有效；要免去每次输入，见下方说明设置环境变量）\n")
    return OpenAI(api_key=key, base_url=base_url)


# wegent 服务端对 tools 这个参数的处理曾经抛过
# `build_execution_request() got an unexpected keyword argument 'auto_enable_web_search'`
# —— 那是它内部的 TypeError，不是我们传错了。带上 tools 会走到那条分支，不带就绕开。
# 一旦撞上，自动去掉 tools 重试一次，并把这件事记在结果里，不静默吞掉。
_SERVER_SIGNATURE_ERROR = "unexpected keyword argument"
_TOOLS_DISABLED = {"value": False}


def _once(client, model: str, prompt: str, timeout: int, use_tools: bool) -> str:
    kwargs: dict[str, Any] = {"model": model, "input": prompt, "stream": True, "timeout": timeout}
    if use_tools:
        kwargs["tools"] = [{"type": "wegent_chat_bot"}]
    text: list[str] = []
    for event in client.responses.create(**kwargs):
        if getattr(event, "type", "") == "response.output_text.delta":
            text.append(event.delta)
    return "".join(text)


def call_agent(client, model: str, prompt: str, timeout: int,
               use_tools: bool = True) -> tuple[str, float]:
    started = time.time()
    want_tools = use_tools and not _TOOLS_DISABLED["value"]
    try:
        return _once(client, model, prompt, timeout, want_tools), time.time() - started
    except Exception as error:  # noqa: BLE001 —— 要看错误内容才能决定怎么退
        if want_tools and _SERVER_SIGNATURE_ERROR in str(error):
            _TOOLS_DISABLED["value"] = True   # 本次运行内不再重试带 tools 的调用
            print("  ⚠ 服务端拒绝了 tools 参数（它内部的 TypeError），已自动去掉 tools 重试；"
                  "本次运行后续调用都不带 tools。")
            return _once(client, model, prompt, timeout, False), time.time() - started
        raise


# ---------- 解析 ----------

_JSON_RE = re.compile(r'\{[^{}]*"hit"\s*:\s*\[[^\]]*\][^{}]*\}')
_ROW_RE = re.compile(r"^\s*\|\s*(\d{1,3})\s*\|", re.M)


def parse_reply(text: str) -> tuple[dict[str, Any] | None, str]:
    """优先读约定的 JSON；读不到再退回抓表格行号，并如实标注来源。"""
    matches = _JSON_RE.findall(text)
    if matches:
        try:
            data = json.loads(matches[-1])
            return {
                "hit": [int(x) for x in data.get("hit", []) if str(x).isdigit()],
                "maybe": [int(x) for x in data.get("maybe", []) if str(x).isdigit()],
                "insufficient": [int(x) for x in data.get("insufficient", []) if str(x).isdigit()],
                "checked": data.get("checked"),
            }, "json"
        except (ValueError, TypeError):
            pass
    rows = [int(x) for x in _ROW_RE.findall(text)]
    if rows:
        return {"hit": sorted(set(rows)), "maybe": [], "insufficient": [], "checked": None}, "table"
    return None, "failed"


# ---------- 评分 ----------

def score(parsed, row_to_name, expected: list[str], must_not: list[str], master_by_name,
          insufficient: list[str] | None = None):
    hit_names = {row_to_name.get(r) for r in parsed["hit"]} - {None}
    maybe_names = {row_to_name.get(r) for r in parsed["maybe"]} - {None}
    insuff_names = {row_to_name.get(r) for r in parsed["insufficient"]} - {None}
    expected_set = set(expected)
    found = hit_names & expected_set
    missed = expected_set - hit_names
    false_pos = hit_names & set(must_not)
    # 命中里既不在答案集也不在禁忌集的，算「额外召回」—— 粗筛阶段不算错，单独记
    extra = hit_names - expected_set - set(must_not)

    def by_tag(names, tag):
        return {n for n in names if master_by_name.get(n, {}).get("tag") == tag}

    exp_thin, exp_thick = by_tag(expected_set, "T"), by_tag(expected_set, "H")
    return {
        "expected": len(expected_set),
        "hit_total": len(hit_names),
        "found": len(found),
        "recall": round(len(found) / len(expected_set), 3) if expected_set else None,
        "missed": "、".join(sorted(missed)),
        "false_pos": len(false_pos),
        "false_pos_names": "、".join(sorted(false_pos)),
        "extra": len(extra),
        # 名单要落盘：复核分歧时需要知道「额外召回的是哪几家」，只存个数就查不回去了。
        "extra_names": "、".join(sorted(extra)),
        "hit_names": "、".join(sorted(hit_names)),
        "maybe": len(maybe_names),
        "recall_thin": round(len(found & exp_thin) / len(exp_thin), 3) if exp_thin else None,
        "recall_thick": round(len(found & exp_thick) / len(exp_thick), 3) if exp_thick else None,
        # 摘要为空的标的，正确做法是列进「信息不足」——既不能凭名字猜进命中清单，
        # 也不能默默丢掉。这两种错法后果完全不同，所以单独记一格。
        "insuff_expected": len(set(insufficient or [])),
        "insuff_ok": len(set(insufficient or []) & insuff_names),
        "insuff_wrongly_hit": len(set(insufficient or []) & hit_names),
    }


# ---------- 各模式 ----------

def cmd_probe(args):
    """确认 agent 用的是我发过去的表格，而不是别处的数据。

    这一步必须先做：如果这个 agent 身上挂了能访问真实标的库的工具，它可能拿真库
    答题，而测试结果看起来完全正常 —— 那是最贵的一种失败。
    """
    master = load_master()
    rows, row_to_name = build_slice(master, 30, [], seed=99)
    target_row = 17
    truth = row_to_name[target_row]
    prompt = (
        f"下面是一份标的表格。请只回答两件事，不要做任何分析：\n"
        f"1. 表格一共有多少行？\n2. 第 {target_row} 行的标的名称是什么？\n\n"
        + render_table(rows)
    )
    client = make_client(args.base_url)
    try:
        text, elapsed = call_agent(client, args.model, prompt, args.timeout, use_tools=not args.no_tools)
    except Exception as error:  # noqa: BLE001 —— 探针阶段要把原始错误原样给人看
        print(f"调用失败：{type(error).__name__}\n{error}\n")
        print("排查顺序：")
        print("  1. 错误里出现 unexpected keyword argument → 是 wegent 服务端的内部错误，")
        print("     加 --no-tools 再试一次；仍失败就得找 wegent 维护者，不是这边能修的。")
        print("  2. 401 / 403 → key 不对或没权限。")
        print("  3. 404 / model not found → --model 的 agent 名写错了。")
        print("  4. 超时 → 加大 --timeout。")
        return 2
    print(f"耗时 {elapsed:.1f}s\n--- 回复 ---\n{text[:800]}\n---")
    ok_rows = "30" in text
    ok_name = truth[:6] in text
    print(f"总行数答对（应为 30）：{'✅' if ok_rows else '❌'}")
    print(f"第 {target_row} 行答对（应为 {truth}）：{'✅' if ok_name else '❌'}")
    if ok_rows and ok_name:
        print("\n结论：agent 读的是我发过去的表格，可以开跑。")
        return 0
    print("\n结论：**不要开跑**。它没有正确读到发过去的表格 —— 可能是提示词里挂了知识库、"
          "带了能查真实库的工具，或者输入被截断。先排掉这个再测。")
    return 2


def build_prompt(question: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    return f"{question['prompt']}\n\n以下是标的库，共 {len(rows)} 条：\n\n{render_table(rows)}"


def run_one(client, args, question, master, master_by_name, size, rep):
    rows, row_to_name = build_slice(master, size, question.get("protected", []), seed=1000 + size)
    prompt = build_prompt(question, rows)
    record = {"question": question["id"], "size": size, "rep": rep,
              "prompt_chars": len(prompt), "error": ""}
    try:
        text, elapsed = call_agent(client, args.model, prompt, args.timeout,
                                   use_tools=not args.no_tools)
    except Exception as error:  # noqa: BLE001 —— 单次失败不该中断整轮
        record.update(elapsed=0, parse="error", error=f"{type(error).__name__}: {error}")
        return record, ""
    parsed, source = parse_reply(text)
    record.update(elapsed=round(elapsed, 1), parse=source, reply_chars=len(text))
    if parsed is None:
        record["error"] = "解析不出命中行号"
        return record, text
    record["checked"] = parsed.get("checked")
    record["checked_ok"] = (parsed.get("checked") == size)
    record.update(score(parsed, row_to_name, question["expected"],
                        question.get("must_not", []), master_by_name))
    return record, text


def cmd_run(args):
    master = load_master()
    master_by_name = {d["name"]: d for d in master}
    questions = {q["id"]: q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))}
    picked = [questions[q] for q in args.questions]
    client = make_client(args.base_url)

    tasks = [(q, size, rep) for q in picked for size in args.sizes for rep in range(1, args.repeats + 1)]
    print(f"共 {len(tasks)} 次调用，并发 {args.concurrency}")
    outdir = HERE / "results"
    outdir.mkdir(exist_ok=True)
    records: list[dict[str, Any]] = []

    def work(task):
        q, size, rep = task
        rec, text = run_one(client, args, q, master, master_by_name, size, rep)
        if text:
            (outdir / f"reply_{q['id']}_{size}_{rep}.txt").write_text(text, encoding="utf-8")
        return rec

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for i, rec in enumerate(pool.map(work, tasks), 1):
            records.append(rec)
            flag = "!" if rec.get("error") else " "
            print(f"  [{i}/{len(tasks)}]{flag} {rec['question']} N={rec['size']} #{rec['rep']} "
                  f"召回={rec.get('recall')} 耗时={rec.get('elapsed')}s {rec.get('error','')}")

    fields = sorted({k for r in records for k in r})
    with (outdir / "results.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    write_report(records, outdir)
    print(f"\n完成。明细 {outdir/'results.csv'}，汇总 {outdir/'report.md'}")
    return 0


def write_report(records, outdir: Path):
    out = ["# 召回率曲线测试结果", ""]
    ok = [r for r in records if not r.get("error")]
    bad = [r for r in records if r.get("error")]
    out.append(f"有效 {len(ok)} 次，失败 {len(bad)} 次。**失败的不计入统计**，"
               "解析失败与模型漏检是两回事，混在一起会让曲线假性偏低。\n")
    by = {}
    for r in ok:
        by.setdefault((r["question"], r["size"]), []).append(r)
    out.append("| 问题 | 规模 | 召回率(均值) | 波动(最低~最高) | 薄组 | 厚组 | 误检 | 额外召回 | checked 对得上 | 平均耗时 |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for (qid, size) in sorted(by):
        rs = by[(qid, size)]
        rec = [r["recall"] for r in rs if r.get("recall") is not None]
        thin = [r["recall_thin"] for r in rs if r.get("recall_thin") is not None]
        thick = [r["recall_thick"] for r in rs if r.get("recall_thick") is not None]
        chk = sum(1 for r in rs if r.get("checked_ok"))
        out.append(
            f"| {qid} | {size} | {statistics.mean(rec):.0%} | {min(rec):.0%}~{max(rec):.0%} | "
            f"{statistics.mean(thin):.0%} | {statistics.mean(thick):.0%} | "
            f"{statistics.mean([r['false_pos'] for r in rs]):.1f} | "
            f"{statistics.mean([r['extra'] for r in rs]):.1f} | {chk}/{len(rs)} | "
            f"{statistics.mean([r['elapsed'] for r in rs]):.0f}s |"
        )
    out.append("\n## 漏掉了哪些（按出现频次）\n")
    freq: dict[str, int] = {}
    for r in ok:
        for name in filter(None, (r.get("missed") or "").split("、")):
            freq[name] = freq.get(name, 0) + 1
    for name, n in sorted(freq.items(), key=lambda kv: -kv[1]):
        out.append(f"- {name} —— 漏 {n} 次")
    if bad:
        out.append("\n## 失败明细\n")
        for r in bad:
            out.append(f"- {r['question']} N={r['size']} #{r['rep']}：{r['error']}")
    (outdir / "report.md").write_text("\n".join(out) + "\n", encoding="utf-8")


MENU = """
========================================
  标的匹配 · 召回率曲线测试
========================================

  1  probe  —— 先验证 agent 读的是发过去的表格（第一次务必先跑这个）
  2  smoke  —— 单次试跑一题，看耗时与解析是否正常
  3  run    —— 跑完整矩阵：Q2 × 4 个规模 × 5 次重复 = 20 次调用
  0        退出

"""


def choose_mode() -> str:
    """直接双击 / VS Code ▶ 运行时没有命令行参数，给个菜单，别让人对着 argparse 报错发愣。"""
    print(MENU)
    mapping = {"1": "probe", "2": "smoke", "3": "run", "probe": "probe", "smoke": "smoke", "run": "run"}
    while True:
        try:
            choice = input("请输入序号后回车：").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\n已退出。")
        if choice in ("0", "q", "exit"):
            raise SystemExit("已退出。")
        if choice in mapping:
            print("")
            return mapping[choice]
        print("没看懂，请输入 1 / 2 / 3 / 0。")


def main() -> int:
    p = argparse.ArgumentParser(description="标的匹配召回率曲线测试")
    p.add_argument("mode", nargs="?", choices=["probe", "smoke", "run"], default=None,
                   help="probe=先验证 agent 读的是我发的表格；smoke=单次试跑看耗时；run=跑矩阵。"
                        "不填则进入交互菜单。")
    p.add_argument("--model", default=os.environ.get("MA_MATCH_MODEL", DEFAULT_MODEL))
    p.add_argument("--base-url", default=os.environ.get("MA_MATCH_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--questions", nargs="*", default=["Q2"])
    p.add_argument("--sizes", nargs="*", type=int, default=[50, 100, 200, 300])
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--no-tools", action="store_true",
                   help="不传 tools 参数。wegent 服务端对它有已知的内部错误时用这个。")
    args = p.parse_args()
    if args.mode is None:
        args.mode = choose_mode()

    if args.mode == "probe":
        return cmd_probe(args)
    if args.mode == "smoke":
        args.sizes, args.repeats, args.concurrency = args.sizes[:1], 1, 1
        return cmd_run(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
