"""Shared answer/citation contract helpers.

The generator is allowed to vary typography, but the graph state exposes one
canonical citation format: ``[S#]``.  Keeping normalization and refusal checks
here makes composition and final validation apply the same rules.
"""
from __future__ import annotations

import re
import unicodedata


_CITATION_RE = re.compile(r"\[S(\d+)\]", re.IGNORECASE)
_CITATION_TOKEN_RE = re.compile(
    r"(?:(?:source|ref(?:erence)?)\s*[:#-]?\s*s?\s*|"
    r"s\s*[:#-]?\s*)(\d+)",
    re.IGNORECASE,
)
_CITATION_RANGE_RE = re.compile(
    r"\s*s\s*(\d+)\s*[-\u2013\u2014]\s*s?\s*(\d+)\s*",
    re.IGNORECASE,
)
_CITATION_CONTAINERS = (
    re.compile(r"\[(?P<body>[^\[\]\n]{1,96})\]"),
    re.compile(r"\u3010(?P<body>[^\u3010\u3011\n]{1,96})\u3011"),
    re.compile(r"\u3014(?P<body>[^\u3014\u3015\n]{1,96})\u3015"),
    re.compile(r"\uff3b(?P<body>[^\uff3b\uff3d\n]{1,96})\uff3d"),
    re.compile(r"\u3016(?P<body>[^\u3016\u3017\n]{1,96})\u3017"),
    re.compile(r"\((?P<body>[^()\n]{1,96})\)"),
    re.compile(r"\uff08(?P<body>[^\uff08\uff09\n]{1,96})\uff09"),
)
_LIMITATIONS_HEADING_RE = re.compile(
    r"\n#{2,6}\s+(?:what\s+(?:this|the\s+evidence)\s+does\s+not\s+"
    r"establish|limitations?|evidence\s+gaps?|gaps?)\b",
    re.IGNORECASE,
)
_LIFECYCLE_TOPIC_RE = re.compile(
    r"\b(?:internal[-\s]?tls|tls|certificates?|renew(?:al|ing|ed|s)?|"
    r"rotat(?:e|es|ed|ing|ion)|lifespan|expir(?:e|es|ed|y|ation))\b",
    re.IGNORECASE,
)
_AUTOMATIC_LIFECYCLE_RE = re.compile(
    r"\b(?:"
    r"automatically\s+(?:renew(?:ed|s|ing)?|rotat(?:e|es|ed|ing)?|"
    r"refresh(?:ed|es|ing)?|updat(?:e|es|ed|ing))|"
    r"(?:renewal|rotation|refresh|update)\s+"
    r"(?:automatically\s+)?(?:happens|occurs|runs|takes\s+place)|"
    r"(?:updates?|renews?|rotates?|refreshes?)\s+every\s+\d+\s+"
    r"(?:hours?|days?|weeks?|months?)|"
    r"(?:is|are)\s+automatically\s+"
    r"(?:renewed|rotated|refreshed|updated)|"
    r"(?:is|are)\s+(?:renewed|rotated|refreshed|updated)\s+every\s+\d+\s+"
    r"(?:hours?|days?|weeks?|months?)|"
    r"(?:is\s+)?renewed\s+\d+\s+days?\s+before\s+expir(?:y|ation)|"
    r"scheduled\s+(?:renewal|rotation|refresh|update)|"
    r"(?:manual|user[-\s]?initiated)\s+(?:renewal|rotation|refresh|update)\s+"
    r"(?:is\s+)?(?:not\s+required|unnecessary)"
    r")\b",
    re.IGNORECASE,
)
_DISCLAIMER_PATTERNS = (
    "provided evidence does not include",
    "evidence does not include",
    "evidence does not contain",
    "does not establish the exact",
    "necessary information is not provided",
    "requested information is not provided",
    "cannot provide the requested",
    "there is no information available",
    "no information is available",
    "evidence blocks do not mention",
    "does not establish what",
    "unable to provide the requested",
    "unable to answer the requested",
    "cannot answer the requested",
    "can't answer the requested",
    "could not be verified",
    "cannot be verified",
    "not enough information",
    "insufficient information",
    "insufficient evidence",
)


