"""
Node 6: compose_answer
Builds the evidence-labelled prompt and calls watsonx.ai for answer generation.
Only runs after evidence_gate confirms sufficient evidence.
"""
from pathlib import Path
from app.graph.state import SupportState
from app.observability.logging import get_logger

logger = get_logger(__name__)
_PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "grounded_answer.md"


def run(state: SupportState, generate_fn=None) -> SupportState:
    if generate_fn is None:
        from app.providers.watsonx_chat import generate as generate_fn

    candidates = state.get("candidates") or []
    question = state["user_question"]

    evidence_blocks = _build_evidence_blocks(candidates)
    template = _PROMPT_FILE.read_text()
    prompt = (
        template
        .replace("{question}", question)
        .replace("{evidence_blocks}", evidence_blocks)
    )

    answer_markdown = generate_fn(prompt)

    return {
        **state,
        "answer_markdown": answer_markdown,
        "trace": {
            **state.get("trace", {}),
            "compose_answer": {"evidence_block_count": len(candidates)},
        },
    }


def _build_evidence_blocks(candidates: list[dict]) -> str:
    """
    Format candidates into numbered evidence blocks for the prompt.
    Each block is labelled [S1], [S2], etc.
    Only the chunk_text and minimal metadata are included — never raw internal URIs.
    """
    blocks = []
    for i, chunk in enumerate(candidates, start=1):
        label = f"[S{i}]"
        title = chunk.get("title", "Unknown document")
        product_label = _product_label(chunk)
        pages = ""
        if chunk.get("page_start") and chunk.get("page_end"):
            pages = f", pp. {chunk['page_start']}–{chunk['page_end']}"
        elif chunk.get("page_start"):
            pages = f", p. {chunk['page_start']}"
        section = chunk.get("section_path", "")
        text = chunk.get("chunk_text", "")
        header = f"{label} {title} — {product_label}{pages}"
        if section:
            header += f" ({section})"
        blocks.append(f"{header}\n{text}")
    return "\n\n".join(blocks)


def _product_label(chunk: dict) -> str:
    """Return a readable product/version label for source headers."""
    product = chunk.get("product") or "Knowledge base"
    version = chunk.get("ocp_version")
    if version:
        return f"{product} {version}"
    return str(product)
