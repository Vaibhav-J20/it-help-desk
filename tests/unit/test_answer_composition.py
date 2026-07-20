"""Focused regressions for answer composition and citation validation."""
from __future__ import annotations

import pytest

from app.graph.citation_contract import normalize_citation_markers
from app.graph.nodes import compose_answer
from app.graph.nodes.validate_citations import run as validate_citations


def _web_lifecycle_candidate() -> dict:
    return {
        "chunk_id": "official_live_web:tls-lifecycle",
        "document_id": "web-tls-lifecycle",
        "title": "How to change the lifespan for internal-tls?",
        "product": "IBM Cloud Pak for Data",
        "product_version": "5.4.x",
        "section_path": "Summary",
        "chunk_text": (
            "The internal-tls certificate updates every 60 days and expires "
            "in 90 days. The renewal happens 30 days before expiry."
        ),
        "source_uri": "https://www.ibm.com/support/pages/how-change-lifespan-internal-tls",
        "retrieval_origin": "official_live_web",
        "web_search_provider": "tavily",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Claim 【S1】.", "Claim [S1]."),
        ("Claim ［Ｓ１］.", "Claim [S1]."),
        ("Claim (source 2).", "Claim [S2]."),
        ("Claim [Source: S1].", "Claim [S1]."),
        ("Claim [S 1, S2].", "Claim [S1][S2]."),
        ("Claim 【S1†source】.", "Claim [S1]."),
        ("Claims [S1-S3].", "Claims [S1][S2][S3]."),
    ],
)
def test_normalize_common_citation_variants(raw: str, expected: str):
    assert normalize_citation_markers(raw) == expected


def test_normalization_preserves_non_citation_parenthetical():
    assert normalize_citation_markers("Use server (S1 is the standby node).") == (
        "Use server (S1 is the standby node)."
    )


def test_validate_normalizes_even_when_composer_is_bypassed():
    result = validate_citations({
        "user_question": "What is documented?",
        "answer_markdown": "The fact is documented [S 1].",
        "candidates": [_web_lifecycle_candidate()],
        "trace": {},
    })

    assert result["status"] == "ANSWERED"
    assert result["answer_markdown"] == "The fact is documented [S1]."
    assert result["citations"][0]["source_uri"].startswith("https://www.ibm.com/")


def test_cited_automatic_lifecycle_correction_is_not_rejected_as_refusal():
    result = validate_citations({
        "user_question": (
            "What commands rotate internal TLS certificates in Cloud Pak for "
            "Data 5.4.x?"
        ),
        "answer_markdown": (
            "### Internal TLS certificate lifecycle\n\n"
            "The provided evidence does not include a manual rotation command "
            "because the internal-tls certificate is updated every 60 days and "
            "is renewed 30 days before expiry [S1]."
        ),
        "candidates": [_web_lifecycle_candidate()],
        "trace": {},
    })

    assert result["status"] == "ANSWERED"
    assert result["citations"][0]["citation_id"] == "S1"


def test_lifecycle_wording_does_not_override_unsupported_evidence():
    candidate = {
        **_web_lifecycle_candidate(),
        "chunk_text": "Cloud Pak for Data uses internal TLS certificates.",
    }
    result = validate_citations({
        "user_question": "What commands rotate internal TLS certificates?",
        "answer_markdown": (
            "The provided evidence does not include the requested command, but "
            "renewal happens automatically [S1]."
        ),
        "candidates": [candidate],
        "trace": {},
    })

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["trace"]["validate_citations"]["reason"] == (
        "answer_disclaims_requested_evidence"
    )


def test_web_grounded_draft_gets_one_bounded_citation_repair():
    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "I cannot provide that information right now."
        return (
            "### Internal TLS certificate lifecycle\n\n"
            "The internal-tls certificate updates every 60 days, with renewal "
            "30 days before expiry [S1]."
        )

    composed = compose_answer.run(
        {
            "user_question": "How do I rotate the internal TLS certificate?",
            "candidates": [_web_lifecycle_candidate()],
            "trace": {},
        },
        generate_fn=generate,
    )
    validated = validate_citations(composed)

    assert len(calls) == 2
    assert "OUTPUT-CONTRACT REPAIR (one attempt only)" in calls[1]
    assert composed["trace"]["composition_repair_attempted"] is True
    assert composed["trace"]["compose_answer"]["repair_succeeded"] is True
    assert validated["status"] == "ANSWERED"


def test_web_grounded_repair_is_never_attempted_more_than_once():
    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        return "Still no citation."

    result = compose_answer.run(
        {
            "user_question": "How do I rotate the internal TLS certificate?",
            "candidates": [_web_lifecycle_candidate()],
            "trace": {},
        },
        generate_fn=generate,
    )

    assert len(calls) == 2
    assert result["trace"]["compose_answer"]["repair_attempted"] is True
    assert result["trace"]["compose_answer"]["repair_succeeded"] is False
    assert result["trace"]["compose_answer"]["remaining_failure_reason"] == (
        "no_citations"
    )


def test_indexed_draft_does_not_spend_web_repair_call():
    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        return "No citation."

    result = compose_answer.run(
        {
            "user_question": "What is documented?",
            "candidates": [{
                **_web_lifecycle_candidate(),
                "retrieval_origin": "opensearch",
                "web_search_provider": None,
            }],
            "trace": {},
        },
        generate_fn=generate,
    )

    assert len(calls) == 1
    assert result["trace"]["compose_answer"]["repair_attempted"] is False
