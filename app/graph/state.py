"""
Graph state — LOCKED CONTRACT.
Changes to this file require a PR reviewed by both Developer A and Developer B.
SupportState is the shared mutable state passed between every LangGraph node.
"""
from typing import Literal, TypedDict


class SupportState(TypedDict, total=False):
    # Request
    request_id: str
    user_question: str
    conversation_context: list[dict]

    # Classification
    intent: Literal["qa", "troubleshoot", "summarize", "unsupported"]
    extracted_scope: dict       # e.g. {"ocp_version": "4.16", "deployment_type": "SNO"}
    required_clarification: str | None

    # Retrieval
    retrieval_query: str
    retrieval_filters: dict
    candidates: list[dict]      # list of chunk records from OpenSearch

    # Evidence decision
    evidence_decision: Literal[
        "sufficient",
        "insufficient",
        "conflicting",
        "out_of_scope",
        "clarify",
    ]

    # Answer
    answer_markdown: str
    citations: list[dict]

    # Final status
    status: Literal[
        "ANSWERED",
        "NEEDS_CLARIFICATION",
        "INSUFFICIENT_EVIDENCE",
        "OUT_OF_SCOPE",
        "INVALID_REQUEST",
        "ERROR",
    ]

    # Observability
    trace: dict
