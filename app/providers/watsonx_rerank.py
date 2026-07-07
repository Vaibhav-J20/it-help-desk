"""
watsonx.ai rerank provider.
Disabled by default (ENABLE_RERANKER=false).
Only activated after baseline retrieval quality is proven.
"""
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


def rerank(query: str, candidates: list[dict], top_k: int = 6) -> list[dict]:
    """
    Rerank candidates using the configured watsonx.ai rerank model.
    Returns the input unchanged if ENABLE_RERANKER is false.

    Args:
        query:      The retrieval query string.
        candidates: List of chunk dicts (output of hybrid_retrieve).
        top_k:      How many reranked results to return.

    Returns:
        Reranked (or original) list of chunk dicts, capped at top_k.
    """
    settings = get_settings()

    if not settings.enable_reranker:
        return candidates[:top_k]

    if not settings.watsonx_rerank_model_id:
        logger.info("ENABLE_RERANKER=true but WATSONX_RERANK_MODEL_ID is not set — skipping rerank")
        return candidates[:top_k]

    # TODO: implement rerank call once baseline is proven (Day 9+)
    # from ibm_watsonx_ai.foundation_models import Rerank
    raise NotImplementedError(
        "Reranker is enabled but not yet implemented. "
        "Set ENABLE_RERANKER=false until baseline retrieval quality is proven."
    )
