from fastapi import APIRouter

from backend.app.api.routes import (
    auth,
    attachments,
    background_jobs,
    business_updates,
    buyer_intents,
    buyer_parties,
    buyer_party_ingest,
    data_dictionaries,
    debug,
    extracted_actions,
    field_sources,
    global_search,
    health,
    meta,
    model_config,
    profile_sections,
    research,
    search_config,
    recommendations,
    relations,
    search_docs,
    seller_targets,
    stats,
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
# 挂在 buyer_parties 之后：它的路径都比 /{buyer_party_id} 多一段，不会被吃掉。
api_router.include_router(buyer_party_ingest.router)
api_router.include_router(buyer_intents.router)
api_router.include_router(data_dictionaries.router)
api_router.include_router(profile_sections.router)
api_router.include_router(research.router)
api_router.include_router(search_config.router)
api_router.include_router(recommendations.router)
api_router.include_router(relations.router)
api_router.include_router(stats.router)
api_router.include_router(search_docs.router)
api_router.include_router(update_logs.router)
api_router.include_router(business_updates.router)
api_router.include_router(extracted_actions.router)
api_router.include_router(field_sources.router)
api_router.include_router(global_search.router)
api_router.include_router(debug.router)
