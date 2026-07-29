from io import BytesIO
from uuid import UUID

from openpyxl import Workbook

from backend.app.api.routes.data_dictionaries import _apply_import_rows, _validate_import_rows
from backend.app.services.industry_dictionary_import import parse_industry_import


def test_parse_csv_supports_chinese_headers_and_alias_separators() -> None:
    content = "一级行业,二级行业,别名,状态\n制造与工业,模具制造,精密模具、模具加工,启用\n".encode("utf-8")

    rows = parse_industry_import("industry.csv", content)

    assert rows == [
        {
            "row_number": 2,
            "l1": "制造与工业",
            "l2": "模具制造",
            "aliases": ["精密模具", "模具加工"],
            "active": True,
        }
    ]


def test_parse_xlsx_supports_l1_only_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["一级行业", "二级行业", "别名", "状态"])
    sheet.append(["能源", None, "新能源产业", "启用"])
    content = BytesIO()
    workbook.save(content)
    workbook.close()

    rows = parse_industry_import("industry.xlsx", content.getvalue())

    assert rows[0]["l1"] == "能源"
    assert rows[0]["l2"] is None
    assert rows[0]["aliases"] == ["新能源产业"]


class _MappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _DictionaryDb:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, _statement, _params):
        return _MappingsResult(self.rows)


def test_import_preview_is_idempotent_for_existing_alias_and_repeated_row() -> None:
    l1_id = UUID("00000000-0000-0000-0000-000000000001")
    l2_id = UUID("00000000-0000-0000-0000-000000000002")
    alias_id = UUID("00000000-0000-0000-0000-000000000003")
    db = _DictionaryDb(
        [
            {"id": l1_id, "term": "制造与工业", "level": "l1", "l1_name": "制造与工业", "parent_id": None, "canonical_term_id": None},
            {"id": l2_id, "term": "模具制造", "level": "l2", "l1_name": "制造与工业", "parent_id": l1_id, "canonical_term_id": None},
            {"id": alias_id, "term": "精密模具", "level": "alias", "l1_name": "制造与工业", "parent_id": None, "canonical_term_id": l2_id},
        ]
    )
    rows = [
        {"row_number": 2, "l1": "制造与工业", "l2": "模具制造", "aliases": ["精密模具"], "active": True},
        {"row_number": 3, "l1": "制造与工业", "l2": "模具制造", "aliases": ["精密模具"], "active": True},
    ]

    preview = _validate_import_rows(db, rows)

    assert [row["status"] for row in preview] == ["ready", "ready"]


def test_import_preview_rejects_alias_reassignment() -> None:
    l1_id = UUID("00000000-0000-0000-0000-000000000001")
    l2_id = UUID("00000000-0000-0000-0000-000000000002")
    alias_id = UUID("00000000-0000-0000-0000-000000000003")
    db = _DictionaryDb(
        [
            {"id": l1_id, "term": "制造与工业", "level": "l1", "l1_name": "制造与工业", "parent_id": None, "canonical_term_id": None},
            {"id": l2_id, "term": "模具制造", "level": "l2", "l1_name": "制造与工业", "parent_id": l1_id, "canonical_term_id": None},
            {"id": alias_id, "term": "精密模具", "level": "alias", "l1_name": "制造与工业", "parent_id": None, "canonical_term_id": l2_id},
        ]
    )

    preview = _validate_import_rows(
        db,
        [{"row_number": 2, "l1": "制造与工业", "l2": "汽车零部件", "aliases": ["精密模具"], "active": True}],
    )

    assert preview[0]["status"] == "error"
    assert "其他行业" in preview[0]["message"]


class _ApplyDb:
    def __init__(self, existing_rows):
        self.existing_rows = existing_rows
        self.calls = []

    def execute(self, statement, params):
        self.calls.append((str(statement), params))
        if len(self.calls) == 1:
            return _MappingsResult(self.existing_rows)
        return object()


def test_apply_import_batches_the_0729_shape_instead_of_writing_row_by_row() -> None:
    rows = [
        {
            "row_number": index + 2,
            "l1": f"一级-{index % 16}",
            "l2": f"二级-{index}",
            "aliases": [f"别名-{index}"] if index < 40 else [],
            "active": True,
        }
        for index in range(167)
    ]
    # 文件还有 16 个仅含 L1 的行；重复 L1 应在内存里归并，而不是再次写库。
    rows.extend(
        {
            "row_number": 169 + index,
            "l1": f"一级-{index}",
            "l2": None,
            "aliases": [],
            "active": True,
        }
        for index in range(16)
    )
    db = _ApplyDb(existing_rows=[])

    counts = _apply_import_rows(db, rows)

    assert counts == {"created_l1": 16, "created_l2": 167, "created_aliases": 40}
    # 1 次现状读取 + L1/L2/alias 各 1 个 executemany；即使新旧混合也至多 7 次。
    assert len(db.calls) == 4
    assert [len(params) for _, params in db.calls[1:]] == [16, 167, 40]
