"""
Node 7: validate_citations
Verifies that every [S#] label in the answer maps to a real retrieved chunk.
Rules:
  - An answer with NO [S#] citations is not grounded — return INSUFFICIENT_EVIDENCE.
  - An answer that cites an out-of-range index is also INSUFFICIENT_EVIDENCE.
  - Only an answer with at least one valid in-range citation reaches ANSWERED.
"""
from app.graph.citation_contract import (
    answer_disclaims_requested_evidence,
    citation_indices,
    normalize_citation_markers,
)
from app.graph.state import SupportState
from app.observability.logging import get_logger

logger = get_logger(__name__)


def run(state: SupportState) -> SupportState:
    answer = normalize_citation_markers(state.get("answer_markdown") or "")
    candidates = state.get("candidates") or []
    max_valid_index = len(candidates)

    cited_indices = citation_indices(answer)

    # A cited refusal is still a refusal. Do not report ANSWERED when the model
    # explicitly says the retrieved evidence does not establish the requested
    # commands, procedure, version, or topic.
    if answer_disclaims_requested_evidence(
        answer,
        candidates=candidates,
        user_question=state.get("user_question", ""),
    ):
        logger.info(
            "validate_citations: generated answer disclaims requested evidence"
        )
        return {
            **state,
            "answer_markdown": None,
            "citations": [],
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": _retry_trace(
                state,
                reason="answer_disclaims_requested_evidence",
                invalid_indices=[],
            ),
        }

    # Guard 1: a generated answer with zero citations is not grounded.
    if not cited_indices:
        logger.info("validate_citations: answer contains no [S#] citations — not grounded")
        return {
            **state,
            "answer_markdown": None,
            "citations": [],
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": _retry_trace(
                state, reason="no_citations", invalid_indices=[]
            ),
        }

    # Guard 2: any cited index that is out of the candidates range is invalid.
    invalid = {i for i in cited_indices if i < 1 or i > max_valid_index}
    if invalid:
        logger.info(f"validate_citations: invalid indices {invalid} (max valid: {max_valid_index})")
        return {
            **state,
            "answer_markdown": None,
            "citations": [],
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": _retry_trace(
                state, reason="invalid_citations", invalid_indices=list(invalid)
            ),
        }

    # All citations valid and at least one present.
    citations = _build_citations(cited_indices, candidates)

    return {
        **state,
        "answer_markdown": answer,
        "citations": citations,
        "status": "ANSWERED",
        "trace": {
            **state.get("trace", {}),
            "validate_citations": {"cited_count": len(citations), "valid": True},
        },
    }


def _build_citations(cited_indices: set[int], candidates: list[dict]) -> list[dict]:
    citations = []
    for i in sorted(cited_indices):
        if 1 <= i <= len(candidates):
            chunk = candidates[i - 1]
            citations.append({
                "citation_id": f"S{i}",
                "title": chunk.get("title", ""),
                "product": chunk.get("product", ""),
                "ocp_version": chunk.get("ocp_version"),
                "product_version": chunk.get("product_version"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "section_path": chunk.get("section_path"),
                "document_id": chunk.get("document_id", ""),
                "chunk_id": chunk.get("chunk_id"),
                "source_uri": chunk.get("source_uri"),
                "retrieval_origin": chunk.get("retrieval_origin", "opensearch"),
                "web_search_provider": chunk.get("web_search_provider"),
            })
    return citations


def _retry_trace(
    state: SupportState,
    *,
    reason: str,
    invalid_indices: list[int],
) -> dict:
    """Request one broader retrieval pass after an indexed answer fails."""
    trace = dict(state.get("trace") or {})
    adaptive = (trace.get("retrieve") or {}).get("adaptive") or {}
    selected_stage = str(adaptive.get("selected_stage") or "")
    can_retry = (
        not trace.get("adaptive_retry_attempted")
        and selected_stage in {
            "opensearch",
            "persistent_cache",
            "global_metadata_catalog",
        }
    )
    if can_retry:
        trace["adaptive_retry_requested"] = True
    trace["validate_citations"] = {
        "invalid_indices": invalid_indices,
        "reason": reason,
        "adaptive_retry_requested": can_retry,
    }
    return trace
