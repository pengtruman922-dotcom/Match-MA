"""One-off cleanup: re-summarize seller targets whose business_summary is raw pasted text.

Before this change the target-create modal wrote the user's raw supplement text
straight into business_summary; the AI parse may or may not have overwritten it
later. This script finds targets whose business_summary still looks like a raw
paste (long text or multi-line) and re-triggers the seller_target_parse job so
the LLM rewrites a short summary (the apply path now caps business_summary at
300 chars).

Usage (run from repo root so .match-ma-local-auth.json is picked up):

  python scripts/cleanup_business_summaries.py           # dry run: list suspects
  python scripts/cleanup_business_summaries.py --apply   # trigger re-parse jobs
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from match_ma_api_tools import ApiError, _request_json, _resolve_token

DEFAULT_API_BASE = os.getenv(
    "MATCH_MA_API_BASE", "https://match-ma-production.up.railway.app/api/v1"
)

# A hand-written or AI-written summary should be one or two sentences; raw
# pastes are long and usually contain line breaks.
MAX_SUMMARY_CHARS = 200


def looks_like_raw_paste(summary: str) -> bool:
    text = summary.strip()
    if not text:
        return False
    return len(text) > MAX_SUMMARY_CHARS or "\n" in text


def iter_targets(api_base: str, token: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _request_json(
            api_base,
            "GET",
            "/seller-targets",
            token=token,
            query={"limit": 200, "offset": offset},
        )
        batch = page.get("items") or []
        items.extend(batch)
        offset += len(batch)
        if offset >= int(page.get("total") or 0) or not batch:
            return items


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--apply", action="store_true", help="trigger re-parse jobs (default: dry run)")
    args = parser.parse_args()

    token = _resolve_token(args.api_base)
    targets = iter_targets(args.api_base, token)
    suspects = [
        target
        for target in targets
        if looks_like_raw_paste(str(target.get("business_summary") or ""))
    ]

    print(f"共 {len(targets)} 个标的，其中 {len(suspects)} 个 business_summary 疑似原文粘贴：")
    for target in suspects:
        summary = str(target.get("business_summary") or "").replace("\n", " ")
        print(f"- {target['target_name']} ({target['id']}): {len(summary)} 字 | {summary[:60]}...")

    if not args.apply:
        if suspects:
            print("\n干跑模式，未触发任何解析。加 --apply 重新生成摘要。")
        return 0

    failures: list[str] = []
    for target in suspects:
        try:
            job = _request_json(
                args.api_base,
                "POST",
                f"/seller-targets/{target['id']}/parse",
                token=token,
                json_body={"force": True},
            )
            print(f"[queued] {target['target_name']} -> job {job.get('job_id')} ({job.get('status')})")
        except ApiError as exc:
            failures.append(f"{target['target_name']}: {exc}")
            print(f"[failed] {target['target_name']}: {exc}")

    if failures:
        print(f"\n{len(failures)} 个触发失败，可重跑本脚本重试。")
        return 1
    print("\n已全部进入解析队列，几分钟后可在标的列表查看新摘要（状态列会显示解析中）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
