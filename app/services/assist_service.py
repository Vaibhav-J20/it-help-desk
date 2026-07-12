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

    requested_scope = _scope_to_dict(request)
    initial_state: SupportState = {
        "request_id": request_id,
        "user_question": request.question,
        "conversation_context": [m.model_dump() for m in request.conversation_context],
        "extracted_scope": requested_scope,
        "trace": {
            "trace_id": trace_id,
            "explicit_scope_keys": sorted(requested_scope),
        },
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
    # domain_id from RequestedScope takes precedence over classifier inference
    # and over any component-based domain mapping below.
    if request.requested_scope.domain_id:
        scope["domain_id"] = request.requested_scope.domain_id
    if request.requested_scope.ocp_version:
        scope["ocp_version"] = request.requested_scope.ocp_version
    if request.requested_scope.deployment_type:
        scope["deployment_type"] = request.requested_scope.deployment_type
    if request.requested_scope.component:
        # Only apply component→domain mapping when no explicit domain_id was given.
        component_scope = _normalise_component_scope(request.requested_scope.component)
        if "domain_id" not in scope:
            scope.update(component_scope)
        elif "domain_id" in component_scope:
            # Explicit domain_id wins; still carry through non-domain keys (e.g. component).
            scope.update({k: v for k, v in component_scope.items() if k != "domain_id"})
        else:
            scope.update(component_scope)
    return scope


def _normalise_component_scope(component: str) -> dict:
    """
    Orchestrate sometimes sends product/domain names in requested_scope.component.
    Map those to domain filters so they do not become impossible component filters.
    """
    value = component.strip()
    key = value.lower()

    if key in {"ibm bob", "bob", "bob ide"}:
        return {"domain_id": "ibm_bob"}

    if key in {
        "watsonx orchestrate",
        "ibm watsonx orchestrate",
        "orchestrate",
        "orchestrate adk",
    }:
        return {"domain_id": "watsonx_orchestrate"}

    if key in {
        "openshift",
        "open shift",
        "ocp",
        "openshift container platform",
        "sno",
        "single node openshift",
    }:
        return {"domain_id": "ocp_sno_support"}

    return {"component": value}


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
