"""
Hybrid retriever: BM25 lexical + vector kNN, fused with RRF.
"""
from typing import Callable
from opensearchpy import OpenSearch
from app.core.config import get_settings
from app.retrieval.fusion import reciprocal_rank_fusion
from app.observability.logging import get_logger

logger = get_logger(__name__)


def hybrid_retrieve(
    query: str,
    filters: list[dict],
    opensearch_client: OpenSearch,
    embedding_fn: Callable[[str], list[float]],
) -> list[dict]:
    """
    Run BM25 + vector kNN retrieval, merge with RRF, return top candidates.

    Args:
        query:             The retrieval query string (may differ from raw user question).
        filters:           OpenSearch filter clauses from build_filters().
        opensearch_client: Injected OpenSearch client.
        embedding_fn:      Callable that takes a string and returns a float vector.

    Returns:
        List of chunk dicts ordered by descending RRF score, capped at
        settings.retrieval_top_candidates.
    """
    settings = get_settings()
    index = settings.opensearch_index_chunks

    bm25_results = _bm25_search(query, filters, opensearch_client, index, settings.retrieval_top_bm25)
    logger.info(f"BM25 returned {len(bm25_results)} results")

    query_vector = embedding_fn(query)
    vector_results = _vector_search(query_vector, filters, opensearch_client, index, settings.retrieval_top_vector)
    logger.info(f"Vector kNN returned {len(vector_results)} results")

    merged = reciprocal_rank_fusion(bm25_results, vector_results, k=settings.rrf_k)
    candidates = merged[: settings.retrieval_top_candidates]
    logger.info(f"RRF merged to {len(candidates)} candidates")

    return candidates


def _bm25_search(
    query: str,
    filters: list[dict],
    client: OpenSearch,
    index: str,
    size: int,
) -> list[dict]:
    body: dict = {
        "size": size,
        "query": {
            "bool": {
                "must": {"match": {"chunk_text": query}},
                "filter": filters,
            }
        },
        "_source": {"excludes": ["chunk_text_vector"]},
    }
    resp = client.search(index=index, body=body)
    return [hit["_source"] for hit in resp["hits"]["hits"]]


def _vector_search(
    vector: list[float],
    filters: list[dict],
    client: OpenSearch,
    index: str,
    size: int,
) -> list[dict]:
    body: dict = {
        "size": size,
        "query": {
            "bool": {
                "must": {
                    "knn": {
                        "chunk_text_vector": {
                            "vector": vector,
                            "k": size,
                        }
                    }
                },
                "filter": filters,
            }
        },
        "_source": {"excludes": ["chunk_text_vector"]},
    }
    resp = client.search(index=index, body=body)
    return [hit["_source"] for hit in resp["hits"]["hits"]]
