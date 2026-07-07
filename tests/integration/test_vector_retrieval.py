"""
Integration tests for vector search and hybrid RRF retrieval.
Requires: OpenSearch running + watsonx.ai credentials in .env
"""
import json
import pytest
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_chunk.json"
VECTOR_TEST_INDEX = "test_vector_integration"


def _services_available() -> bool:
    try:
        from app.retrieval.opensearch_client import ping_opensearch
        from app.providers.watsonx_embeddings import ping_watsonx_embeddings
        return ping_opensearch() and ping_watsonx_embeddings()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _services_available(),
    reason="OpenSearch or watsonx.ai not available",
)


@pytest.fixture(scope="module")
def vector_index():
    from app.retrieval.opensearch_client import get_opensearch_client
    from app.providers.watsonx_embeddings import embed_text

    client = get_opensearch_client()
    chunk = json.loads(FIXTURE.read_text())
    vector = embed_text(chunk["chunk_text"])
    dim = len(vector)

    if client.indices.exists(index=VECTOR_TEST_INDEX):
        client.indices.delete(index=VECTOR_TEST_INDEX)

    client.indices.create(index=VECTOR_TEST_INDEX, body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0, "knn": True},
        "mappings": {"properties": {
            "chunk_id":          {"type": "keyword"},
            "ocp_version":       {"type": "keyword"},
            "deployment_type":   {"type": "keyword"},
            "is_current":        {"type": "boolean"},
            "chunk_text":        {"type": "text", "analyzer": "english"},
            "chunk_text_vector": {
                "type": "knn_vector", "dimension": dim,
                "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
            },
        }}
    })

    chunk["chunk_text_vector"] = vector
    client.index(index=VECTOR_TEST_INDEX, id=chunk["chunk_id"], body=chunk, refresh="wait_for")

    yield {"client": client, "chunk": chunk, "dim": dim}

    client.indices.delete(index=VECTOR_TEST_INDEX)


def test_vector_search_returns_correct_chunk(vector_index):
    from app.providers.watsonx_embeddings import embed_text
    client = vector_index["client"]
    chunk = vector_index["chunk"]

    query_vec = embed_text("DNS configuration for SNO bootstrap installation")
    resp = client.search(index=VECTOR_TEST_INDEX, body={
        "size": 5,
        "query": {"knn": {"chunk_text_vector": {"vector": query_vec, "k": 5}}},
        "_source": {"excludes": ["chunk_text_vector"]},
    })
    hits = resp["hits"]["hits"]
    assert hits, "Vector search returned no hits"
    assert hits[0]["_source"]["chunk_id"] == chunk["chunk_id"]


def test_hybrid_rrf_returns_correct_chunk(vector_index):
    from app.retrieval.hybrid_retriever import hybrid_retrieve
    from app.retrieval.filters import build_filters
    from app.providers.watsonx_embeddings import embed_text
    from app.core.config import get_settings

    client = vector_index["client"]
    chunk = vector_index["chunk"]
    settings = get_settings()
    settings.__dict__["opensearch_index_chunks"] = VECTOR_TEST_INDEX

    filters = build_filters({"ocp_version": "4.16", "deployment_type": "SNO"})
    results = hybrid_retrieve("DNS SNO bootstrap", filters, client, embed_text)

    settings.__dict__["opensearch_index_chunks"] = "knowledge_chunks_v1"

    assert results, "Hybrid retrieval returned no results"
    assert results[0]["chunk_id"] == chunk["chunk_id"]
    assert "_rrf_score" in results[0]


def test_rrf_score_present_and_positive(vector_index):
    from app.retrieval.hybrid_retriever import hybrid_retrieve
    from app.retrieval.filters import build_filters
    from app.providers.watsonx_embeddings import embed_text
    from app.core.config import get_settings

    client = vector_index["client"]
    settings = get_settings()
    settings.__dict__["opensearch_index_chunks"] = VECTOR_TEST_INDEX

    filters = build_filters({})
    results = hybrid_retrieve("OpenShift installation", filters, client, embed_text)

    settings.__dict__["opensearch_index_chunks"] = "knowledge_chunks_v1"

    assert results[0]["_rrf_score"] > 0
