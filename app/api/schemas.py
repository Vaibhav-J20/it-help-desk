"""
API schemas — LOCKED CONTRACT.
Changes to this file require a PR reviewed by both Developer A and Developer B.
These models define the exact wire format for POST /v1/assist.
"""
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import uuid


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class RequestedScope(BaseModel):
    ocp_version: str | None = None
    deployment_type: Literal["SNO", "standard", "compact"] | None = None
    component: str | None = None


class AssistRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str | None = None
    conversation_context: list[ConversationMessage] = Field(default_factory=list, max_length=4)
    requested_scope: RequestedScope = Field(default_factory=RequestedScope)

    @field_validator("conversation_context")
    @classmethod
    def validate_context_total_length(cls, v: list[ConversationMessage]) -> list[ConversationMessage]:
        total = sum(len(m.content) for m in v)
        if total > 4000:
            raise ValueError("conversation_context total content exceeds 4000 characters")
        return v


class Citation(BaseModel):
    citation_id: str                          # e.g. "S1"
    title: str
    product: str
    ocp_version: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    document_id: str
    chunk_id: str | None = None


class AssistResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: Literal[
        "ANSWERED",
        "NEEDS_CLARIFICATION",
        "INSUFFICIENT_EVIDENCE",
        "OUT_OF_SCOPE",
        "INVALID_REQUEST",
        "ERROR",
    ]
    intent: Literal["qa", "troubleshoot", "summarize", "unsupported"] | None = None
    answer_markdown: str | None = None
    clarification_question: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    safety_note: str = (
        "Guidance is based only on the approved knowledge base; "
        "verify commands in your environment."
    )
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "degraded"]
    opensearch: bool
    watsonx: bool
