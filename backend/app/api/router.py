from fastapi import APIRouter

from backend.app.api.routes import (
    auth,
    attachments,
    background_jobs,
    business_updates,
    buyer_intents,
    buyer_parties,
    data_dictionaries,
    debug,
    extracted_actions,
    field_sources,
    global_search,
    health,
    meta,
    model_config,
    profile_sections,
    recommendations,
    relations,
    search_docs,
    seller_targets,
    update_logs,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(health.router)
api_router.include_router(meta.router)
api_router.include_router(model_config.router)
api_router.include_router(background_jobs.router)
api_router.include_router(attachments.router)
api_router.include_router(seller_targets.router)
api_router.include_router(buyer_parties.router)
api_router.include_router(buyer_intents.router)
api_router.include_router(data_dictionaries.router)
api_router.include_router(profile_sections.router)
api_router.include_router(recommendations.router)
api_router.include_router(relations.router)
api_router.include_router(search_docs.router)
api_router.include_router(update_logs.router)
api_router.include_router(business_updates.router)
api_router.include_router(extracted_actions.router)
api_router.include_router(field_sources.router)
api_router.include_router(global_search.router)
api_router.include_router(debug.router)
