from pathlib import Path

import pytest

from backend.app.migration_sql import load_migration_sql, split_sql_statements

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database" / "migrations"

STATEMENT_START_KEYWORDS = {
    "alter",
    "comment",
    "create",
    "delete",
    "do",
    "drop",
    "grant",
    "insert",
    "select",
    "set",
    "update",
    "with",
}


def _strip_leading_comment_lines(statement: str) -> str:
    lines = statement.splitlines()
    while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines).strip()


def test_split_sql_statements_ignores_semicolon_in_line_comment() -> None:
    sql = "-- comment with a semicolon; still a comment\nselect 'a;b';\nselect 2;"

    statements = split_sql_statements(sql)

    assert statements == [
        "-- comment with a semicolon; still a comment\nselect 'a;b'",
        "select 2",
    ]


def test_extracted_action_follow_up_migration_splits_into_two_statements() -> None:
    sql = load_migration_sql("029_extracted_action_type_target_follow_up.sql")

    statements = split_sql_statements(sql)

    assert len(statements) == 2
    assert "drop constraint if exists chk_extracted_action_type" in statements[0]
    assert "add constraint chk_extracted_action_type" in statements[1]
    assert "'target_follow_up'" in statements[1]
    assert not any(statement.lstrip().startswith("the") for statement in statements)


@pytest.mark.parametrize(
    "migration_name",
    sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql")),
)
def test_every_migration_splits_into_valid_statements(migration_name: str) -> None:
    sql = load_migration_sql(migration_name)

    statements = split_sql_statements(sql)

    assert statements, f"{migration_name}: splitter produced no statements"
    for position, statement in enumerate(statements):
        body = _strip_leading_comment_lines(statement)
        assert body, f"{migration_name}[{position}]: comment-only statement"
        first_word = body.split(None, 1)[0].lower()
        assert first_word in STATEMENT_START_KEYWORDS, (
            f"{migration_name}[{position}]: statement starts with {first_word!r}, "
            f"likely a mis-split fragment: {body[:120]!r}"
        )
