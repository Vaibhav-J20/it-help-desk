"""Unit tests for graph nodes (input_guard, evidence_gate, validate_citations)."""
import pytest
from app.graph.nodes.input_guard import run as input_guard
from app.graph.nodes.evidence_gate import run as evidence_gate
from app.graph.nodes.validate_citations import run as validate_citations
from app.graph.nodes.resolve_scope import run as resolve_scope
from app.graph.nodes.classify_extract import run as classify_extract
from app.graph.nodes import retrieve as retrieve_node


# ── input_guard ──────────────────────────────────────────────────────────────

def test_input_guard_passes_valid():
    state = {"user_question": "How do I configure SNO bootstrap?", "trace": {}}
    result = input_guard(state)
    assert result.get("status") != "INVALID_REQUEST"
    assert result["user_question"] == "How do I configure SNO bootstrap?"


def test_input_guard_rejects_empty():
    state = {"user_question": "", "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_rejects_too_short():
    state = {"user_question": "Hi", "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_rejects_too_long():
    state = {"user_question": "x" * 2001, "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_normalises_whitespace():
    state = {"user_question": "  How  do  I  install  SNO?  ", "trace": {}}
    result = input_guard(state)
    assert result["user_question"] == "How do I install SNO?"


def test_input_guard_clears_empty_context():
    state = {
        "user_question": "How does DNS work in SNO?",
        "conversation_context": [{"role": "user", "content": ""}],
        "trace": {},
    }
    result = input_guard(state)
    assert result["conversation_context"] == []


# ── classify_extract ─────────────────────────────────────────────────────────

def test_classify_extract_explicit_scope_satisfies_general_clarification():
    def _generate(_prompt):
        return """
        {
          "intent": "troubleshoot",
          "ocp_version": null,
          "deployment_type": null,
          "component": "api_server",
          "needs_clarification": true,
          "clarification_question": "What version of OpenShift are you using and is it a standard or Single Node OpenShift deployment?"
        }
        """

    state = {
        "user_question": "The OpenShift API server is not responding after installation.",
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = classify_extract(state, generate_fn=_generate)
    assert result["required_clarification"] is None


def test_classify_extract_keeps_deployment_clarification_for_sno_question():
    def _generate(_prompt):
        return """
        {
          "intent": "troubleshoot",
          "ocp_version": null,
          "deployment_type": null,
          "component": "bootstrap",
          "needs_clarification": true,
          "clarification_question": "What version of OpenShift are you using and is it a standard or Single Node OpenShift deployment?"
        }
        """

    state = {
        "user_question": "My SNO bootstrap is timing out.",
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = classify_extract(state, generate_fn=_generate)
    assert result["required_clarification"] is not None


# ── resolve_scope ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "How do I create a ServiceNow ticket for an OpenShift incident?",
    "Can you access my live OpenShift cluster and check the node status?",
    "How do I configure IBM Db2 on OpenShift?",
    "What is the latest version of Kubernetes released this week?",
    "Write me a Python script to automate OpenShift deployments.",
])
def test_resolve_scope_blocks_explicitly_excluded_topics(question):
    state = {
        "user_question": question,
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    }
    result = resolve_scope(state)
    assert result["status"] == "OUT_OF_SCOPE"
    assert result["intent"] == "unsupported"


def test_resolve_scope_clarifies_nmstateconfig_without_version():
    state = {
        "user_question": "What is the purpose of the NMStateConfig manifest in the agent-based installer?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    }
    result = resolve_scope(state)
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert "version" in result["required_clarification"].lower()


# ── retrieve ─────────────────────────────────────────────────────────────────

def test_retrieve_relaxes_component_and_inferred_deployment_filters(monkeypatch):
    calls = []

    def _hybrid_retrieve(query, filters, opensearch_client, embedding_fn):
        calls.append(filters)
        return [] if len(calls) == 1 else [{"chunk_id": "c1"}]

    monkeypatch.setattr(
        "app.retrieval.hybrid_retriever.hybrid_retrieve",
        _hybrid_retrieve,
    )
    state = {
        "user_question": "What is the rendezvous host in the Agent-based Installer workflow?",
        "retrieval_query": "What is the rendezvous host in the Agent-based Installer workflow?",
        "retrieval_filters": [
            {"term": {"components": "api_server"}},
            {"term": {"deployment_type": "compact"}},
            {"term": {"domain_id": "ocp_sno_support"}},
            {"term": {"is_current": True}},
        ],
        "trace": {},
    }

    result = retrieve_node.run(state, opensearch_client=object(), embedding_fn=lambda _: [0.0])

    assert result["candidates"] == [{"chunk_id": "c1"}]
    assert {"term": {"components": "api_server"}} not in calls[1]
    assert {"term": {"deployment_type": "compact"}} not in calls[1]
    assert {"term": {"is_current": True}} in calls[1]


def test_retrieve_keeps_explicit_deployment_filter(monkeypatch):
    calls = []

    def _hybrid_retrieve(query, filters, opensearch_client, embedding_fn):
        calls.append(filters)
        return []

    monkeypatch.setattr(
        "app.retrieval.hybrid_retriever.hybrid_retrieve",
        _hybrid_retrieve,
    )
    state = {
        "user_question": "What changed in the installation process?",
        "retrieval_query": "What changed in the installation process?",
        "retrieval_filters": [
            {"term": {"deployment_type": "SNO"}},
            {"term": {"is_current": True}},
        ],
        "trace": {"explicit_scope_keys": ["deployment_type"]},
    }

    retrieve_node.run(state, opensearch_client=object(), embedding_fn=lambda _: [0.0])

    assert {"term": {"deployment_type": "SNO"}} in calls[1]


# ── evidence_gate ─────────────────────────────────────────────────────────────

def _chunk(version="4.16"):
    return {
        "chunk_id": "c1",
        "ocp_version": version,
        "title": "SNO Guide",
        "chunk_text": "text",
        "document_id": "d1",
    }


def test_evidence_gate_sufficient():
    state = {
        "candidates": [_chunk("4.16")],
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = evidence_gate(state)
    assert result.get("status") != "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "sufficient"


def test_evidence_gate_no_candidates():
    state = {"candidates": [], "extracted_scope": {}, "trace": {}}
    result = evidence_gate(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "insufficient"


def test_evidence_gate_version_mismatch():
    state = {
        "candidates": [_chunk("4.14")],
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = evidence_gate(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


# ── validate_citations ────────────────────────────────────────────────────────

def test_validate_citations_valid():
    state = {
        "answer_markdown": "Check the DNS config [S1].",
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    assert result["status"] == "ANSWERED"
    assert len(result["citations"]) == 1
    assert result["citations"][0]["citation_id"] == "S1"


def test_validate_citations_no_citations_in_answer():
    state = {
        "answer_markdown": "No citations here.",
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    # No citations cited → answer is technically valid but empty citations list
    assert result["status"] == "ANSWERED"
    assert result["citations"] == []


def test_validate_citations_invalid_index():
    state = {
        "answer_markdown": "See [S5] for details.",  # only 1 candidate
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
