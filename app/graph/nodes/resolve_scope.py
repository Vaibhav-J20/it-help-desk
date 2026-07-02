"""
Node 3: resolve_scope
Decides whether the request is in scope and whether clarification is needed.
Must not silently change an explicit user-provided version.
"""
from app.graph.state import SupportState
from app.policy.domain_policy import is_in_scope

_SUPPORTED_DOMAIN = "ocp_sno_support"


def run(state: SupportState) -> SupportState:
    intent = state.get("intent", "qa")
    required_clarification = state.get("required_clarification")

    # Out of scope
    if intent == "unsupported":
        return {
            **state,
            "status": "OUT_OF_SCOPE",
            "trace": {**state.get("trace", {}), "resolve_scope": "out_of_scope"},
        }

    # Needs clarification before we can retrieve anything useful
    if required_clarification:
        return {
            **state,
            "status": "NEEDS_CLARIFICATION",
            "trace": {**state.get("trace", {}), "resolve_scope": "needs_clarification"},
        }

    # Build retrieval query — use original question as the retrieval query
    retrieval_query = state["user_question"]

    # Add domain filter to extracted scope
    extracted_scope = dict(state.get("extracted_scope") or {})
    extracted_scope.setdefault("domain_id", _SUPPORTED_DOMAIN)

    from app.retrieval.filters import build_filters
    retrieval_filters = build_filters(extracted_scope)

    return {
        **state,
        "retrieval_query": retrieval_query,
        "retrieval_filters": retrieval_filters,
        "extracted_scope": extracted_scope,
        "trace": {**state.get("trace", {}), "resolve_scope": "in_scope"},
    }
