"""
Assist service — orchestrates the LangGraph workflow for the POST /v1/assist route.
"""
import uuid
from app.api.schemas import AssistRequest, AssistResponse, Citation
from app.graph.state import SupportState
from app.graph.workflow import support_graph
from app.observability.logging import get_logger, log_request_event
import time

logger = get_logger(__name__)


def handle_request(request: AssistRequest) -> AssistResponse:
    """
    Entry point for POST /v1/assist.
    Builds initial state, runs the LangGraph workflow, maps terminal state to response.
    """
    request_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    start_ms = time.monotonic()

    initial_state: SupportState = {
        "request_id": request_id,
        "user_question": request.question,
        "conversation_context": [m.model_dump() for m in request.conversation_context],
        "extracted_scope": _scope_to_dict(request),
        "trace": {"trace_id": trace_id},
    }

    try:
        final_state: SupportState = support_graph.invoke(initial_state)
    except Exception as e:
        logger.info(f"Graph execution error: {e}")
        log_request_event(
            logger, "support_request_error",
            request_id=request_id, trace_id=trace_id,
            error=str(e),
        )
        return AssistResponse(
            request_id=request_id,
            status="ERROR",
            trace_id=trace_id,
        )

    total_ms = round((time.monotonic() - start_ms) * 1000)
    status = final_state.get("status", "ERROR")

    log_request_event(
        logger, "support_request_complete",
        request_id=request_id,
        trace_id=trace_id,
        status=status,
        intent=final_state.get("intent"),
        candidate_count=len(final_state.get("candidates") or []),
        evidence_chunk_count=len(final_state.get("citations") or []),
        total_ms=total_ms,
    )

    return _state_to_response(final_state, request_id, trace_id)


def _scope_to_dict(request: AssistRequest) -> dict:
    scope = {}
    if request.requested_scope.ocp_version:
        scope["ocp_version"] = request.requested_scope.ocp_version
    if request.requested_scope.deployment_type:
        scope["deployment_type"] = request.requested_scope.deployment_type
    if request.requested_scope.component:
        scope["component"] = request.requested_scope.component
    return scope


def _state_to_response(state: SupportState, request_id: str, trace_id: str) -> AssistResponse:
    raw_citations = state.get("citations") or []
    citations = [Citation(**c) for c in raw_citations]

    return AssistResponse(
        request_id=request_id,
        status=state.get("status", "ERROR"),
        intent=state.get("intent"),
        answer_markdown=state.get("answer_markdown"),
        clarification_question=state.get("required_clarification"),
        citations=citations,
        trace_id=trace_id,
    )
