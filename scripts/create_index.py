"""
scripts/create_index.py
Creates the two OpenSearch indices for the IT Help Desk Copilot.

Usage:
    python scripts/create_index.py
    python scripts/create_index.py --recreate    # drops and recreates if index exists

Index names and vector dimension come from settings (OPENSEARCH_INDEX_CHUNKS,
OPENSEARCH_INDEX_DOCS, OPENSEARCH_EMBEDDING_DIM).  Always verify that
OPENSEARCH_EMBEDDING_DIM matches the output dimension of your
WATSONX_EMBEDDING_MODEL_ID before running this against production data.

Embedding-model migration rule:
    When you change WATSONX_EMBEDDING_MODEL_ID to a new model you MUST run
    this script with --recreate (or point to new v3/v4/... index names) and
    re-ingest all documents.  Mixing vectors from different models in the same
    index produces silently broken retrieval.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.retrieval.opensearch_client import get_opensearch_client
from app.core.config import get_settings


def _build_chunks_mapping(embedding_dim: int) -> dict:
    """Return the chunks index mapping for the given vector dimension."""
    return {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "knn": True,  # enables the k-NN plugin for vector search
            }
        },
        "mappings": {
            "properties": {
                # Identity
                "chunk_id":           {"type": "keyword"},
                "document_id":        {"type": "keyword"},
                "revision_id":        {"type": "keyword"},

                # Source metadata
                "domain_id":          {"type": "keyword"},
                "title":              {"type": "keyword"},
                "source_uri":         {"type": "keyword", "index": False},  # stored, not filterable
                "source_type":        {"type": "keyword"},
                "document_type":      {"type": "keyword"},
                "classification":     {"type": "keyword"},
                "access_scope":       {"type": "keyword"},

                # Taxonomy filters — all keyword for exact match
                "product":            {"type": "keyword"},
                "ocp_version":        {"type": "keyword"},
                "ocp_major":          {"type": "integer"},
                "ocp_minor":          {"type": "integer"},
                "deployment_type":    {"type": "keyword"},
                "components":         {"type": "keyword"},
                "topic_tags":         {"type": "keyword"},

                # Location
                "section_path":       {"type": "keyword"},
                "page_start":         {"type": "integer"},
                "page_end":           {"type": "integer"},
                "chunk_ordinal":      {"type": "integer"},

                # Content
                "chunk_text": {
                    "type": "text",
                    "analyzer": "english",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    },
                },
                "chunk_text_vector": {
                    "type": "knn_vector",
                    "dimension": embedding_dim,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },

                # Provenance
                "content_hash":        {"type": "keyword"},
                "parser_version":      {"type": "keyword"},
                "chunker_version":     {"type": "keyword"},
                "embedding_model_id":  {"type": "keyword"},
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
            "document_id":      {"type": "keyword"},
            "revision_id":      {"type": "keyword"},
            "source_uri":       {"type": "keyword", "index": False},
            "source_filename":  {"type": "keyword"},
            "title":            {"type": "keyword"},
            "content_hash":     {"type": "keyword"},
            "metadata":         {"type": "object", "enabled": False},  # schema-free bag
            "ingestion_status": {"type": "keyword"},
            "chunk_count":      {"type": "integer"},
            "failed_pages":     {"type": "integer"},
            "last_error":       {"type": "text", "index": False},
            "ingested_at":      {"type": "date"},
        }
    },
}


def create_indices(recreate: bool = False) -> None:
    settings = get_settings()
    client = get_opensearch_client()
    embedding_dim = settings.opensearch_embedding_dim

    chunks_mapping = _build_chunks_mapping(embedding_dim)

    for index_name, mapping in [
        (settings.opensearch_index_chunks, chunks_mapping),
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
        print(f"  ✅ created index: {index_name}  (embedding_dim={embedding_dim})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create OpenSearch indices for the IT Help Desk Copilot")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate existing indices")
    args = parser.parse_args()

    print(f"Creating indices (recreate={args.recreate})...")
    create_indices(recreate=args.recreate)
    print("Done.")
