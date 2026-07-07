"""Unit tests for API request/response schemas."""
import pytest
from pydantic import ValidationError
from app.api.schemas import AssistRequest, AssistResponse, Citation, RequestedScope


def test_valid_request():
    req = AssistRequest(question="How do I configure DNS for SNO on OCP 4.16?")
    assert req.question == "How do I configure DNS for SNO on OCP 4.16?"
    assert req.conversation_context == []


def test_question_too_short():
    with pytest.raises(ValidationError):
        AssistRequest(question="Hi")


def test_question_too_long():
    with pytest.raises(ValidationError):
        AssistRequest(question="x" * 2001)


def test_conversation_context_limit():
    messages = [{"role": "user", "content": "msg"} for _ in range(5)]
    with pytest.raises(ValidationError):
        AssistRequest(question="valid question here", conversation_context=messages)


def test_conversation_context_total_length():
    # 4 messages × 1100 chars each = 4400 > 4000
    long_msg = "x" * 1100
    messages = [{"role": "user", "content": long_msg} for _ in range(4)]
    with pytest.raises(ValidationError):
        AssistRequest(question="valid question here", conversation_context=messages)


def test_requested_scope_optional():
    req = AssistRequest(question="How does SNO bootstrap work?")
    assert req.requested_scope.ocp_version is None
    assert req.requested_scope.deployment_type is None


def test_requested_scope_valid():
    req = AssistRequest(
        question="How does SNO bootstrap work?",
        requested_scope={"ocp_version": "4.16", "deployment_type": "SNO"},
    )
    assert req.requested_scope.ocp_version == "4.16"
    assert req.requested_scope.deployment_type == "SNO"


def test_invalid_deployment_type():
    with pytest.raises(ValidationError):
        AssistRequest(
            question="valid question here",
            requested_scope={"deployment_type": "INVALID"},
        )


def test_response_defaults():
    resp = AssistResponse(status="ANSWERED")
    assert resp.citations == []
    assert resp.request_id is not None
    assert resp.trace_id is not None


def test_citation_model():
    c = Citation(
        citation_id="S1",
        title="SNO Installation Guide",
        product="OpenShift",
        ocp_version="4.16",
        page_start=12,
        page_end=13,
        document_id="doc-abc",
    )
    assert c.citation_id == "S1"
