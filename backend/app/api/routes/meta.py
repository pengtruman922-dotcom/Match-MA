from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.db import get_db

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/seed-status")
def seed_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    default_team_id = "00000000-0000-0000-0000-000000000001"
    default_workspace_id = "00000000-0000-0000-0000-000000000101"
    default_admin_id = "00000000-0000-0000-0000-000000000201"

    checks = {
        "default_team": _exists(db, "team", default_team_id),
        "default_workspace": _exists(db, "workspace", default_workspace_id),
        "default_admin_user": _exists(db, "app_user", default_admin_id),
    }

    dictionaries = {
        "industry": _count_dictionary(db, "industry"),
        "deal_path": _count_dictionary(db, "deal_path"),
        "payment_method": _count_dictionary(db, "payment_method"),
        "control_path": _count_dictionary(db, "control_path"),
        "risk": _count_dictionary(db, "risk"),
    }

    region_alias_count = db.execute(
        text("select count(*) from region_alias_config where is_active = true")
    ).scalar_one()

    ok = all(checks.values()) and dictionaries["industry"] > 0 and dictionaries["risk"] > 0

    return {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "dictionary_counts": dictionaries,
        "region_alias_count": region_alias_count,
    }


def _exists(db: Session, table_name: str, entity_id: str) -> bool:
    if table_name not in {"team", "workspace", "app_user"}:
        raise ValueError(f"Unsupported table for seed check: {table_name}")

    result = db.execute(
        text(f"select exists(select 1 from {table_name} where id = :entity_id)"),
        {"entity_id": entity_id},
    )
    return bool(result.scalar_one())


def _count_dictionary(db: Session, domain: str) -> int:
    result = db.execute(
        text(
            """
            select count(*)
            from tag_dictionary
            where domain = :domain
              and is_active = true
            """
        ),
        {"domain": domain},
    )
    return int(result.scalar_one())
