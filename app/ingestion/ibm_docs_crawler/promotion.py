"""Explicit indexing of audited crawl artifacts into staging indices."""

from __future__ import annotations

from dataclasses import fields

from app.ingestion.chunker import ChunkRecord
from app.ingestion.indexer import index_document
from app.ingestion.metadata import validate_metadata

from .extractor import to_parse_result
from .models import ContentBlock, ExtractedDocument
from .registry import CrawlTarget
from .storage import CrawlStorage


def index_run_to_staging(
    storage: CrawlStorage,
    run_id: str,
    target: CrawlTarget,
    *,
    chunks_index: str,
    docs_index: str,
    opensearch_client,
    embedding_fn,
) -> dict:
    """Index a clean staged run. Production-looking index names are rejected."""
    if "staging" not in chunks_index.lower() or "staging" not in docs_index.lower():
        raise ValueError("both index names must contain 'staging'")
    summary = storage.run_summary(run_id)
    if summary["product_id"] != target.product_id or summary["version_id"] != target.version_id:
        raise ValueError("run target does not match the enabled registry target")
    if summary["status"] != "STAGED" or summary["page_statuses"].get("FAILED", 0):
        raise ValueError("only a fully successful STAGED run can be indexed")
    for index_name in (chunks_index, docs_index):
        if not opensearch_client.indices.exists(index=index_name):
            raise ValueError(
                f"staging index does not exist: {index_name}; create it before indexing"
            )

    prepared: list[tuple[ExtractedDocument, list[ChunkRecord], dict]] = []
    for raw_document, raw_chunks in storage.iter_staged_artifacts(run_id):
        document = _document_from_dict(raw_document)
        chunks = [ChunkRecord(**record) for record in raw_chunks]
        metadata = {
            "source_uri": document.canonical_url,
            "source_type": "ibm_docs",
            "domain_id": target.domain_id,
            "product": target.product_name,
            "product_version": target.product_version,
            "locale": document.locale,
            "document_type": target.document_type,
            "classification": target.classification,
            "access_scope": list(target.access_scope),
            "title": document.title,
            "components": [],
            "topic_tags": [target.product_id, target.version_id],
        }
        validation = validate_metadata(metadata)
        if not validation.valid:
            raise ValueError(
                f"Metadata invalid for {document.canonical_url}: "
                + "; ".join(validation.errors)
            )
        prepared.append((document, chunks, metadata))

    if not prepared:
        raise ValueError("staged run contains no indexable document artifacts")

    # Metadata for every artifact is validated before the first OpenSearch write.
    counts = {"INDEXED": 0, "PARTIAL": 0, "SKIPPED": 0, "FAILED": 0}
    for document, chunks, metadata in prepared:
        result = index_document(
            parse_result=to_parse_result(document),
            chunks=chunks,
            metadata=metadata,
            opensearch_client=opensearch_client,
            embedding_fn=embedding_fn,
            chunks_index=chunks_index,
            docs_index=docs_index,
        )
        counts[result.status if result.status in counts else "FAILED"] += 1

    status = "INDEXED_STAGING" if counts["FAILED"] == 0 and counts["PARTIAL"] == 0 else "PARTIAL"
    report = {
        "run_id": run_id,
        "status": status,
        "chunks_index": chunks_index,
        "docs_index": docs_index,
        "documents": counts,
        "next_action": "Run retrieval and citation audits before an explicit alias promotion.",
    }
    storage.update_run_status(run_id, status, report)
    return report


def _document_from_dict(record: dict) -> ExtractedDocument:
    allowed = {item.name for item in fields(ExtractedDocument)}
    values = {key: value for key, value in record.items() if key in allowed}
    values["blocks"] = [ContentBlock(**block) for block in values.get("blocks", [])]
    return ExtractedDocument(**values)
