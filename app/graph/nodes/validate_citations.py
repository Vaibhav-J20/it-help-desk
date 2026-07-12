"""
Node 7: validate_citations
Verifies that every [S#] label in the answer maps to a real retrieved chunk.
Rules:
  - An answer with NO [S#] citations is not grounded — return INSUFFICIENT_EVIDENCE.
  - An answer that cites an out-of-range index is also INSUFFICIENT_EVIDENCE.
  - Only an answer with at least one valid in-range citation reaches ANSWERED.
"""
import re
from app.graph.state import SupportState
from app.observability.logging import get_logger

logger = get_logger(__name__)
_CITATION_RE = re.compile(r"\[S(\d+)\]")


def run(state: SupportState) -> SupportState:
    answer = state.get("answer_markdown") or ""
    candidates = state.get("candidates") or []
    max_valid_index = len(candidates)

    cited_indices = {int(m) for m in _CITATION_RE.findall(answer)}

    # Guard 1: a generated answer with zero citations is not grounded.
    if not cited_indices:
        logger.info("validate_citations: answer contains no [S#] citations — not grounded")
        return {
            **state,
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": {
                **state.get("trace", {}),
                "validate_citations": {"invalid_indices": [], "reason": "no_citations"},
            },
        }

    # Guard 2: any cited index that is out of the candidates range is invalid.
    invalid = {i for i in cited_indices if i < 1 or i > max_valid_index}
    if invalid:
        logger.info(f"validate_citations: invalid indices {invalid} (max valid: {max_valid_index})")
        return {
            **state,
            "status": "INSUFFICIENT_EVIDENCE",
            "trace": {
                **state.get("trace", {}),
                "validate_citations": {"invalid_indices": list(invalid)},
            },
        }

    # All citations valid and at least one present.
    citations = _build_citations(cited_indices, candidates)

    return {
        **state,
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
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "section_path": chunk.get("section_path"),
                "document_id": chunk.get("document_id", ""),
                "chunk_id": chunk.get("chunk_id"),
            })
    return citations
