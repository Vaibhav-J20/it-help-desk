"""
Node 4: retrieve
Runs hybrid BM25 + vector retrieval with RRF fusion.
If the first attempt returns nothing, retries with relaxed inferred filters.
"""
from app.graph.state import SupportState
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Fields that were inferred (not explicitly from the user) and may be relaxed
_INFERRED_FIELDS = ["component", "domain_id"]


def run(state: SupportState, opensearch_client=None, embedding_fn=None) -> SupportState:
    """
    Args:
        state:             Current graph state.
        opensearch_client: Injected OpenSearch client.
        embedding_fn:      Injected callable(text: str) -> list[float].
    """
    if opensearch_client is None:
        from app.retrieval.opensearch_client import get_opensearch_client
        opensearch_client = get_opensearch_client()

    if embedding_fn is None:
        from app.providers.watsonx_embeddings import embed_text
        embedding_fn = embed_text

    from app.retrieval.hybrid_retriever import hybrid_retrieve
    from app.retrieval.filters import relax_inferred_filters

    query = state["retrieval_query"]
    filters = list(state.get("retrieval_filters") or [])

    candidates = hybrid_retrieve(query, filters, opensearch_client, embedding_fn)

    # Retry once with relaxed inferred filters if nothing returned
    if not candidates:
        logger.info("First retrieval returned 0 results — relaxing inferred filters and retrying")
        relaxed = relax_inferred_filters(filters, _INFERRED_FIELDS)
        candidates = hybrid_retrieve(query, relaxed, opensearch_client, embedding_fn)

    return {
        **state,
        "candidates": candidates,
        "trace": {
            **state.get("trace", {}),
            "retrieve": {"candidate_count": len(candidates)},
        },
    }
