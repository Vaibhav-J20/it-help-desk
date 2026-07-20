"""
Evidence policy — thresholds and rules for the evidence gate.
All thresholds are configuration, never magic numbers buried in logic.
"""
from __future__ import annotations

import re

from app.retrieval.constraints import constrain_candidates, constraints_are_satisfied
from app.retrieval.section_ranker import candidate_set_is_confident


def is_evidence_sufficient(
    candidates: list[dict],
    requested_version: str | None,
    question: str = "",
    *,
    version_field: str | None = None,
) -> tuple[bool, str]:
    """
    Decide whether the retrieved candidates are sufficient to generate an answer.

    Args:
        candidates:         List of chunk dicts from hybrid_retrieve (RRF-ordered).
        requested_version:  Explicit OCP or IBM product version, if any.
        version_field:      Candidate field to validate (``ocp_version`` or
                            ``product_version``). Legacy callers may omit it.

    Returns:
        (sufficient: bool, reason: str)
        reason is a short machine-readable code used in trace logs.
    """
    if not candidates:
        return False, "no_candidates"

    if question and not constraints_are_satisfied(question, candidates):
        return False, "explicit_platform_mismatch"
    if question:
        candidates[:] = constrain_candidates(question, candidates)
        if not candidates:
            return False, "explicit_platform_mismatch"

    # Version conflict check: if user gave an explicit version, all top evidence
    # must match it — never silently use a different version.
    if requested_version:
        version_matched = [
            c for c in candidates
            if _versions_compatible(
                requested_version,
                _candidate_version(c, version_field),
            )
        ]
        if not version_matched:
            return False, "version_mismatch"

        # Replace candidates with only version-matched evidence
        candidates[:] = version_matched

    # Presence alone is not evidence. The retrieved text must cover both the
    # product/topic terms and the requested intent (commands, installation,
    # use cases, version discovery, rotation, and so on).
    # Production graph calls always include the user's question. Keep the
    # optional/questionless policy API usable for legacy callers that can only
    # validate presence and version compatibility; semantic topic/intent
    # confidence cannot be measured without a query.
    if question and not candidate_set_is_confident(question, candidates):
        return False, "insufficient_intent_or_topic_coverage"

    return True, "sufficient"


def _candidate_version(candidate: dict, version_field: str | None) -> str:
    if version_field:
        return str(candidate.get(version_field) or "").strip()
    return str(
        candidate.get("ocp_version") or candidate.get("product_version") or ""
    ).strip()


def _versions_compatible(requested: str, evidence: str) -> bool:
    """Compare exact versions, ``.x`` families, and explicit future support."""
    requested_normalized = requested.strip().casefold().removeprefix("v")
    evidence_normalized = evidence.strip().casefold().removeprefix("v")
    if not requested_normalized or not evidence_normalized:
        return False
    if requested_normalized == evidence_normalized:
        return True
    if {requested_normalized, evidence_normalized} <= {"current", "latest"}:
        return True

    requested_parts = _numeric_version_parts(requested_normalized)
    evidence_parts = _numeric_version_parts(evidence_normalized)
    if not requested_parts or not evidence_parts:
        return False

    if "future release" in evidence_normalized:
        width = max(len(requested_parts), len(evidence_parts))
        requested_padded = requested_parts + (0,) * (width - len(requested_parts))
        evidence_padded = evidence_parts + (0,) * (width - len(evidence_parts))
        return requested_padded >= evidence_padded

    requested_family = requested_normalized.endswith(".x")
    evidence_family = evidence_normalized.endswith(".x")
    if requested_family:
        return evidence_parts[:len(requested_parts)] == requested_parts
    if evidence_family:
        return requested_parts[:len(evidence_parts)] == evidence_parts

    width = max(len(requested_parts), len(evidence_parts))
    return (
        requested_parts + (0,) * (width - len(requested_parts))
        == evidence_parts + (0,) * (width - len(evidence_parts))
    )


def _numeric_version_parts(value: str) -> tuple[int, ...]:
    match = re.search(r"\d+(?:\.\d+)*", value)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))
