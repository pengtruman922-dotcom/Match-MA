from fastapi import APIRouter

from backend.app.api.routes import (
    business_updates,
    buyer_intents,
    extracted_actions,
    health,
    meta,
    seller_targets,
    update_logs,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)
api_router.include_router(seller_targets.router)
api_router.include_router(buyer_intents.router)
api_router.include_router(update_logs.router)
api_router.include_router(business_updates.router)
api_router.include_router(extracted_actions.router)
