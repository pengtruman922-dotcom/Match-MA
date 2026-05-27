from fastapi import APIRouter

from backend.app.api.routes import buyer_intents, health, meta, seller_targets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)
api_router.include_router(seller_targets.router)
api_router.include_router(buyer_intents.router)
