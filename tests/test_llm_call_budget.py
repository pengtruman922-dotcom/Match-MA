"""缓冲式模型调用的墙钟预算。

`urlopen(timeout=...)` 只约束单次 socket 操作。流式那一支的 docstring 早就写明
了这件事并自己掐表，但缓冲式一直只有那道 per-op 超时 —— 而所有非流式节点（解析、
调研、深评、归一）都走缓冲式。

生产实测（2026-08-27）：一条 1462 字的买家需求，`buyer_intent_semantic_parser`
配 300 秒，实跑 26 分钟未返回；job 一直 running，trace 一条没有（trace 在调用返回
后才写），前端一直停在「语义解析中」，而且**没有任何报错**——因为确实没超时。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat


class _Response:
    """按块喂数据的假响应。read(n) 的次数就是墙钟的检查次数。"""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.reads = 0
        self.closed = False

    def read(self, size: int | None = None) -> bytes:
        self.reads += 1
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _call(monkeypatch: pytest.MonkeyPatch, response: _Response, *, timeout_seconds: int = 300):
    import backend.app.ai.llm_client as client

    monkeypatch.setattr(client.request, "urlopen", lambda *_a, **_k: response)
    monkeypatch.setattr(client, "_get_api_key", lambda *_a, **_k: "k")
    return call_openai_compatible_chat(
        base_url="https://example.invalid/v1",
        api_key_secret_ref="ref",
        model_name="m",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        top_p=0.9,
        max_tokens=None,
        timeout_seconds=timeout_seconds,
    )


def _payload(text: str) -> bytes:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode("utf-8")


def test_a_reply_inside_the_budget_is_read_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app.ai.llm_client as client

    monkeypatch.setattr(client.time, "perf_counter", lambda: 0.0)
    body = _payload("你好")
    response = _Response([body[:10], body[10:]])

    result = _call(monkeypatch, response)

    assert result.raw_output_text == "你好"


def test_a_server_dripping_bytes_forever_is_hung_up_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """每次 read 都在超时内返回，但整体早已超预算 —— 这正是生产里那 26 分钟。"""
    import backend.app.ai.llm_client as client

    ticks = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr(client.time, "perf_counter", lambda: next(ticks, 999.0))
    response = _Response([b'{"cho', b'ices"', b":[]}"])

    with pytest.raises(LlmCallError) as raised:
        _call(monkeypatch, response, timeout_seconds=300)

    message = str(raised.value)
    assert "budget of 300s" in message
    # 报错要带「已读多少」：否则分不清「一个字节都没来」和「读到一半卡住」。
    assert "字节" in message


def test_the_budget_error_is_an_llm_call_error_so_the_failure_gets_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """裸 TimeoutError 会绕过调用方的 except LlmCallError，失败分支写 trace 的代码
    就不执行 —— 一次挂死什么记录都不留。这条和文件里那段注释是同一个理由。"""
    import backend.app.ai.llm_client as client

    ticks = iter([0.0, 999.0])
    monkeypatch.setattr(client.time, "perf_counter", lambda: next(ticks, 999.0))

    with pytest.raises(LlmCallError):
        _call(monkeypatch, _Response([b"{}"]))


def test_reading_is_chunked_rather_than_one_unbounded_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """一次 read() 读到底的话，中间没有任何地方能检查墙钟。"""
    import backend.app.ai.llm_client as client

    monkeypatch.setattr(client.time, "perf_counter", lambda: 0.0)
    body = _payload("ok")
    response = _Response([body[:5], body[5:10], body[10:]])

    _call(monkeypatch, response)

    # 3 块内容 + 1 次读到 EOF
    assert response.reads == 4
