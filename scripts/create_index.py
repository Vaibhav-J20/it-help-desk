"""
OpenSearch Index Creation Script — OpenShift & SNO Support Copilot
Owner: Developer B
Script: scripts/create_index.py

Creates the two OpenSearch indices required by the ingestion pipeline:
  - knowledge_chunks_v1   (chunk documents with dense vector field)
  - knowledge_documents_v1 (document registry)

Run ONCE before first ingestion:
    python scripts/create_index.py

Safe to re-run — skips creation if index already exists.
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from opensearchpy import OpenSearch

load_dotenv()

logging.basicConfig(level="INFO", format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger(__name__)

CHUNKS_INDEX = os.getenv("OPENSEARCH_INDEX_CHUNKS", "knowledge_chunks_v1")
DOCS_INDEX = os.getenv("OPENSEARCH_INDEX_DOCS", "knowledge_documents_v1")


def _get_embedding_dimension() -> int:
    """Read embedding dimension from env or default to 768."""
    return int(os.getenv("EMBEDDING_DIMENSION", "768"))


CHUNKS_MAPPING = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
        }
    },
    "mappings": {
        "properties": {
            "chunk_id":             {"type": "keyword"},
            "document_id":          {"type": "keyword"},
            "revision_id":          {"type": "keyword"},
            "domain_id":            {"type": "keyword"},
            "title":                {"type": "text", "analyzer": "english"},
            "source_uri":           {"type": "keyword"},
            "source_type":          {"type": "keyword"},
            "document_type":        {"type": "keyword"},
            "classification":       {"type": "keyword"},
            "access_scope":         {"type": "keyword"},
            "product":              {"type": "keyword"},
            "ocp_version":          {"type": "keyword"},
            "ocp_major":            {"type": "integer"},
            "ocp_minor":            {"type": "integer"},
            "deployment_type":      {"type": "keyword"},
            "components":           {"type": "keyword"},
            "topic_tags":           {"type": "keyword"},
            "section_path":         {"type": "text"},
            "page_start":           {"type": "integer"},
            "page_end":             {"type": "integer"},
            "chunk_ordinal":        {"type": "integer"},
            "chunk_text":           {"type": "text", "analyzer": "english"},
            "chunk_text_vector": {
                "type": "knn_vector",
                "dimension": _get_embedding_dimension(),
                "method": {
                    "name": "hnsw",
                    "space_type": "l2",
                    "engine": "lucene",
                    "parameters": {"ef_construction": 128, "m": 24},
                },
            },
            "content_hash":         {"type": "keyword"},
            "parser_version":       {"type": "keyword"},
            "chunker_version":      {"type": "keyword"},
            "embedding_model_id":   {"type": "keyword"},
            "embedding_dimension":  {"type": "integer"},
            "ingested_at":          {"type": "date"},
            "is_current":           {"type": "boolean"},
        }
    },
}

DOCS_MAPPING = {
    "mappings": {
        "properties": {
            "document_id":      {"type": "keyword"},
            "revision_id":      {"type": "keyword"},
            "source_uri":       {"type": "keyword"},
            "source_filename":  {"type": "keyword"},
            "title":            {"type": "text"},
            "content_hash":     {"type": "keyword"},
            "metadata":         {"type": "object", "dynamic": True},
            "ingestion_status": {"type": "keyword"},
            "chunk_count":      {"type": "integer"},
            "failed_pages":     {"type": "integer"},
            "last_error":       {"type": "text"},
            "ingested_at":      {"type": "date"},
        }
    }
}


def create_indices(client: OpenSearch) -> None:
    for index_name, mapping in [
        (CHUNKS_INDEX, CHUNKS_MAPPING),
        (DOCS_INDEX, DOCS_MAPPING),
    ]:
        if client.indices.exists(index=index_name):
            logger.info("Index already exists — skipping: %s", index_name)
        else:
            client.indices.create(index=index_name, body=mapping)
            logger.info("Created index: %s", index_name)


def main() -> None:
    try:
        url = os.environ["OPENSEARCH_URL"]
        username = os.environ["OPENSEARCH_USERNAME"]
        password = os.environ["OPENSEARCH_PASSWORD"]
    except KeyError as e:
        logger.error("Missing required env var: %s. Check your .env file.", e)
        sys.exit(1)

    client = OpenSearch(
        hosts=[url],
        http_auth=(username, password),
        use_ssl=url.startswith("https"),
        verify_certs=False,
        ssl_show_warn=False,
    )

    logger.info("Connected to OpenSearch: %s", url)
    create_indices(client)
    logger.info("Index setup complete.")


if __name__ == "__main__":
    main()