def normalize_citation_markers(answer: str) -> str:
    """Return model citation variants in canonical ``[S#]`` form.

    Only containers whose full contents look like citations are rewritten.  A
    normal parenthetical such as ``(S1 is a server)`` is therefore preserved.
    """
    normalized = str(answer or "")
    for pattern in _CITATION_CONTAINERS:
        normalized = pattern.sub(_normalize_container, normalized)
    return normalized


def citation_indices(answer: str) -> set[int]:
    """Extract canonical citation indices from an answer."""
    return {int(value) for value in _CITATION_RE.findall(answer)}


def citation_failure_reason(
    answer: str,
    candidates: list[dict],
    user_question: str = "",
) -> str | None:
    """Return the answer-contract failure that final validation would reject."""
    indices = citation_indices(answer)
    if not indices:
        return "no_citations"
    if any(index < 1 or index > len(candidates) for index in indices):
        return "invalid_citations"
    if answer_disclaims_requested_evidence(
        answer,
        candidates=candidates,
        user_question=user_question,
    ):
        return "answer_disclaims_requested_evidence"
    return None


def answer_disclaims_requested_evidence(
    answer: str,
    *,
    candidates: list[dict] | None = None,
    user_question: str = "",
) -> bool:
    """Detect a non-answer while preserving cited lifecycle corrections.

    A source-backed correction is a substantive answer.  For example, when a
    user asks for a manual certificate-rotation command and IBM documentation
    instead states a scheduled renewal lifecycle, wording such as "the evidence
    does not include a manual command" must not turn that answer into a refusal.
    """
    main_answer = _main_answer(answer)
    compact = " ".join(main_answer.casefold().split())
    if not any(pattern in compact for pattern in _DISCLAIMER_PATTERNS):
        return False
    if _has_cited_automatic_lifecycle_correction(
        main_answer,
        candidates or [],
        user_question,
    ):
        return False
    return True


def _normalize_container(match: re.Match[str]) -> str:
    original = match.group(0)
    body = unicodedata.normalize("NFKC", match.group("body")).strip()

    citation_range = _CITATION_RANGE_RE.fullmatch(body)
    if citation_range:
        start, end = (int(value) for value in citation_range.groups())
        if 1 <= start <= end and end - start <= 20:
            return "".join(f"[S{index}]" for index in range(start, end + 1))
        return original

    matches = list(_CITATION_TOKEN_RE.finditer(body))
    if not matches:
        return original

    residue = _CITATION_TOKEN_RE.sub("", body)
    # Some chat models append a provider-specific dagger annotation, for
    # example ``【S1†source】``.  It is not part of our citation ID.
    residue = re.sub(r"†[^,;/|&]+", "", residue)
    residue = re.sub(r"\band\b", "", residue, flags=re.IGNORECASE)
    residue = re.sub(r"[\s,;/|&:+]", "", residue)
    if residue:
        return original

    ordered_indices: list[int] = []
    for token in matches:
        index = int(token.group(1))
        if index not in ordered_indices:
            ordered_indices.append(index)
    return "".join(f"[S{index}]" for index in ordered_indices)


def _main_answer(answer: str) -> str:
    match = _LIMITATIONS_HEADING_RE.search(answer)
    return answer[:match.start()] if match else answer


def _has_cited_automatic_lifecycle_correction(
    main_answer: str,
    candidates: list[dict],
    user_question: str,
) -> bool:
    if not _LIFECYCLE_TOPIC_RE.search(user_question or main_answer):
        return False
    if not _AUTOMATIC_LIFECYCLE_RE.search(main_answer):
        return False

    for index in citation_indices(main_answer):
        if index < 1 or index > len(candidates):
            continue
        candidate = candidates[index - 1]
        evidence_text = " ".join(
            str(candidate.get(field) or "")
            for field in ("title", "section_path", "chunk_text")
        )
        if (
            _LIFECYCLE_TOPIC_RE.search(evidence_text)
            and _AUTOMATIC_LIFECYCLE_RE.search(evidence_text)
        ):
            return True
    return False
