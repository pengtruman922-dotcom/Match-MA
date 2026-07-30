from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error, parse, request

DEFAULT_API_BASE = "https://match-ma-production.up.railway.app/api/v1"
DEFAULT_PINDA_DIR = Path(
    r"C:\Users\MP\search-toolkit\Match-MA\测试样本\业务更新文本\标的更新或新建\拼哒出行"
)
PINDA_FILES = [
    "88c4395f6f66ed97f3ebfa24e2078abb.jpg",
    "b59056693335f6e779ff20f6715d5fbd.jpg",
    "拼哒出行介绍V1.8.pdf",
    "拼哒宣传文.txt",
]
BEIDA_INTENT_ID = "3d3a30cb-b850-4849-a6e3-a8d589af0257"
BEIDA_ATTACHMENT_ID = "37d34f41-2631-4231-8648-6ae27668860a"


class ApiError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Match-MA production validation helpers.")
    parser.add_argument(
        "--api-base",
        default=os.getenv("MATCH_MA_API_BASE", DEFAULT_API_BASE),
        help="API base URL. Defaults to production API.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pinda = subparsers.add_parser("run-pinda-sample", help="Upload and poll the Pinda mixed sample.")
    pinda.add_argument("--sample-dir", type=Path, default=DEFAULT_PINDA_DIR)
    pinda.add_argument("--poll-seconds", type=int, default=12)
    pinda.add_argument("--max-wait-seconds", type=int, default=900)
    pinda.add_argument("--no-auto-process", action="store_true")

    failures = subparsers.add_parser("failures", help="Preview or archive failed background jobs.")
    failures.add_argument("--lookback-hours", type=int, default=720)
    failures.add_argument("--limit", type=int, default=50)
    failures.add_argument("--include-ignored", action="store_true")
    failures.add_argument("--include-archived", action="store_true")
    failures.add_argument("--include-test-data", action="store_true")
    failures.add_argument(
        "--job-id",
        action="append",
        default=[],
        help="Limit operations to one or more explicit job ids. Can be passed multiple times.",
    )
    failures.add_argument("--archive", action="store_true", help="Archive non-archived returned failures.")
    failures.add_argument("--mark-test-data", action="store_true", help="Mark returned failures as test data.")
    failures.add_argument(
        "--reason",
        default="Historical failure triaged after deployed fixes; retained for audit.",
        help="Archive reason when --archive is used.",
    )
    failures.add_argument("--test-label", default="historical_validation", help="Label used by --mark-test-data.")

    repair = subparsers.add_parser("repair-stuck", help="Dry-run or apply the audited stuck-state repair.")
    repair.add_argument("--apply", action="store_true")

    recover = subparsers.add_parser("recover-buyer-intent", help="Retry an original attachment and verify the full buyer-intent chain.")
    recover.add_argument("--buyer-intent-id", default=BEIDA_INTENT_ID)
    recover.add_argument("--attachment-id", default=BEIDA_ATTACHMENT_ID)
    recover.add_argument("--retry", action="store_true")
    recover.add_argument("--poll-seconds", type=int, default=8)
    recover.add_argument("--max-wait-seconds", type=int, default=900)

    health = subparsers.add_parser("health", help="Read health or wait for a deployed commit hash.")
    health.add_argument("--expect-commit")
    health.add_argument("--poll-seconds", type=int, default=10)
    health.add_argument("--max-wait-seconds", type=int, default=600)

    args = parser.parse_args()
    api_base = args.api_base.rstrip("/")
    try:
        token = _resolve_token(api_base)
        if args.command == "run-pinda-sample":
            run_pinda_sample(
                api_base=api_base,
                token=token,
                sample_dir=args.sample_dir,
                poll_seconds=args.poll_seconds,
                max_wait_seconds=args.max_wait_seconds,
                auto_process=not args.no_auto_process,
            )
        elif args.command == "failures":
            handle_failures(api_base=api_base, token=token, args=args)
        elif args.command == "repair-stuck":
            print(json.dumps(_request_json(
                api_base, "POST", "/background-jobs/repair-stuck-processing",
                token=token, json_body={"apply": args.apply},
            ), ensure_ascii=False, indent=2))
        elif args.command == "recover-buyer-intent":
            recover_buyer_intent(api_base=api_base, token=token, args=args)
        elif args.command == "health":
            wait_for_health(api_base=api_base, token=token, args=args)
    except ApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


def run_pinda_sample(
    *,
    api_base: str,
    token: str,
    sample_dir: Path,
    poll_seconds: int,
    max_wait_seconds: int,
    auto_process: bool,
) -> None:
    sample_dir = sample_dir.resolve()
    paths = [sample_dir / name for name in PINDA_FILES]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise ApiError("Missing sample files: " + ", ".join(missing))

    text_path = sample_dir / "拼哒宣传文.txt"
    raw_text = text_path.read_text(encoding="utf-8-sig").strip()
    metadata = {
        "test_data": True,
        "is_test_data": True,
        "sample_label": "pinda_mixed_validation",
        "sample_object": "pinda_chuxing",
        "sample_group": "seller_target_update_or_create",
        "source": "codex_sample_runner",
        "runner_version": 1,
    }
    fields = {
        "raw_text": raw_text,
        "input_type": "mixed",
        "auto_process": "true" if auto_process else "false",
        "process_after_ocr": "true",
        "include_attachment_text": "true",
        "auto_parse_linked_objects": "false",
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }

    upload_response = _request_json(
        api_base,
        "POST",
        "/business-updates/upload",
        token=token,
        multipart=_multipart_body(fields, paths),
    )
    business_update = upload_response.get("business_update") or {}
    business_update_id = business_update.get("id")
    if not business_update_id:
        raise ApiError("Upload response did not include business_update.id")

    print(
        json.dumps(
            {
                "uploaded": True,
                "business_update_id": business_update_id,
                "processing_status": business_update.get("processing_status"),
                "uploaded_attachment_count": len(upload_response.get("uploaded_attachment_ids") or []),
                "ocr_attachment_count": len(upload_response.get("ocr_attachment_ids") or []),
                "multimodal_image_count": len(upload_response.get("multimodal_image_attachment_ids") or []),
                "skipped_ocr_count": len(upload_response.get("skipped_ocr_attachment_ids") or []),
                "ocr_job_count": len(upload_response.get("ocr_jobs") or []),
                "process_job_id": (upload_response.get("process_job") or {}).get("id"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    deadline = time.time() + max(max_wait_seconds, 1)
    latest: dict[str, Any] | None = None
    while True:
        latest = _request_json(api_base, "GET", f"/business-updates/{business_update_id}/review-page", token=token)
        summary = _compact_review_page(latest)
        print(json.dumps(summary, ensure_ascii=False))
        if _review_terminal_enough(latest) or time.time() >= deadline:
            break
        time.sleep(max(poll_seconds, 1))

    sample_runs = _request_json(
        api_base,
        "GET",
        "/business-updates/summary/sample-runs",
        token=token,
        query={"lookback_hours": 720, "limit": 10, "sample_label": "pinda_mixed_validation"},
    )
    print(
        json.dumps(
            {
                "final_review": _compact_review_page(latest or {}),
                "sample_runs_total": sample_runs.get("total_count"),
                "latest_sample_run": (sample_runs.get("runs") or [None])[0],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def wait_for_health(*, api_base: str, token: str, args: argparse.Namespace) -> None:
    deadline = time.monotonic() + args.max_wait_seconds
    while True:
        health = _request_json(api_base, "GET", "/health", token=token)
        railway = health.get("railway") or {}
        commit = str(
            health.get("commit") or health.get("commit_hash") or health.get("git_commit")
            or railway.get("git_commit_sha") or ""
        )
        print(json.dumps(health, ensure_ascii=False))
        if not args.expect_commit or commit.startswith(args.expect_commit) or args.expect_commit.startswith(commit):
            return
        if time.monotonic() >= deadline:
            raise ApiError(f"Health commit did not switch to {args.expect_commit}; latest was {commit or 'missing'}.")
        time.sleep(args.poll_seconds)


def recover_buyer_intent(*, api_base: str, token: str, args: argparse.Namespace) -> None:
    if args.retry:
        retry = _request_json(
            api_base,
            "POST",
            f"/attachments/{args.attachment_id}/ocr",
            token=token,
            json_body={"force": True},
        )
        print(json.dumps({"retry": retry}, ensure_ascii=False, indent=2))

    deadline = time.monotonic() + args.max_wait_seconds
    latest: dict[str, Any] = {}
    while True:
        parse_status = _request_json(
            api_base, "GET", f"/buyer-intents/{args.buyer_intent_id}/parse-status", token=token
        )
        attachment_items = _request_json(
            api_base,
            "GET",
            "/attachments",
            token=token,
            query={"entity_type": "buyer_intent", "entity_id": args.buyer_intent_id, "limit": 100},
        )
        batches = _request_json(
            api_base,
            "GET",
            "/update-logs/batches",
            token=token,
            query={"entity_type": "buyer_intent", "entity_id": args.buyer_intent_id, "limit": 50},
        )
        attachment = next(
            (item for item in attachment_items if str(item.get("id")) == args.attachment_id), None
        )
        state = parse_status.get("processing_state") or {}
        source_update_id = state.get("source_business_update_id")
        batch = next(
            (item for item in batches.get("items", []) if str(item.get("source_id")) == str(source_update_id)),
            None,
        )
        latest = {
            "buyer_intent_id": args.buyer_intent_id,
            "processing_state": state,
            "attachment": attachment,
            "business_update_batch": batch,
            "latest_job": parse_status.get("latest_job"),
            "latest_trace": parse_status.get("latest_trace"),
            "structured_fields": {
                key: parse_status.get("buyer_intent", {}).get(key)
                for key in (
                    "intent_summary", "industries_json", "industry_l2_json",
                    "region_constraints_json", "min_net_profit_yuan", "preferred_listed_status",
                    "requires_control", "transaction_types_json", "needs_confirmation_json",
                )
            },
        }
        print(json.dumps({
            "overall_status": state.get("overall_status"),
            "current_stage": state.get("current_stage"),
            "attachment_status": (attachment or {}).get("content_extraction_status"),
            "batch_status": (batch or {}).get("status"),
        }, ensure_ascii=False))
        attachment_terminal = (attachment or {}).get("content_extraction_status") in {"succeeded", "failed", "skipped"}
        terminal = state.get("overall_status") == "failed" or _buyer_recovery_succeeded(latest)
        if terminal and attachment_terminal:
            break
        if time.monotonic() >= deadline:
            raise ApiError("Buyer-intent recovery did not reach a terminal state before timeout.")
        time.sleep(args.poll_seconds)
    print(json.dumps(latest, ensure_ascii=False, indent=2))
    if not _buyer_recovery_succeeded(latest):
        raise ApiError("Buyer-intent recovery reached a non-success terminal state.")


def _buyer_recovery_succeeded(latest: dict[str, Any]) -> bool:
    state = latest.get("processing_state") or {}
    attachment = latest.get("attachment") or {}
    batch = latest.get("business_update_batch") or {}
    return bool(
        state.get("overall_status") == "succeeded"
        and attachment.get("content_extraction_status") == "succeeded"
        and batch.get("status") == "applied"
        and state.get("ai_parse_status") == "succeeded"
        and state.get("semantic_parse_status") == "succeeded"
        and state.get("normalization_status") == "succeeded"
        and state.get("write_status") == "succeeded"
    )


def handle_failures(*, api_base: str, token: str, args: argparse.Namespace) -> None:
    summary = _request_json(
        api_base,
        "GET",
        "/background-jobs/summary/failures",
        token=token,
        query={
            "lookback_hours": args.lookback_hours,
            "limit": args.limit,
            "include_ignored": args.include_ignored,
            "include_archived": args.include_archived,
            "include_test_data": args.include_test_data,
        },
    )
    failures = summary.get("recent_failures") or []
    job_ids = {str(item) for item in args.job_id}
    if job_ids:
        failures = [job for job in failures if str(job.get("id")) in job_ids]

    preview = {
        "lookback_hours": summary.get("lookback_hours"),
        "include_ignored": summary.get("include_ignored"),
        "include_archived": summary.get("include_archived"),
        "include_test_data": summary.get("include_test_data"),
        "totals": summary.get("totals"),
        "failures": [
            {
                "id": job.get("id"),
                "queue_name": job.get("queue_name"),
                "job_type": job.get("job_type"),
                "failure_category": job.get("failure_category"),
                "failure_summary": job.get("failure_summary"),
                "can_retry": job.get("can_retry"),
                "ignored": job.get("ignored"),
                "archived": job.get("archived"),
                "is_test_data": job.get("is_test_data"),
                "related_entity_ref": job.get("related_entity_ref"),
            }
            for job in failures
        ],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    if not args.archive and not args.mark_test_data:
        return

    archived_jobs: list[dict[str, Any]] = []
    test_marked_jobs: list[dict[str, Any]] = []
    for job in failures:
        if args.mark_test_data and not job.get("is_test_data"):
            marked = _request_json(
                api_base,
                "POST",
                f"/background-jobs/{job['id']}/mark-test-data",
                token=token,
                json_body={"label": args.test_label, "reason": args.reason},
            )
            test_marked_jobs.append(_compact_mutated_job(marked))
        if args.archive and not job.get("archived"):
            archived = _request_json(
                api_base,
                "POST",
                f"/background-jobs/{job['id']}/archive",
                token=token,
                json_body={"reason": args.reason},
            )
            archived_jobs.append(_compact_mutated_job(archived))
    print(
        json.dumps(
            {
                "archived_count": len(archived_jobs),
                "archived_jobs": archived_jobs,
                "test_marked_count": len(test_marked_jobs),
                "test_marked_jobs": test_marked_jobs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _resolve_token(api_base: str) -> str:
    local_auth = _load_local_auth_file()
    token = _clean_secret(
        os.getenv("MATCH_MA_ADMIN_TOKEN")
        or os.getenv("MATCH_MA_ACCESS_TOKEN")
        or os.getenv("ADMIN_TOKEN")
        or local_auth.get("token")
        or local_auth.get("admin_token")
        or local_auth.get("access_token")
    )
    if token:
        return token

    username = (
        os.getenv("MATCH_MA_SAMPLE_USERNAME")
        or os.getenv("MATCH_MA_ADMIN_USERNAME")
        or os.getenv("ADMIN_USERNAME")
        or str(local_auth.get("username") or "")
        or "admin"
    )
    password = _clean_secret(
        os.getenv("MATCH_MA_SAMPLE_PASSWORD")
        or os.getenv("MATCH_MA_ADMIN_PASSWORD")
        or os.getenv("ADMIN_PASSWORD")
        or local_auth.get("password")
        or local_auth.get("admin_password")
    )
    if not password:
        raise ApiError(
            "No auth secret found. Set MATCH_MA_ADMIN_TOKEN, or set MATCH_MA_SAMPLE_PASSWORD "
            "(optionally MATCH_MA_SAMPLE_USERNAME) in this PowerShell session. You may also create "
            ".match-ma-local-auth.json with {\"token\":\"...\"} or {\"username\":\"admin\",\"password\":\"...\"}; "
            "this file is git-ignored."
        )
    response = _request_json(
        api_base,
        "POST",
        "/auth/login",
        token=None,
        json_body={"username": username, "password": password},
    )
    access_token = _clean_secret(response.get("access_token"))
    if not access_token:
        raise ApiError("Login response did not include access_token.")
    return access_token


def _load_local_auth_file() -> dict[str, Any]:
    path = Path.cwd() / ".match-ma-local-auth.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise ApiError(f"Could not read {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ApiError(f"{path.name} must contain a JSON object.")
    return data


def _request_json(
    api_base: str,
    method: str,
    path: str,
    *,
    token: str | None,
    query: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    multipart: tuple[bytes, str] | None = None,
) -> dict[str, Any]:
    url = f"{api_base}{path}"
    if query:
        clean_query = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in query.items()}
        url = f"{url}?{parse.urlencode(clean_query)}"

    data: bytes | None = None
    headers: dict[str, str] = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if multipart is not None:
        data, content_type = multipart
        headers["Content-Type"] = content_type

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as response:
            raw = response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        sanitized = body.replace(_clean_secret(token) or "", "[REDACTED]")
        raise ApiError(f"API {exc.code} {method} {path}: {sanitized[:1000]}") from exc
    except error.URLError as exc:
        raise ApiError(f"Network error calling {method} {path}: {exc}") from exc
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _multipart_body(fields: dict[str, str], file_paths: list[Path]) -> tuple[bytes, str]:
    boundary = f"----match-ma-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for path in file_paths:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="files"; filename="{path.name}"\r\n'.encode(),
                f"Content-Type: {mime_type}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _compact_review_page(review: dict[str, Any]) -> dict[str, Any]:
    business_update = review.get("business_update") or {}
    overview = review.get("overview") or {}
    attachments = review.get("attachments") or []
    jobs = review.get("jobs") or []
    traces = review.get("traces") or []
    return {
        "business_update_id": business_update.get("id"),
        "processing_status": business_update.get("processing_status"),
        "overview": {
            key: overview.get(key)
            for key in [
                "action_count",
                "pending_review_count",
                "auto_applied_count",
                "failed_job_count",
                "running_job_count",
                "trace_count",
                "attachment_count",
            ]
            if key in overview
        },
        "attachments": [
            {
                "id": item.get("id"),
                "file_name": item.get("file_name"),
                "file_type": item.get("file_type"),
                "parse_status": item.get("parse_status"),
                "parse_readiness": item.get("parse_readiness"),
                "latest_job": _compact_job(item.get("latest_job") or {}),
                "parsed_document_id": (item.get("latest_parsed_document") or {}).get("id"),
                "evidence_id": (item.get("latest_evidence") or {}).get("id"),
            }
            for item in attachments
        ],
        "jobs": [_compact_job(item) for item in jobs],
        "failed_jobs": [_compact_job(item) for item in jobs if item.get("status") == "failed"],
        "trace_count": len(traces),
        "failed_trace_count": len([item for item in traces if item.get("status") == "failed" or item.get("error_code")]),
    }


def _compact_job(job: dict[str, Any]) -> dict[str, Any] | None:
    if not job:
        return None
    return {
        "id": job.get("id"),
        "job_type": job.get("job_type"),
        "queue_name": job.get("queue_name"),
        "status": job.get("status"),
        "error_code": job.get("error_code"),
        "error_message": _truncate(job.get("error_message"), 220),
    }


def _compact_mutated_job(job: dict[str, Any]) -> dict[str, Any]:
    metadata = job.get("metadata_json") or {}
    return {
        "id": job.get("id"),
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "archived": metadata.get("archived") is True,
        "is_test_data": metadata.get("is_test_data") is True,
    }


def _review_terminal_enough(review: dict[str, Any]) -> bool:
    business_update = review.get("business_update") or {}
    jobs = review.get("jobs") or []
    attachments = review.get("attachments") or []
    if any(job.get("status") in {"queued", "running", "retry_waiting"} for job in jobs):
        return False
    if any(item.get("parse_status") in {"pending", "parsing"} for item in attachments):
        return False
    return business_update.get("processing_status") in {"parsed", "failed", "needs_review", "applied"}


def _truncate(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _clean_secret(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("<>").strip()
    for _ in range(3):
        previous = text
        if (
            (text.startswith('"') and text.endswith('"'))
            or (text.startswith("'") and text.endswith("'"))
        ):
            text = text[1:-1].strip()
        if text.lower().startswith("authorization:"):
            text = text.split(":", 1)[1].strip()
        if text.lower().startswith("bearer "):
            text = text[7:].strip()
        text = text.strip().strip("<>").strip()
        if text == previous:
            break
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
