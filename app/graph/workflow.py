"""
LangGraph workflow — wires all 7 nodes in the correct order.
State machine from ARCHITECTURE_IMPLEMENTATION_V3.md section 5.1.
"""
from langgraph.graph import StateGraph, END
from app.graph.state import SupportState
from app.graph.nodes import (
    input_guard,
    classify_extract,
    resolve_scope,
    retrieve,
    evidence_gate,
    compose_answer,
    validate_citations,
)


def _route_after_input_guard(state: SupportState) -> str:
    if state.get("status") == "INVALID_REQUEST":
        return END
    return "classify_and_extract"


def _route_after_resolve_scope(state: SupportState) -> str:
    status = state.get("status")
    if status == "OUT_OF_SCOPE":
        return END
    if status == "NEEDS_CLARIFICATION":
        return END
    return "retrieve"


def _route_after_evidence_gate(state: SupportState) -> str:
    if state.get("evidence_decision") == "insufficient":
        return END
    return "compose_answer"


def _route_after_validate_citations(state: SupportState) -> str:
    trace = state.get("trace") or {}
    if (
        state.get("status") == "INSUFFICIENT_EVIDENCE"
        and trace.get("adaptive_retry_requested")
        and not trace.get("adaptive_retry_attempted")
    ):
        return "retrieve"
    return END


def build_graph() -> StateGraph:
    graph = StateGraph(SupportState)

    graph.add_node("input_guard", input_guard.run)
    graph.add_node("classify_and_extract", classify_extract.run)
    graph.add_node("resolve_scope", resolve_scope.run)
    graph.add_node("retrieve", retrieve.run)
    graph.add_node("evidence_gate", evidence_gate.run)
    graph.add_node("compose_answer", compose_answer.run)
    graph.add_node("validate_citations", validate_citations.run)

    graph.set_entry_point("input_guard")

    graph.add_conditional_edges("input_guard", _route_after_input_guard)
    graph.add_edge("classify_and_extract", "resolve_scope")
    graph.add_conditional_edges("resolve_scope", _route_after_resolve_scope)
    graph.add_edge("retrieve", "evidence_gate")
    graph.add_conditional_edges("evidence_gate", _route_after_evidence_gate)
    graph.add_edge("compose_answer", "validate_citations")
    graph.add_conditional_edges("validate_citations", _route_after_validate_citations)

    return graph.compile()


# Module-level compiled graph — imported by assist_service
support_graph = build_graph()
