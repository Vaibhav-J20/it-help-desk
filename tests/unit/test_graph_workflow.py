"""
Day 5 — LangGraph workflow tests.
Proves all 5 status codes are returned deterministically with mocked providers.
No real LLM or OpenSearch calls — all external dependencies are injected mocks.
"""
import pytest
from app.graph.workflow import build_graph
from app.graph.state import SupportState


# ── mock providers ────────────────────────────────────────────────────────────

def _mock_embed(text: str) -> list[float]:
    return [0.1] * 768


def _mock_generate_qa(prompt: str) -> str:
    """Returns a valid cited answer."""
    return "Check the DNS configuration. [S1]\n\n### Sources\n[S1] SNO Guide — OCP 4.16, p. 12"


def _mock_generate_classify_in_scope(prompt: str) -> str:
    import json
    return json.dumps({
        "intent": "qa",
        "ocp_version": "4.16",
        "deployment_type": "SNO",
        "component": "dns",
        "needs_clarification": False,
        "clarification_question": None,
    })


def _mock_generate_classify_unsupported(prompt: str) -> str:
    import json
    return json.dumps({
        "intent": "unsupported",
        "ocp_version": None,
        "deployment_type": None,
        "component": None,
        "needs_clarification": False,
        "clarification_question": None,
    })


def _mock_generate_classify_needs_clarification(prompt: str) -> str:
    import json
    return json.dumps({
        "intent": "troubleshoot",
        "ocp_version": None,
        "deployment_type": None,
        "component": None,
        "needs_clarification": True,
        "clarification_question": "Which OCP version and deployment type are you using?",
    })


def _make_chunk(version="4.16"):
    return {
        "chunk_id": "ocp_sno_support:doc-test:rev-001:chunk-0001",
        "document_id": "doc-test",
        "title": "SNO Guide",
        "product": "OpenShift",
        "ocp_version": version,
        "deployment_type": ["SNO"],
        "page_start": 12,
        "page_end": 12,
        "section_path": "Bootstrap > DNS",
        "chunk_text": "DNS records must be configured before bootstrap.",
    }


def _mock_opensearch(chunks: list[dict]):
    """Returns a mock OpenSearch client that always returns the given chunks."""
    class MockClient:
        def search(self, index, body):
            return {"hits": {"hits": [{"_source": c} for c in chunks]}}
    return MockClient()


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_graph(question: str, classify_fn, retrieve_chunks: list[dict],
               generate_fn=_mock_generate_qa, requested_scope: dict | None = None) -> SupportState:
    """
    Build a fresh graph with mocked node functions injected directly into
    the StateGraph — bypasses the compiled node reference problem.
    """
    from langgraph.graph import StateGraph, END
    import app.graph.nodes.input_guard as ig_mod
    import app.graph.nodes.resolve_scope as rs_mod
    import app.graph.nodes.evidence_gate as eg_mod
    import app.graph.nodes.validate_citations as vc_mod

    _chunks = list(retrieve_chunks)
    _classify_fn = classify_fn
    _generate_fn = generate_fn

    def _classify(state: SupportState) -> SupportState:
        import app.graph.nodes.classify_extract as ce_mod
        return ce_mod.run.__wrapped__(state, generate_fn=_classify_fn) \
            if hasattr(ce_mod.run, '__wrapped__') \
            else ce_mod.run(state, generate_fn=_classify_fn)

    def _retrieve(state: SupportState) -> SupportState:
        import app.graph.nodes.retrieve as ret_mod
        return ret_mod.run(state,
                           opensearch_client=_mock_opensearch(_chunks),
                           embedding_fn=_mock_embed)

    def _compose(state: SupportState) -> SupportState:
        import app.graph.nodes.compose_answer as ca_mod
        return ca_mod.run(state, generate_fn=_generate_fn)

    # Re-import routing helpers from workflow
    from app.graph.workflow import (
        _route_after_input_guard,
        _route_after_resolve_scope,
        _route_after_evidence_gate,
        _route_after_validate_citations,
    )

    graph = StateGraph(SupportState)
    graph.add_node("input_guard",         ig_mod.run)
    graph.add_node("classify_and_extract", _classify)
    graph.add_node("resolve_scope",        rs_mod.run)
    graph.add_node("retrieve",             _retrieve)
    graph.add_node("evidence_gate",        eg_mod.run)
    graph.add_node("compose_answer",       _compose)
    graph.add_node("validate_citations",   vc_mod.run)

    graph.set_entry_point("input_guard")
    graph.add_conditional_edges("input_guard", _route_after_input_guard)
    graph.add_edge("classify_and_extract", "resolve_scope")
    graph.add_conditional_edges("resolve_scope", _route_after_resolve_scope)
    graph.add_edge("retrieve", "evidence_gate")
    graph.add_conditional_edges("evidence_gate", _route_after_evidence_gate)
    graph.add_edge("compose_answer", "validate_citations")
    graph.add_conditional_edges("validate_citations", _route_after_validate_citations)

    compiled = graph.compile()
    initial: SupportState = {
        "request_id": "test-req-001",
        "user_question": question,
        "conversation_context": [],
        "extracted_scope": requested_scope or {},
        "trace": {"trace_id": "test-trace-001"},
    }
    return compiled.invoke(initial)


