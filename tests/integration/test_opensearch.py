"""
Integration tests for OpenSearch — index creation, BM25 retrieval, filter correctness.

Requirements:
    - OpenSearch running at OPENSEARCH_URL (default: http://localhost:9200)
    - Run: docker run -d --name opensearch-poc -p 9200:9200
             -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true
             opensearchproject/opensearch:2.15.0

Skip automatically if OpenSearch is not reachable.
"""
import json
import time
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _opensearch_available() -> bool:
    try:
        from app.retrieval.opensearch_client import ping_opensearch
        return ping_opensearch()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _opensearch_available(),
    reason="OpenSearch not reachable — start local container to run integration tests",
)

TEST_INDEX = "test_knowledge_chunks_integration"


@pytest.fixture(scope="module")
def os_client():
    from app.retrieval.opensearch_client import get_opensearch_client
    client = get_opensearch_client()

    # Create a minimal test index
    if client.indices.exists(index=TEST_INDEX):
        client.indices.delete(index=TEST_INDEX)

    client.indices.create(index=TEST_INDEX, body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "properties": {
                "chunk_id":        {"type": "keyword"},
                "document_id":     {"type": "keyword"},
                "domain_id":       {"type": "keyword"},
                "ocp_version":     {"type": "keyword"},
                "ocp_major":       {"type": "integer"},
                "ocp_minor":       {"type": "integer"},
                "deployment_type": {"type": "keyword"},
                "components":      {"type": "keyword"},
                "page_start":      {"type": "integer"},
                "page_end":        {"type": "integer"},
                "is_current":      {"type": "boolean"},
                "chunk_text": {"type": "text", "analyzer": "english"},
                "title":           {"type": "keyword"},
            }
        },
    })

    # Load and index the fixture chunk
    chunk = json.loads((FIXTURE_DIR / "sample_chunk.json").read_text())
    chunk_for_test = {k: v for k, v in chunk.items() if k != "chunk_text_vector"}
    client.index(index=TEST_INDEX, id=chunk["chunk_id"], body=chunk_for_test, refresh="wait_for")

    yield client

    # Teardown
    client.indices.delete(index=TEST_INDEX)


def test_index_exists(os_client):
    assert os_client.indices.exists(index=TEST_INDEX)


def test_bm25_retrieves_dns_chunk(os_client):
    """A query about DNS should retrieve the fixture chunk."""
    resp = os_client.search(index=TEST_INDEX, body={
        "query": {"match": {"chunk_text": "DNS bootstrap SNO installation"}}
    })
    hits = resp["hits"]["hits"]
    assert len(hits) > 0, "Expected at least one hit for DNS query"
    assert hits[0]["_source"]["chunk_id"] == "ocp_sno_support:doc-test01:rev-20260101:chunk-0001"


def test_filter_by_ocp_version(os_client):
    """Filter for ocp_version=4.16 should return the chunk."""
    resp = os_client.search(index=TEST_INDEX, body={
        "query": {
            "bool": {
                "must": {"match_all": {}},
                "filter": [{"term": {"ocp_version": "4.16"}}],
            }
        }
    })
    assert resp["hits"]["total"]["value"] == 1
    assert resp["hits"]["hits"][0]["_source"]["ocp_version"] == "4.16"


def test_filter_wrong_version_returns_nothing(os_client):
    """Filter for a version not in the index should return 0 hits."""
    resp = os_client.search(index=TEST_INDEX, body={
        "query": {
            "bool": {
                "must": {"match": {"chunk_text": "DNS"}},
                "filter": [{"term": {"ocp_version": "4.99"}}],
            }
        }
    })
    assert resp["hits"]["total"]["value"] == 0


def test_filter_by_deployment_type_sno(os_client):
    """Filter for SNO deployment_type should return the chunk."""
    resp = os_client.search(index=TEST_INDEX, body={
        "query": {
            "bool": {
                "must": {"match_all": {}},
                "filter": [{"term": {"deployment_type": "SNO"}}],
            }
        }
    })
    assert resp["hits"]["total"]["value"] == 1


def test_filter_by_is_current(os_client):
    """is_current=true filter should return the chunk."""
    resp = os_client.search(index=TEST_INDEX, body={
        "query": {
            "bool": {
                "must": {"match_all": {}},
                "filter": [{"term": {"is_current": True}}],
            }
        }
    })
    assert resp["hits"]["total"]["value"] == 1


def test_page_fields_round_trip(os_client):
    """page_start and page_end must be stored and returned correctly."""
    resp = os_client.get(index=TEST_INDEX, id="ocp_sno_support:doc-test01:rev-20260101:chunk-0001")
    src = resp["_source"]
    assert src["page_start"] == 12
    assert src["page_end"] == 13


def test_chunk_text_content(os_client):
    """chunk_text must be stored and retrievable."""
    resp = os_client.get(index=TEST_INDEX, id="ocp_sno_support:doc-test01:rev-20260101:chunk-0001")
    assert "DNS records" in resp["_source"]["chunk_text"]
