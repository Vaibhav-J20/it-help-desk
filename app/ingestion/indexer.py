"""
OpenSearch Indexer — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/indexer.py

Idempotent indexer that writes chunk records and document registry entries
to OpenSearch. Re-ingesting a document with the same content_hash is a NO-OP.
Re-ingesting a changed document creates a new revision and marks the old one
is_current=false.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from app.ingestion.chunker import ChunkRecord
from app.ingestion.pdf_parser import ParseResult

logger = logging.getLogger(__name__)

CHUNKS_INDEX = os.getenv("OPENSEARCH_INDEX_CHUNKS", "knowledge_chunks_v1")
DOCS_INDEX = os.getenv("OPENSEARCH_INDEX_DOCS", "knowledge_documents_v1")
EMBEDDING_BATCH_SIZE = int(os.getenv("INGESTION_EMBEDDING_BATCH_SIZE", "16"))
OPENSEARCH_BULK_CHUNK_BATCH_SIZE = int(os.getenv("OPENSEARCH_BULK_CHUNK_BATCH_SIZE", "500"))


@dataclass
class IngestionSummary:
    source_uri: str
    status: str          # INDEXED | SKIPPED | FAILED
    document_id: str
    revision_id: str
    chunks_indexed: int
    chunks_skipped: int
    error: str | None = None


def _make_document_id(source_uri: str) -> str:
    """Stable 8-char document ID from source URI hash."""
    return "doc-" + hashlib.sha256(source_uri.encode()).hexdigest()[:4]


def _make_revision_id(content_hash: str) -> str:
    """Revision ID: date + first 12 chars of content hash."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hash_short = content_hash.removeprefix("sha256:")[:12]
    return f"rev-{date_str}-{hash_short}"


def _make_chunk_id(domain_id: str, document_id: str, revision_id: str, ordinal: int) -> str:
    return f"{domain_id}:{document_id}:{revision_id}:chunk-{ordinal:04d}"


def _get_embedding_model_id() -> str:
    model_id = os.getenv("WATSONX_EMBEDDING_MODEL_ID")
    if not model_id:
        raise EnvironmentError(
            "WATSONX_EMBEDDING_MODEL_ID env var is not set. "
            "Get the value from Developer A and add it to .env."
        )
    return model_id


def _mark_old_revisions_superseded(
    client, document_id: str, current_revision_id: str
) -> int:
    """Set is_current=false on all chunks from previous revisions of this document."""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"document_id": document_id}},
                    {"term": {"is_current": True}},
                ],
                "must_not": [{"term": {"revision_id": current_revision_id}}],
            }
        },
        "script": {"source": "ctx._source.is_current = false", "lang": "painless"},
    }
    resp = client.update_by_query(index=CHUNKS_INDEX, body=query, refresh=True)
    updated = resp.get("updated", 0)
    if updated:
        logger.info("Marked %d old chunks as is_current=false for document %s", updated, document_id)
    return updated


def _delete_existing_revision_chunks(client, document_id: str, revision_id: str) -> int:
    """Remove existing chunk docs for a revision before an explicit re-index."""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"document_id": document_id}},
                    {"term": {"revision_id": revision_id}},
                ]
            }
        }
    }
    resp = client.delete_by_query(
        index=CHUNKS_INDEX,
        body=query,
        refresh=True,
        conflicts="proceed",
    )
    deleted = resp.get("deleted", 0)
    if deleted:
        logger.info(
            "Deleted %d existing chunks for forced re-index of %s / %s",
            deleted,
            document_id,
            revision_id,
        )
    return deleted


