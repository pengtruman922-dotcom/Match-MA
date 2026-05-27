from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings
from backend.app.db import engine_is_configured, session_scope

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
    }


@router.get("/health/db")
def database_health_check() -> dict[str, str]:
    if not engine_is_configured():
        return {"status": "degraded", "database": "not_configured"}

    try:
        with session_scope() as session:
            session.execute(text("select 1"))
    except SQLAlchemyError as exc:
        return {"status": "degraded", "database": "error", "detail": str(exc)}

    return {"status": "ok", "database": "reachable"}

