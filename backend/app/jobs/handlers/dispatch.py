from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.app.ai.doc2x_client import Doc2xCallError, poll_doc2x_status, submit_doc2x_pdf
from backend.app.ai.embedding_client import (
    EmbeddingCallError,
    call_openai_compatible_embedding,
    embedding_to_pgvector_literal,
)
from backend.app.ai.llm_client import LlmCallError, call_openai_compatible_chat
from backend.app.ai.ocr_client import OcrInput, build_attachment_ocr_input_json, call_attachment_ocr
from backend.app.ai.prompting import render_template
from backend.app.ai.rerank_client import RerankCallError, call_dashscope_compatible_rerank
from backend.app.config import get_settings
from backend.app.constants import DEFAULT_TEAM_ID, DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID
from backend.app.api.routes.extracted_actions import (
    apply_buyer_intent_follow_up_action,
    apply_buyer_intent_target_exclusion_action,
    apply_buyer_intent_update_action,
    apply_buyer_seller_relation_update_action,
    apply_seller_fact_update_action,
    apply_target_follow_up_action,
)
from backend.app.jobs.queue import JobClaim
from backend.app.services.search_docs import (
    create_search_doc_rebuild_job,
    rebuild_buyer_intent_search_doc,
    rebuild_seller_target_search_doc,
)
from backend.app.services.attachment_storage import (
    AttachmentStorageError,
    read_attachment_bytes,
    read_local_text_content,
    save_generated_text,
)
from backend.app.services.image_inputs import (
    is_supported_multimodal_image,
    multimodal_image_constraints,
    prepare_image_for_multimodal,
)
from backend.app.services.industry_taxonomy import (
    industry_l1_prompt_list,
    normalize_excluded_terms,
    normalize_l1_values,
    resolve_l1,
)
from backend.app.services.office_inspection import inspect_office_text, office_document_kind
from backend.app.services.pdf_inspection import inspect_pdf_text_layer

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
