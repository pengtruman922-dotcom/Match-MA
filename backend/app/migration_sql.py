from pathlib import Path


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
    index = 0

    while index < len(sql):
        character = sql[index]
        current.append(character)

        if character == "'":
            next_character = sql[index + 1] if index + 1 < len(sql) else ""
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
