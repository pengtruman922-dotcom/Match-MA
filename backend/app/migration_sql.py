from pathlib import Path


def load_migration_sql(name: str) -> str:
    project_root = Path(__file__).resolve().parents[2]
    sql = (project_root / "database" / "migrations" / name).read_text(encoding="utf-8")
    return "\n".join(
        line for line in sql.splitlines() if line.strip().lower() not in {"begin;", "commit;"}
    )


def split_sql_statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]

