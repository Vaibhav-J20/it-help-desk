"""Unit tests for graph nodes (input_guard, evidence_gate, validate_citations)."""
import pytest
from app.graph.nodes.input_guard import run as input_guard
from app.graph.nodes.evidence_gate import run as evidence_gate
from app.graph.nodes.validate_citations import run as validate_citations


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
