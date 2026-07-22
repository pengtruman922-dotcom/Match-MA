"""Cross-check the three places an extracted_action action_type must be registered.

Adding a new action_type requires updating, in lockstep:
1. ALLOWED_ACTION_TYPES in backend/app/jobs/handlers/common.py
2. The chk_extracted_action_type DB check constraint (rebuilt via migration)
3. The apply dispatch in the extracted-actions route (unless the type is
   record-only and never writes entity fields)

These tests turn that discipline into assertions so a missed spot fails CI.
"""

import re
from pathlib import Path

from backend.app.jobs.handlers import ALLOWED_ACTION_TYPES
from backend.app.jobs.handlers.business_update import AUTO_APPLY_ACTION_TYPE_ORDER

MIGRATIONS_DIR = Path("database/migrations")
APPLY_ROUTE_SOURCE = Path("backend/app/api/routes/extracted_actions.py")

# Action types that intentionally have no apply branch: they are recorded for
# audit/diagnosis only and never write entity fields. Adding a new type here
# is an explicit product decision, not a default.
NON_APPLYABLE_ACTION_TYPES = {
    "seller_event",
    "buyer_level_blacklist_suggestion",
    "internal_note",
    "unresolved_item",
}


def _db_constraint_action_types() -> set[str]:
    """Return the enum list of the latest chk_extracted_action_type definition.

    Migrations rebuild the constraint (drop + add), so the last definition in
    file order is the one live in production after `alembic upgrade head`.
    """
    latest: str | None = None
    # 两种写法：迁移重建用 check (action_type in (...))，
    # 基线文件是 pg_get_constraintdef 的规范形式 CHECK ((action_type = ANY (ARRAY[...])))。
    pattern = re.compile(
        r"chk_extracted_action_type\s+"
        r"(?:check \(action_type in \((?P<plain>.*?)\)\)"
        r"|CHECK \(\(action_type = ANY \(ARRAY\[(?P<pg>.*?)\]\)\)\))",
        re.S,
    )
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        content = path.read_text(encoding="utf-8")
        for match in pattern.finditer(content):
            latest = match.group("plain") or match.group("pg")
    assert latest is not None, "chk_extracted_action_type not found in any migration"
    return set(re.findall(r"'([a-z_]+)'", latest))


def _apply_dispatch_action_types() -> set[str]:
    source = APPLY_ROUTE_SOURCE.read_text(encoding="utf-8")
    start = source.index("def apply_extracted_action(")
    end = source.find("\n@router.", start)
    body = source[start : end if end != -1 else len(source)]
    return set(re.findall(r'action\["action_type"\] == "([a-z_]+)"', body))


def test_allowed_action_types_match_db_check_constraint() -> None:
    assert _db_constraint_action_types() == ALLOWED_ACTION_TYPES


def test_apply_dispatch_covers_every_applyable_action_type() -> None:
    assert NON_APPLYABLE_ACTION_TYPES <= ALLOWED_ACTION_TYPES
    assert _apply_dispatch_action_types() == ALLOWED_ACTION_TYPES - NON_APPLYABLE_ACTION_TYPES


def test_auto_apply_order_only_lists_applyable_action_types() -> None:
    assert set(AUTO_APPLY_ACTION_TYPE_ORDER) <= ALLOWED_ACTION_TYPES - NON_APPLYABLE_ACTION_TYPES
