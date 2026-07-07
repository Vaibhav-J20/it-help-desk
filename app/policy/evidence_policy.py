"""
Evidence policy — thresholds and rules for the evidence gate.
All thresholds are configuration, never magic numbers buried in logic.
"""
from app.core.config import get_settings


def is_evidence_sufficient(candidates: list[dict], requested_version: str | None) -> tuple[bool, str]:
    """
    Decide whether the retrieved candidates are sufficient to generate an answer.

    Args:
        candidates:         List of chunk dicts from hybrid_retrieve (RRF-ordered).
        requested_version:  Explicit OCP version from the user request, if any.

    Returns:
        (sufficient: bool, reason: str)
        reason is a short machine-readable code used in trace logs.
    """
    if not candidates:
        return False, "no_candidates"

    # Version conflict check: if user gave an explicit version, all top evidence
    # must match it — never silently use a different version.
    if requested_version:
        version_matched = [
            c for c in candidates
            if c.get("ocp_version") == requested_version
        ]
        if not version_matched:
            return False, "version_mismatch"

        # Replace candidates with only version-matched evidence
        candidates[:] = version_matched

    # Minimum candidate threshold
    settings = get_settings()
    if len(candidates) < 1:
        return False, "below_threshold"

    return True, "sufficient"