def index_document(
    parse_result: ParseResult,
    chunks: list[ChunkRecord],
    metadata: dict,
    opensearch_client,
    embedding_fn,
    force_reindex: bool = False,
) -> IngestionSummary:
    """
    Index a parsed document and its chunks into OpenSearch.

    Args:
        parse_result:       Output of pdf_parser.parse_pdf()
        chunks:             Output of chunker.chunk_pages()
        metadata:           Validated metadata dict from corpus manifest
        opensearch_client:  An opensearch-py OpenSearch client instance
        embedding_fn:       Callable(text: str) -> list[float] — provided by Developer A's provider
        force_reindex:      When true, refresh this revision even if content_hash is unchanged

    Returns:
        IngestionSummary with counts and final status.
    """
    document_id = _make_document_id(parse_result.source_uri)
    revision_id = _make_revision_id(parse_result.content_hash)
    embedding_model_id = _get_embedding_model_id()

    # --- Idempotency check: skip if same content_hash already indexed ---
    try:
        existing = opensearch_client.get(index=DOCS_INDEX, id=revision_id, ignore=[404])
        if (
            existing.get("found")
            and existing["_source"].get("ingestion_status") == "INDEXED"
            and not force_reindex
        ):
            logger.info(
                "SKIPPED %s — revision %s already indexed with same content_hash",
                parse_result.source_uri, revision_id,
            )
            return IngestionSummary(
                source_uri=parse_result.source_uri,
                status="SKIPPED",
                document_id=document_id,
                revision_id=revision_id,
                chunks_indexed=0,
                chunks_skipped=len(chunks),
            )
    except Exception as e:
        logger.warning("Could not check existing revision: %s", e)

    now_iso = datetime.now(timezone.utc).isoformat()

    if force_reindex:
        _delete_existing_revision_chunks(opensearch_client, document_id, revision_id)

    # --- Write document registry entry (status: PARSED) ---
    doc_record = {
        "document_id": document_id,
        "revision_id": revision_id,
        "source_uri": parse_result.source_uri,
        "source_filename": parse_result.source_uri.split("/")[-1],
        "title": metadata["title"],
        "content_hash": parse_result.content_hash,
        "metadata": metadata,
        "ingestion_status": "PARSED",
        "chunk_count": len(chunks),
        "failed_pages": [],
        "last_error": None,
        "ingested_at": now_iso,
    }
    opensearch_client.index(index=DOCS_INDEX, id=revision_id, body=doc_record)
    logger.info("Document registry entry created: %s / %s", document_id, revision_id)

    # --- Bulk index all chunks ---
    ocp_version = metadata.get("ocp_version")
    ocp_major, ocp_minor = _parse_version(ocp_version)
    deployment_type = metadata.get("deployment_type") or []
    if isinstance(deployment_type, str):
        deployment_type = [deployment_type]
    source_type = metadata.get("source_type") or ("pdf" if parse_result.source_uri.lower().endswith(".pdf") else "web")

    indexed_count = 0
    vectors_by_ordinal, failed_pages = _embed_chunks(chunks, embedding_fn)

    bulk_body = []
    for chunk in chunks:
        chunk_id = _make_chunk_id(metadata["domain_id"], document_id, revision_id, chunk.chunk_ordinal)
        vector = vectors_by_ordinal.get(chunk.chunk_ordinal)
        if vector is None:
            continue

        chunk_doc = {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "revision_id": revision_id,

            "domain_id": metadata["domain_id"],
            "title": metadata["title"],
            "source_uri": parse_result.source_uri,
            "source_type": source_type,
            "document_type": metadata["document_type"],
            "classification": metadata["classification"],
            "access_scope": metadata.get("access_scope", ["isa_technical"]),

            "product": metadata["product"],
            "ocp_version": ocp_version,
            "ocp_major": ocp_major,
            "ocp_minor": ocp_minor,
            "deployment_type": deployment_type,
            "components": metadata.get("components", []),
            "topic_tags": metadata.get("topic_tags", []),

            "section_path": chunk.section_path,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chunk_ordinal": chunk.chunk_ordinal,
            "chunk_text": chunk.text,
            "chunk_text_vector": vector,

            "content_hash": chunk.content_hash,
            "parser_version": parse_result.parser_version,
            "chunker_version": chunk.chunker_version,
            "embedding_model_id": embedding_model_id,
            "embedding_dimension": len(vector),

            "ingested_at": now_iso,
            "is_current": True,
        }
        bulk_body.append({"index": {"_index": CHUNKS_INDEX, "_id": chunk_id}})
        bulk_body.append(chunk_doc)
        indexed_count += 1

    _bulk_index_chunks(opensearch_client, bulk_body)

    # --- Mark old revisions as superseded ---
    _mark_old_revisions_superseded(opensearch_client, document_id, revision_id)

    # --- Update document registry to INDEXED ---
    final_status = "INDEXED" if not failed_pages else "INDEXED"  # partial indexing still marked INDEXED
    opensearch_client.update(
        index=DOCS_INDEX,
        id=revision_id,
        body={"doc": {
            "ingestion_status": final_status,
            "chunk_count": indexed_count,
            "failed_pages": failed_pages,
        }},
    )

    logger.info(
        "Indexed %s: %d chunks indexed, %d failed pages",
        parse_result.source_uri, indexed_count, len(failed_pages),
    )

    return IngestionSummary(
        source_uri=parse_result.source_uri,
        status=final_status,
        document_id=document_id,
        revision_id=revision_id,
        chunks_indexed=indexed_count,
        chunks_skipped=0,
        error=str(failed_pages) if failed_pages else None,
    )


