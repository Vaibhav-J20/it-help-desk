"""
FastAPI routes for the v1 API.
"""
from fastapi import APIRouter, Depends
from app.api.schemas import AssistRequest, AssistResponse
from app.api.dependencies import verify_api_key
from app.services.assist_service import handle_request

router = APIRouter(prefix="/v1", tags=["assist"])


@router.post(
    "/assist",
    response_model=AssistResponse,
    summary="Submit a technical support question",
    description=(
        "Submit a technical support question for an approved domain. "
        "Returns a citation-grounded answer, a clarification request, "
        "an insufficient-evidence notice, or an out-of-scope notice."
    ),
)
async def assist(
    request: AssistRequest,
    _: None = Depends(verify_api_key),
) -> AssistResponse:
    return handle_request(request)
