"""
Node 5: evidence_gate
Decides whether retrieved candidates are sufficient to generate a grounded answer.
This is the safety checkpoint — if evidence is insufficient, stop here.
"""
from app.graph.state import SupportState
from app.policy.evidence_policy import is_evidence_sufficient
from app.observability.logging import get_logger

logger = get_logger(__name__)


def run(state: SupportState) -> SupportState:
    candidates = list(state.get("candidates") or [])
    extracted_scope = state.get("extracted_scope") or {}
    requested_version = extracted_scope.get("ocp_version")

    sufficient, reason = is_evidence_sufficient(candidates, requested_version)

    if not sufficient:
        logger.info(f"evidence_gate: insufficient — reason={reason}")
        return {
            **state,
            "candidates": candidates,
            "evidence_decision": "insufficient",
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": {
                **state.get("trace", {}),
                "evidence_gate": {"decision": "insufficient", "reason": reason},
            },
        }

    from app.core.config import get_settings
    top_k = get_settings().evidence_top_k
    top_candidates = candidates[:top_k]

    return {
        **state,
        "candidates": top_candidates,
        "evidence_decision": "sufficient",
        "trace": {
            **state.get("trace", {}),
            "evidence_gate": {
                "decision": "sufficient",
                "evidence_count": len(top_candidates),
            },
        },
    }