def _parse_version(ocp_version: str | None) -> tuple[int, int]:
    """Parse '4.16' into (4, 16). Returns (0, 0) on failure."""
    if not ocp_version:
        return 0, 0
    try:
        parts = str(ocp_version).split(".")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        logger.warning("Could not parse ocp_version '%s' into major.minor", ocp_version)
        return 0, 0


def _bulk_index_chunks(client, bulk_body: list[dict]) -> None:
    """Write chunk docs in bounded batches to avoid OpenSearch 413 errors."""
    if not bulk_body:
        return

    docs_per_batch = max(1, OPENSEARCH_BULK_CHUNK_BATCH_SIZE)
    items_per_batch = docs_per_batch * 2  # each chunk has an action row and a document row

    for start in range(0, len(bulk_body), items_per_batch):
        batch = bulk_body[start:start + items_per_batch]
        resp = client.bulk(body=batch, refresh=True)
        if resp.get("errors"):
            for item in resp["items"]:
                if item.get("index", {}).get("error"):
                    logger.error("Bulk index error: %s", item["index"]["error"])
            raise RuntimeError("OpenSearch bulk indexing failed")


def _embed_chunks(chunks: list[ChunkRecord], embedding_fn) -> tuple[dict[int, list[float]], list[int]]:
    """
    Embed chunks in batches when the provider supports it.
    Falls back to single-chunk embedding for any failed batch.
    """
    vectors: dict[int, list[float]] = {}
    failed_pages: list[int] = []
    batch_fn = getattr(embedding_fn, "batch", None)

    if batch_fn is None:
        for chunk in chunks:
            _embed_one(chunk, embedding_fn, vectors, failed_pages)
        return vectors, failed_pages

    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[start:start + EMBEDDING_BATCH_SIZE]
        try:
            batch_vectors = batch_fn([chunk.text for chunk in batch])
            for chunk, vector in zip(batch, batch_vectors, strict=True):
                vectors[chunk.chunk_ordinal] = vector
        except Exception as e:
            logger.warning(
                "Batch embedding failed for chunks %d-%d: %s — falling back to single chunks",
                batch[0].chunk_ordinal,
                batch[-1].chunk_ordinal,
                e,
            )
            for chunk in batch:
                _embed_one(chunk, embedding_fn, vectors, failed_pages)

    return vectors, failed_pages


def _embed_one(
    chunk: ChunkRecord,
    embedding_fn,
    vectors: dict[int, list[float]],
    failed_pages: list[int],
) -> None:
    try:
        vectors[chunk.chunk_ordinal] = embedding_fn(chunk.text)
    except Exception as e:
        logger.error("Embedding failed for chunk ordinal %s: %s", chunk.chunk_ordinal, e)
        failed_pages.extend(range(chunk.page_start, chunk.page_end + 1))
