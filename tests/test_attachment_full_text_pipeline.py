"""附件正文从抽取到进模型的全链路不再被截断。

回归背景：一份 10 页年报（14,110 字）曾经这样一路缩水 ——
PDF 检测只采样 5 页 → 落库 4,658 字 → evidence_span 截到 2,000 字 → 模型看到 14%。
主要会计数据表在第 2,306 字，离截断点只差 306 字，于是营收字段永远写不进去。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from backend.app.jobs.handlers import business_update as business_update_module
from backend.app.jobs.handlers.attachment_ocr import _insert_ocr_evidence_span
from backend.app.jobs.handlers.business_update import _build_business_update_attachment_context
from backend.app.jobs.handlers.common import _fetch_seller_targets
from backend.app.services.pdf_inspection import extract_pdf_text, inspect_pdf_text_layer

ATTACHMENT_ID = UUID("00000000-0000-0000-0000-0000000000a1")
PARSED_DOCUMENT_ID = UUID("00000000-0000-0000-0000-0000000000a2")
EVIDENCE_ID = UUID("00000000-0000-0000-0000-0000000000a3")
JOB_ID = UUID("00000000-0000-0000-0000-0000000000a4")
BUSINESS_UPDATE_ID = UUID("00000000-0000-0000-0000-0000000000a5")


class _Result:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict]:
        return self._rows

    def one(self) -> dict:
        return self._rows[0]


class _CaptureDb:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows if rows is not None else [{"id": EVIDENCE_ID}]
        self.sql_text = ""
        self.params: dict = {}

    def execute(self, statement, params=None):
        self.sql_text = str(statement)
        self.params = params or {}
        return _Result(self.rows)


def _pdf_reader_with_pages(monkeypatch, pages: list[str]) -> None:
    class _Page:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class _Reader:
        def __init__(self, _stream) -> None:
            self.pages = [_Page(text) for text in pages]

    monkeypatch.setattr("pypdf.PdfReader", _Reader)


# --- ① PDF：检测只采样，取正文要抽全篇 ------------------------------------


def test_detection_samples_but_extraction_reads_every_page(monkeypatch) -> None:
    pages = [f"第{index}页正文" + "填" * 300 for index in range(1, 11)]
    _pdf_reader_with_pages(monkeypatch, pages)

    detection = inspect_pdf_text_layer(b"%PDF", page_limit=5, min_total_chars=200)
    document = extract_pdf_text(b"%PDF", max_chars=200_000)

    # 检测照旧只看前 5 页 —— 它只需要回答"有没有文字层"。
    assert detection.pdf_kind == "text_pdf"
    assert detection.sampled_page_count == 5
    assert "第10页正文" not in detection.extracted_text

    # 正文必须整篇都在，尤其是采样窗口之外的后半篇。
    assert document.page_count == 10
    assert document.truncated is False
    for index in range(1, 11):
        assert f"第{index}页正文" in document.extracted_text
    assert document.extracted_char_count > detection.extracted_char_count


def test_extraction_flags_truncation_instead_of_dropping_silently(monkeypatch) -> None:
    _pdf_reader_with_pages(monkeypatch, ["甲" * 400, "乙" * 400])

    document = extract_pdf_text(b"%PDF", max_chars=500)

    assert document.truncated is True
    assert document.extracted_char_count == 500


def test_extraction_failure_is_reported_not_raised(monkeypatch) -> None:
    class _Boom:
        def __init__(self, _stream) -> None:
            raise ValueError("broken pdf")

    monkeypatch.setattr("pypdf.PdfReader", _Boom)

    document = extract_pdf_text(b"%PDF", max_chars=200_000)

    assert document.extracted_text == ""
    assert document.error_message == "broken pdf"


# --- ② evidence_span 不再砍到 2000 字 --------------------------------------


def test_evidence_span_keeps_the_whole_document(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.jobs.handlers.attachment_ocr.get_settings",
        lambda: SimpleNamespace(attachment_text_capture_max_bytes=200_000),
    )
    body = "营收" * 5_000  # 10,000 字，远超旧的 2000 上限

    db = _CaptureDb()
    _insert_ocr_evidence_span(
        db,
        attachment_id=ATTACHMENT_ID,
        parsed_document_id=PARSED_DOCUMENT_ID,
        job_id=JOB_ID,
        text_excerpt=body,
    )

    assert db.params["text_excerpt"] == body
    assert db.params["char_end"] == len(body)


# --- ③ 进提示词的正文：只放一份，超预算要留痕 -----------------------------


def _attachment_context_db(text_excerpt: str) -> _CaptureDb:
    return _CaptureDb(
        [
            {
                "attachment_id": ATTACHMENT_ID,
                "file_name": "年报摘要.pdf",
                "file_type": "pdf",
                "mime_type": "application/pdf",
                "parse_status": "parsed",
                "link_type": "source_document",
                "parsed_document_id": PARSED_DOCUMENT_ID,
                "parsed_document_status": "parsed",
                "evidence_id": EVIDENCE_ID,
                "text_excerpt": text_excerpt,
                "page_no": 1,
                "char_start": 0,
                "char_end": len(text_excerpt),
            }
        ]
    )


def test_attachment_context_sends_full_text_once(monkeypatch) -> None:
    monkeypatch.setattr(
        business_update_module,
        "get_settings",
        lambda: SimpleNamespace(attachment_prompt_text_max_chars=60_000),
    )
    body = "".join(f"第{index}段 营业收入 579,187,676.55 " for index in range(400))

    context = _build_business_update_attachment_context(
        _attachment_context_db(body), BUSINESS_UPDATE_ID
    )

    # raw_text 那一份是全的。
    assert body.strip() in context["combined_text"]
    assert context["combined_text_truncated"] is False

    # context_json 那一份必须是短的：两处都渲进提示词，全文放两遍等于白烧一倍 token。
    evidence = context["attachments"][0]["evidence_spans"][0]
    assert len(evidence["text_excerpt"]) <= 200
    assert evidence["text_char_count"] == len(body)


def test_attachment_context_flags_budget_truncation(monkeypatch) -> None:
    monkeypatch.setattr(
        business_update_module,
        "get_settings",
        lambda: SimpleNamespace(attachment_prompt_text_max_chars=50),
    )

    context = _build_business_update_attachment_context(
        _attachment_context_db("甲" * 500), BUSINESS_UPDATE_ID
    )

    assert context["combined_text_truncated"] is True
    assert "甲" * 50 in context["combined_text"]
    assert "甲" * 51 not in context["combined_text"]


# --- ④ 模型的字段词汇表必须覆盖可写的财务字段 -----------------------------

# 提示词说的是 "use canonical seller_target fields from context"：没进 context 的
# 字段，模型不知道它存在。这几列都是 parse 可写的，缺一个就等于永远写不进去。
FINANCIAL_CONTEXT_COLUMNS = (
    "current_revenue_yuan",
    "current_net_profit_yuan",
    "current_total_profit_yuan",
    "current_assets_yuan",
    "current_debt_ratio",
    "current_operating_cash_flow_yuan",
    "financial_period_label",
    "market_cap_yuan",
    "profitability_status",
    "cash_flow_status",
    "operation_stability_status",
)


def test_seller_target_context_exposes_writable_financial_fields() -> None:
    db = _CaptureDb([])
    _fetch_seller_targets(db, [ATTACHMENT_ID])

    for column in FINANCIAL_CONTEXT_COLUMNS:
        assert column in db.sql_text, f"{column} 不在模型可见的字段清单里"


def test_context_financial_columns_are_parse_writable() -> None:
    from backend.app.registry.indicators import writable_columns

    parse_writable = writable_columns("parse")
    for column in FINANCIAL_CONTEXT_COLUMNS:
        assert column in parse_writable, f"{column} 不是 parse 可写，放进 context 会被写入层拒掉"
