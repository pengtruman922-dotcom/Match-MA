from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class Doc2xCallError(RuntimeError):
    pass


@dataclass(frozen=True)
class Doc2xPreuploadResult:
    uid: str
    upload_url: str
    raw_response: dict[str, Any]
    latency_ms: int


@dataclass(frozen=True)
class Doc2xStatusResult:
    status: str
    progress: int | None
    markdown_text: str
    page_count: int | None
    raw_response: dict[str, Any]
    detail: Any
    latency_ms: int


def submit_doc2x_pdf(
    *,
    base_url: str,
    api_key: str,
    file_bytes: bytes,
    model: str | None = None,
    timeout_seconds: int = 60,
) -> Doc2xPreuploadResult:
    started = time.perf_counter()
    preupload = _preupload(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    _put_file(preupload.upload_url, file_bytes=file_bytes, timeout_seconds=timeout_seconds)
    latency_ms = int((time.perf_counter() - started) * 1000)
    return Doc2xPreuploadResult(
        uid=preupload.uid,
        upload_url=preupload.upload_url,
        raw_response=preupload.raw_response,
        latency_ms=latency_ms,
    )


def poll_doc2x_status(
    *,
    base_url: str,
    api_key: str,
    uid: str,
    timeout_seconds: int = 30,
) -> Doc2xStatusResult:
    started = time.perf_counter()
    url = base_url.rstrip("/") + f"/api/v2/parse/status?uid={uid}"
    response_json = _request_json(
        url,
        method="GET",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    data = _success_data(response_json, operation="get status")
    status_value = str(data.get("status") or "")
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    pages = result.get("pages") if isinstance(result.get("pages"), list) else []
    markdown_parts: list[str] = []
    for page in pages:
        if isinstance(page, dict) and str(page.get("md") or "").strip():
            markdown_parts.append(str(page.get("md")).strip())
    latency_ms = int((time.perf_counter() - started) * 1000)
    return Doc2xStatusResult(
        status=status_value,
        progress=_optional_int(data.get("progress")),
        markdown_text="\n\n".join(markdown_parts).strip(),
        page_count=len(pages) if pages else None,
        raw_response=response_json,
        detail=data.get("detail"),
        latency_ms=latency_ms,
    )


def _preupload(
    *,
    base_url: str,
    api_key: str,
    model: str | None,
    timeout_seconds: int,
) -> Doc2xPreuploadResult:
    started = time.perf_counter()
    url = base_url.rstrip("/") + "/api/v2/parse/preupload"
    body = {"model": model} if model else None
    response_json = _request_json(
        url,
        method="POST",
        api_key=api_key,
        json_body=body,
        timeout_seconds=timeout_seconds,
    )
    data = _success_data(response_json, operation="get preupload url")
    uid = str(data.get("uid") or "").strip()
    upload_url = str(data.get("url") or "").strip()
    if not uid or not upload_url:
        raise Doc2xCallError("Doc2X preupload response missing uid or url.")
    latency_ms = int((time.perf_counter() - started) * 1000)
    return Doc2xPreuploadResult(
        uid=uid,
        upload_url=upload_url,
        raw_response=response_json,
        latency_ms=latency_ms,
    )


def _put_file(upload_url: str, *, file_bytes: bytes, timeout_seconds: int) -> None:
    req = request.Request(upload_url, data=file_bytes, method="PUT")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            if response.status != 200:
                body = response.read().decode("utf-8", errors="replace")
                raise Doc2xCallError(f"Doc2X upload failed HTTP {response.status}: {body[:500]}")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise Doc2xCallError(f"Doc2X upload failed HTTP {exc.code}: {body[:500]}") from exc
    except error.URLError as exc:
        raise Doc2xCallError(f"Doc2X upload request failed: {exc.reason}") from exc


def _request_json(
    url: str,
    *,
    method: str,
    api_key: str,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: int,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = None
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise Doc2xCallError(f"Doc2X HTTP {exc.code}: {body[:500]}") from exc
    except error.URLError as exc:
        raise Doc2xCallError(f"Doc2X request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Doc2xCallError(f"Doc2X response is not valid JSON: {body[:500]}") from exc
    if not isinstance(parsed, dict):
        raise Doc2xCallError("Doc2X response JSON is not an object.")
    return parsed


def _success_data(response_json: dict[str, Any], *, operation: str) -> dict[str, Any]:
    if response_json.get("code") != "success":
        raise Doc2xCallError(f"Doc2X {operation} failed: {_safe_error(response_json)}")
    data = response_json.get("data")
    if not isinstance(data, dict):
        raise Doc2xCallError(f"Doc2X {operation} response missing data object.")
    return data


def _safe_error(response_json: dict[str, Any]) -> str:
    redacted = dict(response_json)
    for key in ("api_key", "Authorization", "authorization"):
        if key in redacted:
            redacted[key] = "***"
    return json.dumps(redacted, ensure_ascii=False)[:500]


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
