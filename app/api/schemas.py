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
    # Explicit domain routing — takes precedence over classifier inference.
    domain_id: Literal[
        "ocp_sno_support", "watsonx_orchestrate", "ibm_bob", "ibm_products"
    ] | None = Field(
        default=None,
        description=(
            "Optional retrieval domain. Use ocp_sno_support for OpenShift/SNO, "
            "watsonx_orchestrate for watsonx Orchestrate/ADK, ibm_bob for IBM "
            "Bob, and ibm_products for all other registered IBM products. Omit "
            "the field when uncertain and let the service infer the domain."
        ),
    )
    # OCP-specific scope fields — only relevant when domain_id is ocp_sno_support.
    ocp_version: str | None = None
    deployment_type: Literal["SNO", "standard", "compact"] | None = None
    component: str | None = None
    product: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description=(
            "Canonical product name when known, primarily for ibm_products. "
            "Do not invent a product name; omit it when uncertain."
        ),
    )
    product_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            "Product version stated by the user. Preserve it exactly and omit "
            "it when the user did not specify a version."
        ),
    )


class AssistRequest(BaseModel):
    question: str = Field(
        min_length=3,
        max_length=2000,
        description="The user's technical question, passed without rewriting its meaning.",
    )
    conversation_id: str | None = None
    conversation_context: list[ConversationMessage] = Field(default_factory=list, max_length=4)
    requested_scope: RequestedScope = Field(
        default_factory=RequestedScope,
        description=(
            "Optional explicit routing hints. An empty object is valid; the "
            "backend can infer registered products and versions from the question."
        ),
    )

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
    product_version: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    document_id: str
    chunk_id: str | None = None
    source_uri: str | None = None
    retrieval_source: Literal[
        "opensearch_index",
        "metadata_catalog",
        "ibm_docs_cache",
        "live_ibm_docs",
        "internet_search",
    ] = Field(
        default="opensearch_index",
        description="Where the evidence for this citation was obtained.",
    )


class RetrievalProvenance(BaseModel):
    answer_sources: list[Literal[
        "opensearch_index",
        "metadata_catalog",
        "ibm_docs_cache",
        "live_ibm_docs",
        "internet_search",
    ]] = Field(
        default_factory=list,
        description="Knowledge sources actually cited in the final answer.",
    )
    opensearch_searched: bool = False
    metadata_catalog_searched: bool = False
    live_ibm_docs_retrieved: bool = False
    internet_search_performed: bool = False
    internet_search_provider: str | None = None
    summary: str = "No retrieval source was used."


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
    source_urls: list[str] = Field(
        default_factory=list,
        description="Deduplicated clickable HTTP(S) URLs cited by the final answer.",
    )
    suggested_next_steps: list[str] = Field(
        default_factory=list,
        description="Safe follow-up prompts that help the user continue the task.",
    )
    retrieval_provenance: RetrievalProvenance = Field(
        default_factory=RetrievalProvenance,
        description=(
            "Shows whether OpenSearch, bounded IBM Docs retrieval, cached pages, "
            "or an external internet-search provider was used."
        ),
    )
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
    adaptive_retrieval: bool
    live_ibm_docs_enabled: bool
    live_ibm_docs_configured: bool
    internet_search_enabled: bool
    internet_search_configured: bool


class DomainInfo(BaseModel):
    domain_id: str
    display_name: str
    chunk_count: int


class DomainsResponse(BaseModel):
    domains: list[DomainInfo]
