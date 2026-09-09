"""存量标的的业务标签收敛（方案 0908 §5.3）。

迁移 025 只把二级行业回填成标签（阿里云 13/94、Railway 47/71），其余标的的
`business_tags_json` 是空的。这个脚本对没有标签的 A–D 级标的逐个调
`POST /seller-targets/{id}/parse`（force=true），让新版解析 prompt 从已有摘要里
写出 3~5 个标签；跑完再重建搜索文档，否则深评看到的还是「一级行业：制造与工业」。

用法（先 5 条试跑，看更新记录没问题再全量）：

    python scripts/backfill_target_business_tags.py --dry-run
    python scripts/backfill_target_business_tags.py --limit 5 --apply
    python scripts/backfill_target_business_tags.py --apply --rebuild-search-docs

对阿里云：加 --api-base http://<ECS>/api/v1，并在同一 shell 里设
MATCH_MA_SAMPLE_USERNAME / MATCH_MA_SAMPLE_PASSWORD（或 MATCH_MA_ADMIN_TOKEN）。

注意：
- worker-llm 是单队列，每次入队后间隔 --interval 秒，别把顾问正在等的解析排到几十个补跑后面。
- 标的正在调研时解析入口返回 409，脚本记下来跳过，跑完汇总。
- 重解析会把摘要里的其他字段也再抽一遍：级别有反模式①保护（AI 只能进 E、未提取不写），
  财务数字若与现值不同走待复核；所以先 5 条看更新记录。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import match_ma_api_tools as api  # noqa: E402

RECOMMENDABLE_GRADES = {"A", "B", "C", "D"}


def _list_all_targets(api_base: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = api._request_json(
            api_base, "GET", "/seller-targets", token=token, query={"limit": 200, "offset": offset}
        )
        batch = page.get("items") or []
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= int(page.get("total") or 0):
            break
    return items


def _needs_tags(target: dict[str, Any]) -> bool:
    if target.get("target_grade") not in RECOMMENDABLE_GRADES:
        return False
    tags = target.get("business_tags_json") or []
    return not [tag for tag in tags if str(tag or "").strip()]


def _wait_for_parse(api_base: str, token: str, target_id: str, *, poll_seconds: int, max_wait: int) -> str:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status = api._request_json(api_base, "GET", f"/seller-targets/{target_id}/parse-status", token=token)
        job = status.get("latest_job") or status
        state = str(job.get("status") or status.get("status") or "")
        if state in {"succeeded", "failed", "cancelled", "archived"}:
            return state
        time.sleep(poll_seconds)
    return "timeout"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-base", default=os.getenv("MATCH_MA_API_BASE", api.DEFAULT_API_BASE))
    parser.add_argument("--limit", type=int, default=0, help="最多补跑几条，0 = 全部")
    parser.add_argument("--interval", type=float, default=4.0, help="两次入队之间的间隔秒数")
    parser.add_argument("--poll-seconds", type=int, default=6)
    parser.add_argument("--max-wait-seconds", type=int, default=300, help="单条解析最长等多久")
    parser.add_argument("--no-wait", action="store_true", help="只入队不等结果（更快，但汇总里没有成败）")
    parser.add_argument("--rebuild-search-docs", action="store_true", help="跑完后重建全部标的搜索文档")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只列出要补跑的标的")
    mode.add_argument("--apply", action="store_true", help="真的入队解析")
    args = parser.parse_args()

    token = api._resolve_token(args.api_base)
    targets = _list_all_targets(args.api_base, token)
    pending = [target for target in targets if _needs_tags(target)]
    tagged = len(targets) - len(pending)
    print(f"[scan] 标的 {len(targets)} 条，已有标签 {tagged} 条，待补跑（A–D 级且无标签）{len(pending)} 条")
    if args.limit:
        pending = pending[: args.limit]
        print(f"[scan] 本次只跑前 {len(pending)} 条（--limit）")
    for target in pending:
        print(f"  - {target['id']}  {str(target.get('target_name') or '')[:24]}  级别 {target.get('target_grade')}")
    if args.dry_run:
        print("[dry-run] 未入队")
        return 0

    summary = {"queued": 0, "succeeded": 0, "failed": 0, "conflict_409": 0, "timeout": 0, "error": 0}
    for index, target in enumerate(pending, start=1):
        target_id = target["id"]
        name = str(target.get("target_name") or "")[:24]
        try:
            api._request_json(
                args.api_base,
                "POST",
                f"/seller-targets/{target_id}/parse",
                token=token,
                json_body={"force": True},
            )
        except api.ApiError as exc:
            message = str(exc)
            if "409" in message:
                summary["conflict_409"] += 1
                print(f"[{index}/{len(pending)}] 409 跳过（调研中或解析中）: {name}")
            else:
                summary["error"] += 1
                print(f"[{index}/{len(pending)}] 入队失败: {name}: {message[:160]}")
            continue
        summary["queued"] += 1
        if args.no_wait:
            print(f"[{index}/{len(pending)}] 已入队: {name}")
        else:
            state = _wait_for_parse(
                args.api_base, token, target_id, poll_seconds=args.poll_seconds, max_wait=args.max_wait_seconds
            )
            key = "succeeded" if state == "succeeded" else "timeout" if state == "timeout" else "failed"
            summary[key] += 1
            print(f"[{index}/{len(pending)}] {state}: {name}")
        if index < len(pending):
            time.sleep(args.interval)

    print(f"[done] {summary}")

    if args.rebuild_search_docs:
        result = api._request_json(
            args.api_base, "POST", "/search-docs/jobs/seller-targets/rebuild", token=token, json_body={}
        )
        print(f"[search-docs] 已入队重建: {str(result)[:200]}")

    if not args.no_wait:
        after = _list_all_targets(args.api_base, token)
        still = [target for target in after if _needs_tags(target)]
        print(f"[verify] 补跑后仍无标签的 A–D 级标的 {len(still)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
