from pathlib import Path
from typing import Any


def run_migration_sql(bind: Any, name: str) -> None:
    """Execute a migration SQL file statement by statement.

    All alembic version files must route through this function instead of
    calling bind.exec_driver_sql directly: psycopg3 scans driver-level SQL for
    %-placeholders even when no parameters are bound, so literal percent signs
    (e.g. LIKE '%x%') must be doubled or the migration fails in production
    (incident: migration 031 on Railway).
    """
    for statement in split_sql_statements(load_migration_sql(name)):
        bind.exec_driver_sql(statement.replace("%", "%%"))


def load_migration_sql(name: str) -> str:
    project_root = Path(__file__).resolve().parents[2]
    sql = (project_root / "database" / "migrations" / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in sql.splitlines() if line.strip().lower() not in {"begin;", "commit;"}
    )


def split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_line_comment = False
    in_block_comment = False
    index = 0

    while index < len(sql):
        character = sql[index]
        next_character = sql[index + 1] if index + 1 < len(sql) else ""

        if in_line_comment:
            current.append(character)
            if character in {"\n", "\r"}:
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            current.append(character)
            if character == "*" and next_character == "/":
                current.append(next_character)
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if not in_single_quote and character == "-" and next_character == "-":
            current.append(character)
            current.append(next_character)
            in_line_comment = True
            index += 2
            continue

        if not in_single_quote and character == "/" and next_character == "*":
            current.append(character)
            current.append(next_character)
            in_block_comment = True
            index += 2
            continue

        current.append(character)

        if character == "'":
            if in_single_quote and next_character == "'":
                current.append(next_character)
                index += 2
                continue
            in_single_quote = not in_single_quote

        if character == ";" and not in_single_quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement[:-1].strip())
            current = []

        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements
