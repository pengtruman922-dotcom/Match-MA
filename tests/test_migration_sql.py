from backend.app.migration_sql import load_migration_sql, split_sql_statements


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
