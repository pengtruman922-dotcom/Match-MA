from fastapi import APIRouter

from backend.app.api.routes import (
    background_jobs,
    business_updates,
    buyer_intents,
    buyer_parties,
    debug,
    extracted_actions,
    health,
    meta,
    recommendations,
    relations,
    search_docs,
    seller_targets,
    update_logs,
    workbench,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)
api_router.include_router(background_jobs.router)
api_router.include_router(seller_targets.router)
api_router.include_router(buyer_parties.router)
api_router.include_router(buyer_intents.router)
api_router.include_router(recommendations.router)
api_router.include_router(relations.router)
api_router.include_router(search_docs.router)
api_router.include_router(update_logs.router)
api_router.include_router(business_updates.router)
api_router.include_router(extracted_actions.router)
api_router.include_router(workbench.router)
api_router.include_router(debug.router)
