"""
Node 4: retrieve
Runs hybrid BM25 + vector retrieval with RRF fusion.
If the first attempt returns nothing, retries with relaxed inferred filters.
"""
from app.graph.state import SupportState
from app.observability.logging import get_logger
import re

logger = get_logger(__name__)

# OpenSearch filter fields that may be relaxed on a zero-result retry.
# domain_id is intentionally absent: it is in filters._NEVER_RELAX and must
# never be relaxed — cross-domain chunk leakage would produce wrong-product
# citations (e.g. OpenShift chunks returned for a watsonx Orchestrate query).
_BASE_RELAXABLE_FILTER_FIELDS = ["components"]
_VERSION_RE = re.compile(r"\b4\.(?:14|15|16|17)\b")
_DEPLOYMENT_TERMS = (
    "sno",
    "single node",
    "single-node",
    "compact",
    "standard",
    "multi-node",
    "multinode",
)


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
        relaxed = relax_inferred_filters(filters, _relaxable_filter_fields(state))
        candidates = hybrid_retrieve(query, relaxed, opensearch_client, embedding_fn)

    return {
        **state,
        "candidates": candidates,
        "trace": {
            **state.get("trace", {}),
            "retrieve": {"candidate_count": len(candidates)},
        },
    }


def _relaxable_filter_fields(state: SupportState) -> list[str]:
    explicit_scope_keys = set((state.get("trace") or {}).get("explicit_scope_keys") or [])
    question = state.get("user_question", "")
    relaxable = list(_BASE_RELAXABLE_FILTER_FIELDS)

    if "deployment_type" not in explicit_scope_keys and not _mentions_deployment_type(question):
        relaxable.append("deployment_type")

    if "ocp_version" not in explicit_scope_keys and not _mentions_ocp_version(question):
        relaxable.append("ocp_version")

    return relaxable


def _mentions_ocp_version(question: str) -> bool:
    return bool(_VERSION_RE.search(question.lower()))


def _mentions_deployment_type(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in _DEPLOYMENT_TERMS)