# ── tests: all 5 status codes ─────────────────────────────────────────────────

def test_answered_status():
    """In-scope question + sufficient evidence → ANSWERED with citations."""
    result = _run_graph(
        question="How do I configure DNS for SNO on OCP 4.16?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[_make_chunk("4.16")],
        generate_fn=_mock_generate_qa,
        requested_scope={"ocp_version": "4.16", "deployment_type": "SNO"},
    )
    assert result["status"] == "ANSWERED"
    assert result.get("citations")
    assert result["citations"][0]["citation_id"] == "S1"
    assert result.get("answer_markdown")


def test_insufficient_evidence_no_chunks():
    """In-scope question + no chunks retrieved → INSUFFICIENT_EVIDENCE."""
    result = _run_graph(
        question="How do I configure DNS for SNO on OCP 4.16?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[],  # nothing in index
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert not result.get("answer_markdown")


def test_insufficient_evidence_version_mismatch():
    """Explicit version 4.16 requested but only 4.14 chunks available → INSUFFICIENT_EVIDENCE."""
    result = _run_graph(
        question="How do I configure DNS for SNO on OCP 4.16?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[_make_chunk("4.14")],   # wrong version
        requested_scope={"ocp_version": "4.16"},
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_out_of_scope_status():
    """Question classified as unsupported intent → OUT_OF_SCOPE."""
    result = _run_graph(
        question="How do I configure ServiceNow?",
        classify_fn=_mock_generate_classify_unsupported,
        retrieve_chunks=[],
    )
    assert result["status"] == "OUT_OF_SCOPE"
    assert not result.get("answer_markdown")


def test_needs_clarification_status():
    """Missing version + ambiguous question → NEEDS_CLARIFICATION."""
    result = _run_graph(
        question="My cluster installation failed",
        classify_fn=_mock_generate_classify_needs_clarification,
        retrieve_chunks=[],
    )
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result.get("required_clarification")
    assert not result.get("answer_markdown")


def test_invalid_request_empty_question():
    """Empty question → INVALID_REQUEST (never reaches classify node)."""
    graph = build_graph()
    result = graph.invoke({
        "request_id": "test-req-invalid",
        "user_question": "",
        "conversation_context": [],
        "extracted_scope": {},
        "trace": {},
    })
    assert result["status"] == "INVALID_REQUEST"


def test_invalid_request_too_short():
    """2-char question → INVALID_REQUEST."""
    graph = build_graph()
    result = graph.invoke({
        "request_id": "test-req-short",
        "user_question": "Hi",
        "conversation_context": [],
        "extracted_scope": {},
        "trace": {},
    })
    assert result["status"] == "INVALID_REQUEST"


def test_invalid_citation_returns_insufficient():
    """Answer references [S5] but only 1 chunk — citation validator catches it."""
    def bad_generate(prompt: str) -> str:
        return "See [S5] for details."  # S5 doesn't exist

    result = _run_graph(
        question="How do I configure DNS for SNO on OCP 4.16?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[_make_chunk("4.16")],
        generate_fn=bad_generate,
        requested_scope={"ocp_version": "4.16"},
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_answered_has_trace():
    """Every ANSWERED response must have a populated trace dict."""
    result = _run_graph(
        question="How do I configure DNS for SNO on OCP 4.16?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[_make_chunk("4.16")],
        generate_fn=_mock_generate_qa,
        requested_scope={"ocp_version": "4.16"},
    )
    assert result.get("trace")
    assert "evidence_gate" in result["trace"]
    assert "validate_citations" in result["trace"]


def test_no_answer_generated_without_evidence():
    """compose_answer must not be called when evidence_gate returns insufficient."""
    called = []

    def spy_generate(prompt: str) -> str:
        called.append(prompt)
        return "answer [S1]"

    result = _run_graph(
        question="How do I configure DNS for SNO?",
        classify_fn=_mock_generate_classify_in_scope,
        retrieve_chunks=[],   # no evidence
        generate_fn=spy_generate,
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    # compose_answer should NOT have been called
    assert not called, "generate was called despite no evidence — evidence gate failed"
