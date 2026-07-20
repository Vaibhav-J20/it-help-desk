"""Deterministic explicit platform constraints for retrieval evidence."""

from __future__ import annotations

import re


_PLATFORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows", re.compile(r"\b(?:windows|powershell|win32|win64)\b", re.IGNORECASE)),
    ("linux_unix", re.compile(r"\b(?:linux|unix)\b", re.IGNORECASE)),
    ("macos", re.compile(r"\bmacos\b|\bmac\s+os\b|\bos\s*x\b", re.IGNORECASE)),
    ("aix", re.compile(r"\baix\b", re.IGNORECASE)),
    ("z_os", re.compile(r"(?<!\w)z/os(?!\w)|\bzos\b", re.IGNORECASE)),
    ("openshift", re.compile(r"\b(?:openshift|ocp)\b", re.IGNORECASE)),
    ("kubernetes", re.compile(r"\b(?:kubernetes|k8s)\b", re.IGNORECASE)),
)


def explicit_platform_constraints(question: str) -> tuple[str, ...]:
    """Return platform/OS facets the user explicitly named, in stable order."""
    return tuple(
        name for name, pattern in _PLATFORM_PATTERNS if pattern.search(question)
    )


def candidate_platform_constraints(candidate: dict) -> set[str]:
    """Return explicit platform facets supported by one evidence candidate."""
    haystack = " ".join((
        str(candidate.get("product") or ""),
        str(candidate.get("title") or ""),
        str(candidate.get("section_path") or ""),
        str(candidate.get("chunk_text") or ""),
        str(candidate.get("source_uri") or ""),
    ))
    return {
        name for name, pattern in _PLATFORM_PATTERNS if pattern.search(haystack)
    }


def constraints_are_satisfied(question: str, candidates: list[dict]) -> bool:
    """Require evidence for every platform/OS facet explicitly in the question."""
    required = set(explicit_platform_constraints(question))
    if not required:
        return True
    represented: set[str] = set()
    for candidate in candidates:
        represented.update(candidate_platform_constraints(candidate))
    return required.issubset(represented)


def constrain_candidates(question: str, candidates: list[dict]) -> list[dict]:
    """Remove evidence unrelated to explicit platform facets.

    A single-platform question keeps only evidence for that platform. A
    comparison naming multiple platforms keeps evidence for any named platform,
    while ``constraints_are_satisfied`` separately requires complete coverage.
    """
    required = set(explicit_platform_constraints(question))
    if not required:
        return list(candidates)
    return [
        candidate
        for candidate in candidates
        if candidate_platform_constraints(candidate) & required
    ]
