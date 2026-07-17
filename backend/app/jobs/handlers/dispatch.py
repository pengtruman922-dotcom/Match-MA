from __future__ import annotations


from sqlalchemy.orm import Session

from backend.app.jobs.queue import JobClaim

from backend.app.jobs.handlers.attachment_ocr import (
    _handle_attachment_ocr_parse,
    _handle_attachment_ocr_poll,
)
from backend.app.jobs.handlers.business_update import (
    _handle_business_update_extract_actions,
)
from backend.app.jobs.handlers.buyer_intent_parse import (
    _handle_buyer_intent_parse,
)
from backend.app.jobs.handlers.model_node_test import (
    _handle_model_node_test,
)
from backend.app.jobs.handlers.recommendation import (
    _handle_recommendation_report_generate,
    _handle_recommendation_rerank,
)
from backend.app.jobs.handlers.search_embedding import (
    _handle_buyer_intent_search_doc_rebuild,
    _handle_embedding_generate,
    _handle_seller_search_doc_rebuild,
)
from backend.app.jobs.handlers.seller_target_parse import (
    _handle_seller_target_parse,
)

def execute_job(db: Session, job: JobClaim) -> dict[str, object]:
    if job.job_type == "business_update_extract_actions":
        return _handle_business_update_extract_actions(db, job)
    if job.job_type == "seller_target_parse":
        return _handle_seller_target_parse(db, job)
    if job.job_type == "buyer_intent_parse":
        return _handle_buyer_intent_parse(db, job)
    if job.job_type == "attachment_ocr_parse":
        return _handle_attachment_ocr_parse(db, job)
    if job.job_type == "attachment_ocr_poll":
        return _handle_attachment_ocr_poll(db, job)
    if job.job_type == "seller_search_doc_rebuild":
        return _handle_seller_search_doc_rebuild(db, job)
    if job.job_type == "buyer_intent_search_doc_rebuild":
        return _handle_buyer_intent_search_doc_rebuild(db, job)
    if job.job_type == "embedding_generate":
        return _handle_embedding_generate(db, job)
    if job.job_type == "recommendation_report_generate":
        return _handle_recommendation_report_generate(db, job)
    if job.job_type in {"recommendation_rerank", "recommendation_deep_eval"}:
        return _handle_recommendation_rerank(db, job)
    if job.job_type == "model_node_test":
        return _handle_model_node_test(db, job)

    return {
        "handled": False,
        "job_type": job.job_type,
        "message": "No real job handler is implemented for this job type yet.",
    }
