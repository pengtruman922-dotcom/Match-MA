from fastapi import APIRouter

from backend.app.api.routes import health, meta

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)
