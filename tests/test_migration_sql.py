from pathlib import Path

import pytest

from backend.app.migration_sql import load_migration_sql, run_migration_sql, split_sql_statements

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "database" / "migrations"
ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

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


class _RecordingBind:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def exec_driver_sql(self, statement: str) -> None:
        self.statements.append(statement)


def test_run_migration_sql_escapes_percent_for_psycopg() -> None:
    # psycopg3 scans driver-level SQL for %-placeholders even without bound
    # parameters; a literal LIKE '%x%' must reach the driver as '%%x%%'
    # (incident: migration 031 blocked Railway deploys for two days).
    bind = _RecordingBind()

    run_migration_sql(bind, "031_buyer_management_flow.sql")

    assert bind.statements, "no statements executed"
    joined = "\n".join(bind.statements)
    assert "%%buyer_intent.status use exactly one of%%" in joined
    assert "%%manual buyer notes%%" in joined
    stripped = joined.replace("%%", "")
    assert "%" not in stripped, "found unescaped percent sign in driver-level SQL"


@pytest.mark.parametrize(
    "version_name",
    sorted(path.name for path in ALEMBIC_VERSIONS_DIR.glob("*.py")),
)
def test_alembic_wrappers_route_through_run_migration_sql(version_name: str) -> None:
    source = (ALEMBIC_VERSIONS_DIR / version_name).read_text(encoding="utf-8")
    if "load_migration_sql" in source or "split_sql_statements" in source:
        pytest.fail(
            f"{version_name}: use run_migration_sql instead of load/split + exec_driver_sql "
            "(literal % in SQL breaks psycopg3 placeholder scanning)"
        )


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


def test_splitter_keeps_dollar_quoted_bodies_intact() -> None:
    """do $$ ... $$ blocks carry their own semicolons; splitting inside one
    yields fragments like 'end if' that fail at deploy time."""
    sql = """
alter table t add column a text;
do $do$
begin
  if not exists (select 1 from pg_constraint where conname = 'c') then
    alter table t add constraint c check (a in ('x', 'y'));
  end if;
end
$do$;
create index i on t (a);
"""

    statements = split_sql_statements(sql)

    assert len(statements) == 3
    assert statements[0].startswith("alter table")
    assert statements[1].startswith("do $do$")
    assert statements[1].endswith("$do$")
    assert "end if;" in statements[1]
    assert statements[2].startswith("create index")


def test_splitter_handles_anonymous_and_nested_looking_dollar_tags() -> None:
    sql = "do $$ begin perform 1; end $$;\nselect $tag$ ; not a split $tag$;"

    statements = split_sql_statements(sql)

    assert len(statements) == 2
    assert statements[0] == "do $$ begin perform 1; end $$"
    assert statements[1] == "select $tag$ ; not a split $tag$"
