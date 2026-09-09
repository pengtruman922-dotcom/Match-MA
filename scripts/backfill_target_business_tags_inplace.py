"""存量标的的业务标签收敛 —— **只写标签**的容器内版本（方案 0908 §5.3 的修正）。

`backfill_target_business_tags.py` 走 `POST /seller-targets/{id}/parse` 整条重解析，
阿里云试跑 5 条后发现副作用太大：解析器会把调研写的风险摘要压缩改写、把摘要
里的所在地重新判一遍，财务数字虽是同值重写也会在审计链里刷出一串假改动。
75 条里很多风险摘要是调研写的详细文本，不能这么收敛。

这个脚本改成：直接调 `seller_target_parser` 节点配置的模型，只让它从名称 +
业务摘要 + 主要产品 + 交易摘要里写 3~5 个业务标签，然后经统一写入口
`write_seller_target_fields` **只写 `business_tags_json` 一列**（审计与字段来源照常，
搜索文档照常重建），其他字段一个不碰。摘要为空的标的跳过，不从公司名猜。

它需要库与模型密钥，所以在 api 容器里跑（镜像里带 scripts/，或用 stdin 灌进去）：

    cd /opt/match-ma/deploy
    docker compose exec -T api python scripts/backfill_target_business_tags_inplace.py --limit 3
    docker compose exec -T api python scripts/backfill_target_business_tags_inplace.py --limit 3 --apply
    docker compose exec -T api python scripts/backfill_target_business_tags_inplace.py --apply

不带 --apply 时会真的调模型但不写库（看标签质量用）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.db import get_session_factory
from backend.app.jobs.handlers.common import _get_default_node_config
from backend.app.services.business_tags import business_tags_contract_note, normalize_business_tags
from backend.app.services.field_writer import FieldWriteError, WriteProvenance, write_seller_target_fields

NODE_NAME = "seller_target_parser"
SOURCE_LABEL = "业务标签补跑（方案 0908，只写标签）"

SYSTEM_PROMPT = (
    "你是并购撮合平台的标签标注助手。根据给出的公司资料，为这家公司写业务标签。"
    "只输出一个 JSON 对象，形如 {\"business_tags_json\": [\"汽车零部件\", \"商用车车架\"]}，不要 Markdown、不要解释。\n"
    + business_tags_contract_note("seller_target")
    + "\n资料没有说清这家公司做什么时输出 {\"business_tags_json\": []}，绝不从公司名猜业务。"
)


def _pending_targets(db, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select id, target_name, target_subject_name, business_summary, main_products_text, transaction_summary
            from seller_target
            where team_id = :team_id and workspace_id = :workspace_id and deleted_at is null
              and target_grade <> 'E'
              and (jsonb_typeof(business_tags_json) <> 'array' or jsonb_array_length(business_tags_json) = 0)
            order by updated_at desc, id
            """
        ),
        {"team_id": DEFAULT_TEAM_ID, "workspace_id": DEFAULT_WORKSPACE_ID},
    ).mappings().all()
    items = [dict(row) for row in rows]
    return items[:limit] if limit else items


def _material(target: dict[str, Any]) -> str:
    lines = [f"公司名称：{target.get('target_name') or ''}"]
    if target.get("target_subject_name"):
        lines.append(f"标的主体：{target['target_subject_name']}")
    if target.get("business_summary"):
        lines.append(f"业务摘要：{target['business_summary']}")
    if target.get("main_products_text"):
        lines.append(f"主要产品：{target['main_products_text']}")
    if target.get("transaction_summary"):
        lines.append(f"交易摘要：{target['transaction_summary'][:300]}")
    return "\n".join(lines)


def _ask_tags(node: dict[str, Any], material: str) -> list[str]:
    result = call_openai_compatible_chat(
        base_url=node["base_url"],
        api_key_secret_ref=node["api_key_secret_ref"],
        api_key_encrypted=node.get("api_key_encrypted"),
        model_name=node["model_name"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": material + "\n\n输出："},
        ],
        temperature=0.1,
        top_p=node.get("top_p"),
        max_tokens=min(int(node.get("max_tokens") or 400), 400),
        timeout_seconds=int(node.get("timeout_seconds") or 90),
        response_format="json_object",
    )
    payload = result.parsed_output_json or {}
    return normalize_business_tags(payload.get("business_tags_json"))[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="最多处理几条，0 = 全部")
    parser.add_argument("--apply", action="store_true", help="真的写库；不带则只调模型看标签")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()

    session = get_session_factory()()
    try:
        node = _get_default_node_config(session, NODE_NAME)
        targets = _pending_targets(session, args.limit)
        print(f"[scan] 待补标签（A–D 级、无标签）{len(targets)} 条；模型 {node['model_name']}；{'写库' if args.apply else '只看不写'}")
        summary = {"tagged": 0, "skipped_no_material": 0, "empty_from_model": 0, "llm_error": 0, "write_error": 0}
        for index, target in enumerate(targets, start=1):
            name = str(target.get("target_name") or "")[:20]
            if not (target.get("business_summary") or target.get("main_products_text")):
                summary["skipped_no_material"] += 1
                print(f"[{index}/{len(targets)}] 跳过（无摘要无产品）: {name}")
                continue
            try:
                tags = _ask_tags(node, _material(target))
            except LlmCallError as exc:
                summary["llm_error"] += 1
                print(f"[{index}/{len(targets)}] 模型失败: {name}: {str(exc)[:120]}")
                continue
            if not tags:
                summary["empty_from_model"] += 1
                print(f"[{index}/{len(targets)}] 模型未给标签: {name}")
                continue
            print(f"[{index}/{len(targets)}] {name} -> {tags}")
            if args.apply:
                try:
                    write_seller_target_fields(
                        session,
                        UUID(str(target["id"])),
                        {"business_tags_json": tags},
                        provenance=WriteProvenance(
                            source_type="seller_target_parse",
                            actor_user_id=SYSTEM_USER_ID,
                            writer="parse",
                            field_source_label=SOURCE_LABEL,
                            review_status="auto_accepted",
                            source_context={
                                "source_type": "seller_target_parse",
                                "source_label": SOURCE_LABEL,
                                "model_name": node["model_name"],
                            },
                            log_metadata={"source": "backfill_target_business_tags_inplace", "fields": ["business_tags_json"]},
                        ),
                        search_doc_source="seller_target_parse",
                    )
                    session.commit()
                    summary["tagged"] += 1
                except (FieldWriteError, Exception) as exc:  # noqa: BLE001 - 一条失败不该带走整批
                    session.rollback()
                    summary["write_error"] += 1
                    print(f"    写入失败: {str(exc)[:160]}")
            if index < len(targets):
                time.sleep(args.interval)
        print(f"[done] {json.dumps(summary, ensure_ascii=False)}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
