"""
scripts/smoke_test.py
End-to-end smoke test:
  1. Embed a test query
  2. Index the sample fixture chunk with a real embedding vector
  3. Run BM25 retrieval — verify chunk returned
  4. Run vector kNN retrieval — verify chunk returned
  5. Run hybrid RRF — verify chunk in top result

Usage:
    python scripts/smoke_test.py

Requires: OpenSearch running, watsonx.ai credentials set in .env
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.retrieval.opensearch_client import get_opensearch_client
from app.providers.watsonx_embeddings import embed_text
from app.retrieval.hybrid_retriever import hybrid_retrieve
from app.retrieval.filters import build_filters
from app.core.config import get_settings

FIXTURE = os.path.join(os.path.dirname(__file__), "../tests/fixtures/sample_chunk.json")
SMOKE_INDEX = "smoke_test_chunks"


def run():
    settings = get_settings()
    client = get_opensearch_client()

    print("\n=== Smoke Test ===\n")

    # 1. Embed a query
    print("1. Embedding test query...")
    query = "How do I configure DNS for SNO bootstrap?"
    vector = embed_text(query)
    print(f"   ✅ dim={len(vector)}")

    # 2. Create smoke index with kNN mapping
    print("2. Creating smoke index...")
    if client.indices.exists(index=SMOKE_INDEX):
        client.indices.delete(index=SMOKE_INDEX)

    client.indices.create(index=SMOKE_INDEX, body={
        "settings": {"number_of_shards": 1, "number_of_replicas": 0, "knn": True},
        "mappings": {"properties": {
            "chunk_id":        {"type": "keyword"},
            "ocp_version":     {"type": "keyword"},
            "deployment_type": {"type": "keyword"},
            "is_current":      {"type": "boolean"},
            "chunk_text":      {"type": "text", "analyzer": "english"},
            "chunk_text_vector": {
                "type": "knn_vector",
                "dimension": len(vector),
                "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
            },
        }}
    })
    print("   ✅ created")

    # 3. Index fixture chunk with real embedding
    print("3. Indexing fixture chunk with real embedding...")
    chunk = json.loads(open(FIXTURE).read())
    chunk["chunk_text_vector"] = embed_text(chunk["chunk_text"])
    client.index(index=SMOKE_INDEX, id=chunk["chunk_id"], body=chunk, refresh="wait_for")
    print("   ✅ indexed")

    # 4. BM25 retrieval
    print("4. BM25 retrieval...")
    resp = client.search(index=SMOKE_INDEX, body={
        "query": {"match": {"chunk_text": query}},
        "_source": {"excludes": ["chunk_text_vector"]},
    })
    hits = resp["hits"]["hits"]
    assert hits, "❌ BM25 returned no hits"
    assert hits[0]["_source"]["chunk_id"] == chunk["chunk_id"]
    print(f"   ✅ returned chunk_id={hits[0]['_source']['chunk_id']}")

    # 5. Vector kNN retrieval
    print("5. Vector kNN retrieval...")
    resp = client.search(index=SMOKE_INDEX, body={
        "size": 5,
        "query": {"knn": {"chunk_text_vector": {"vector": vector, "k": 5}}},
        "_source": {"excludes": ["chunk_text_vector"]},
    })
    hits = resp["hits"]["hits"]
    assert hits, "❌ Vector kNN returned no hits"
    assert hits[0]["_source"]["chunk_id"] == chunk["chunk_id"]
    print(f"   ✅ returned chunk_id={hits[0]['_source']['chunk_id']}")

    # 6. Hybrid RRF via hybrid_retriever (using smoke index override)
    print("6. Hybrid RRF retrieval...")
    # Temporarily patch settings index name for the smoke test
    original = settings.opensearch_index_chunks
    settings.__dict__["opensearch_index_chunks"] = SMOKE_INDEX

    filters = build_filters({"ocp_version": "4.16", "deployment_type": "SNO"})
    results = hybrid_retrieve(query, filters, client, embed_text)
    assert results, "❌ Hybrid retrieval returned no results"
    assert results[0]["chunk_id"] == chunk["chunk_id"]
    print(f"   ✅ top result: chunk_id={results[0]['chunk_id']}, rrf_score={results[0]['_rrf_score']}")

    settings.__dict__["opensearch_index_chunks"] = original

    # Cleanup
    client.indices.delete(index=SMOKE_INDEX)
    print("\n✅ All smoke tests passed.\n")


if __name__ == "__main__":
    run()
