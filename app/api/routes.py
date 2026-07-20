"""
FastAPI routes for the v1 API.
"""
from fastapi import APIRouter, Depends
from app.api.schemas import AssistRequest, AssistResponse, DomainsResponse
from app.api.dependencies import verify_api_key
from app.services.assist_service import handle_request
from app.services.domains_service import get_domains

router = APIRouter(prefix="/v1", tags=["assist"])


@router.post(
    "/assist",
    response_model=AssistResponse,
    summary="Submit a technical support question",
    description=(
        "Submit a technical support question for OpenShift/SNO, watsonx "
        "Orchestrate, IBM Bob, or another registered IBM product such as "
        "Guardium, Instana, Verify, Cloud Pak for Data, or Cloud Pak for "
        "Integration, as well as broad IBM and watsonx product-portfolio "
        "questions. For other registered IBM products, use the ibm_products "
        "domain or omit requested_scope and allow the service to resolve it. "
        "The response status is authoritative: ANSWERED returns answer_markdown, "
        "NEEDS_CLARIFICATION returns clarification_question, and the remaining "
        "statuses describe insufficient evidence, out-of-scope, invalid, or "
        "service-error outcomes. answer_markdown contains a visible source "
        "banner, safe suggested next steps, and a deterministic Sources section "
        "with clickable URLs. source_urls exposes those links structurally, and "
        "retrieval_provenance reports which retrieval paths were attempted and "
        "which sources support the final answer."
    ),
)
async def assist(
    request: AssistRequest,
    _: None = Depends(verify_api_key),
) -> AssistResponse:
    return handle_request(request)


@router.get(
    "/domains",
    response_model=DomainsResponse,
    summary="List indexed knowledge domains",
    description=(
        "Returns the domains currently indexed in the knowledge base with their "
        "chunk counts. Does not consume watsonx.ai tokens."
    ),
)
async def domains(
    _: None = Depends(verify_api_key),
) -> DomainsResponse:
    return get_domains()
