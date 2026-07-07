"""
scripts/create_index.py
Creates the two OpenSearch indices required for the V3 POC.

Usage:
    python scripts/create_index.py
    python scripts/create_index.py --recreate    # drops and recreates if index exists

The embedding vector dimension is read from the OPENSEARCH_EMBEDDING_DIM env var
(default 768). Set this to match the actual output of your watsonx.ai embedding model
before running against production data.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.retrieval.opensearch_client import get_opensearch_client
from app.core.config import get_settings

EMBEDDING_DIM = int(os.getenv("OPENSEARCH_EMBEDDING_DIM", "768"))


CHUNKS_MAPPING = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "knn": True,              # enables the k-NN plugin for vector search
        }
    },
    "mappings": {
        "properties": {
            # Identity
            "chunk_id":          {"type": "keyword"},
            "document_id":       {"type": "keyword"},
            "revision_id":       {"type": "keyword"},

            # Source metadata
            "domain_id":         {"type": "keyword"},
            "title":             {"type": "keyword"},
            "source_uri":        {"type": "keyword", "index": False},   # stored, not filterable by users
            "source_type":       {"type": "keyword"},
            "document_type":     {"type": "keyword"},
            "classification":    {"type": "keyword"},
            "access_scope":      {"type": "keyword"},

            # Taxonomy filters — all keyword for exact match
            "product":           {"type": "keyword"},
            "ocp_version":       {"type": "keyword"},
            "ocp_major":         {"type": "integer"},
            "ocp_minor":         {"type": "integer"},
            "deployment_type":   {"type": "keyword"},
            "components":        {"type": "keyword"},
            "topic_tags":        {"type": "keyword"},

            # Location
            "section_path":      {"type": "keyword"},
            "page_start":        {"type": "integer"},
            "page_end":          {"type": "integer"},
            "chunk_ordinal":     {"type": "integer"},

            # Content
            "chunk_text": {
                "type": "text",
                "analyzer": "english",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256}
                }
            },
            "chunk_text_vector": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIM,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                },
            },

            # Provenance
            "content_hash":       {"type": "keyword"},
            "parser_version":     {"type": "keyword"},
            "chunker_version":    {"type": "keyword"},
            "embedding_model_id": {"type": "keyword"},
            "embedding_dimension": {"type": "integer"},

            # Timestamps
            "published_at": {"type": "date"},
            "updated_at":   {"type": "date"},
            "ingested_at":  {"type": "date"},

            # Revision control
            "is_current": {"type": "boolean"},
        }
    },
}


DOCS_MAPPING = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }
    },
    "mappings": {
        "properties": {
            "document_id":       {"type": "keyword"},
            "revision_id":       {"type": "keyword"},
            "source_uri":        {"type": "keyword", "index": False},
            "source_filename":   {"type": "keyword"},
            "title":             {"type": "keyword"},
            "content_hash":      {"type": "keyword"},
            "metadata":          {"type": "object", "enabled": False},   # schema-free bag
            "ingestion_status":  {"type": "keyword"},
            "chunk_count":       {"type": "integer"},
            "failed_pages":      {"type": "integer"},
            "last_error":        {"type": "text", "index": False},
            "ingested_at":       {"type": "date"},
        }
    },
}


def create_indices(recreate: bool = False) -> None:
    settings = get_settings()
    client = get_opensearch_client()

    for index_name, mapping in [
        (settings.opensearch_index_chunks, CHUNKS_MAPPING),
        (settings.opensearch_index_docs, DOCS_MAPPING),
    ]:
        exists = client.indices.exists(index=index_name)

        if exists and recreate:
            client.indices.delete(index=index_name)
            print(f"  deleted existing index: {index_name}")
            exists = False

        if exists:
            print(f"  index already exists (skip): {index_name}")
            continue

        client.indices.create(index=index_name, body=mapping)
        print(f"  ✅ created index: {index_name}  (embedding_dim={EMBEDDING_DIM})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create OpenSearch indices for V3 POC")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate existing indices")
    args = parser.parse_args()

    print(f"Creating indices (recreate={args.recreate})...")
    create_indices(recreate=args.recreate)
    print("Done.")
