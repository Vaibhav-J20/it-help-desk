"""Best-effort background promotion of bounded live documents into OpenSearch."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import logging

from app.ingestion.ibm_docs_crawler.extractor import to_parse_result
from app.ingestion.ibm_docs_crawler.registry import CrawlTarget
from app.ingestion.indexer import index_document
from app.ingestion.metadata import validate_metadata
from app.retrieval.live_docs import LiveDocumentArtifact

logger = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-docs-index")


def schedule_live_indexing(
    artifacts: list[LiveDocumentArtifact],
    target: CrawlTarget,
    *,
    opensearch_client,
    embedding_fn,
    chunks_index: str,
    docs_index: str,
) -> Future | None:
    if not artifacts:
        return None
    return _EXECUTOR.submit(
        index_live_artifacts,
        artifacts,
        target,
        opensearch_client=opensearch_client,
        embedding_fn=embedding_fn,
        chunks_index=chunks_index,
        docs_index=docs_index,
    )


def index_live_artifacts(
    artifacts: list[LiveDocumentArtifact],
    target: CrawlTarget,
    *,
    opensearch_client,
    embedding_fn,
    chunks_index: str,
    docs_index: str,
) -> dict:
    if not chunks_index.strip() or not docs_index.strip():
        raise ValueError("explicit live-document OpenSearch index names are required")
    counts = {"INDEXED": 0, "PARTIAL": 0, "SKIPPED": 0, "FAILED": 0}
    for artifact in artifacts:
        source_id = str(artifact.document.metadata.get("source_id") or "ibm-docs")
        metadata = {
            "source_uri": artifact.document.canonical_url,
            "source_type": (
                "ibm_docs_live"
                if source_id == "ibm-docs"
                else "official_product_docs_live"
            ),
            "domain_id": target.domain_id,
            "product": target.product_name,
            "product_version": target.product_version,
            "locale": artifact.document.locale,
            "document_type": target.document_type,
            "classification": target.classification,
            "access_scope": list(target.access_scope),
            "title": artifact.document.title,
            "components": [],
            "topic_tags": [target.product_id, target.version_id, "live-cache"],
        }
        validation = validate_metadata(metadata)
        if not validation.valid:
            logger.error(
                "Live document metadata rejected for %s: %s",
                artifact.document.canonical_url,
                "; ".join(validation.errors),
            )
            counts["FAILED"] += 1
            continue
        try:
            summary = index_document(
                parse_result=to_parse_result(artifact.document),
                chunks=artifact.chunks,
                metadata=metadata,
                opensearch_client=opensearch_client,
                embedding_fn=embedding_fn,
                chunks_index=chunks_index,
                docs_index=docs_index,
            )
            counts[summary.status if summary.status in counts else "FAILED"] += 1
        except Exception:
            logger.exception(
                "Background live indexing failed for %s",
                artifact.document.canonical_url,
            )
            counts["FAILED"] += 1
    return counts
