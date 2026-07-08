"""
Ingestion CLI Entry Point — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/run.py

Usage:
    python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml
    python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml --dry-run
    python -m app.ingestion.run --manifest config/corpus/ocp_sno_poc.yaml --force
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from opensearchpy import OpenSearch

from app.ingestion.chunker import chunk_pages
from app.ingestion.cos_source import get_document, list_documents
from app.ingestion.indexer import index_document
from app.ingestion.metadata import validate_metadata
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.text_parser import parse_text_document
from app.ingestion.web_source import expand_web_sources

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


def _build_opensearch_client() -> OpenSearch:
    url = os.environ["OPENSEARCH_URL"]
    username = os.environ["OPENSEARCH_USERNAME"]
    password = os.environ["OPENSEARCH_PASSWORD"]
    return OpenSearch(
        hosts=[url],
        http_auth=(username, password),
        use_ssl=url.startswith("https"),
        verify_certs=False,
        ssl_show_warn=False,
    )


def _stub_embedding_fn(text: str) -> list[float]:
    """
    Stub embedding function for local dev without watsonx.ai credentials.
    Returns a zero vector of dimension 768.
    Replace this with Developer A's real embedding provider once available.
    """
    logger.warning("Using STUB embeddings — vectors are zeroes. Set WATSONX_EMBEDDING_MODEL_ID and provide real embedding_fn.")
    return [0.0] * 768


def _stub_embedding_batch(texts: list[str]) -> list[list[float]]:
    logger.warning("Using STUB batch embeddings — vectors are zeroes.")
    return [[0.0] * 768 for _ in texts]


_stub_embedding_fn.batch = _stub_embedding_batch  # type: ignore[attr-defined]


def _get_embedding_fn():
    """
    Return the real embedding function if credentials are available,
    otherwise fall back to the stub.
    """
    if not os.getenv("WATSONX_EMBEDDING_MODEL_ID"):
        return _stub_embedding_fn

    try:
        from app.providers.watsonx_embeddings import embed_text, embed_texts

        embed_text.batch = embed_texts  # type: ignore[attr-defined]
        return embed_text
    except Exception as e:
        logger.warning("Could not initialise watsonx.ai embeddings (%s) — using stub", e)
        return _stub_embedding_fn


def run(manifest_path: Path, dry_run: bool = False, force: bool = False) -> None:
    """
    Main ingestion loop.

    Reads the corpus manifest, validates each source, parses PDFs,
    chunks text, and indexes into OpenSearch.
    """
    logger.info("=" * 60)
    logger.info("OpenShift & SNO Support Copilot — Ingestion Pipeline")
    logger.info("Manifest: %s  |  Dry-run: %s  |  Force: %s", manifest_path, dry_run, force)
    logger.info("=" * 60)

    # Load manifest
    with open(manifest_path, "r") as f:
        manifest = yaml.safe_load(f)

    sources = expand_web_sources(manifest.get("sources", []))
    if not sources:
        logger.error("No sources found in manifest: %s", manifest_path)
        sys.exit(1)

    logger.info("Found %d sources in manifest", len(sources))

    # Pre-flight: check which sources are accessible
    sources_with_status = list_documents(sources)
    accessible = [s for s in sources_with_status if s["accessible"]]
    skipped = [s for s in sources_with_status if not s["accessible"]]

    if skipped:
        logger.warning("%d source(s) not accessible and will be skipped:", len(skipped))
        for s in skipped:
            logger.warning("  SKIP: %s", s["source_uri"])

    if not accessible:
        logger.error("No accessible sources found. Exiting.")
        sys.exit(1)

    if dry_run:
        logger.info("DRY RUN — would ingest %d source(s):", len(accessible))
        for s in accessible:
            logger.info("  → %s", s["source_uri"])
        return

    # Build OpenSearch client and embedding function
    try:
        os_client = _build_opensearch_client()
        logger.info("Connected to OpenSearch: %s", os.environ["OPENSEARCH_URL"])
    except KeyError as e:
        logger.error("Missing env var for OpenSearch: %s. Check your .env file.", e)
        sys.exit(1)

    embedding_fn = _get_embedding_fn()

    # Process each source
    total = len(accessible)
    results = {"INDEXED": 0, "SKIPPED": 0, "FAILED": 0}

    for i, source in enumerate(accessible, start=1):
        uri = source["source_uri"]
        logger.info("[%d/%d] Processing: %s", i, total, uri)

        # Validate metadata
        validation = validate_metadata(source)
        if not validation.valid:
            logger.error("Metadata validation FAILED for %s:", uri)
            for err in validation.errors:
                logger.error("  - %s", err)
            results["FAILED"] += 1
            continue

        # Fetch PDF bytes
        try:
            content = get_document(uri, timeout=_source_timeout(source))
        except FileNotFoundError as e:
            logger.error("Document not found: %s", e)
            results["FAILED"] += 1
            continue
        except Exception as e:
            logger.error("Document fetch failed for %s: %s", uri, e)
            results["FAILED"] += 1
            continue

        # Parse source document
        try:
            parse_result = _parse_document(content, source)
        except ValueError as e:
            logger.error("Parse error for %s: %s", uri, e)
            results["FAILED"] += 1
            continue

        non_empty_pages = sum(1 for p in parse_result.pages if p.char_count > 0)
        if non_empty_pages == 0:
            logger.error("No extractable text in %s — is it an image-only PDF?", uri)
            results["FAILED"] += 1
            continue

        # Chunk
        chunks = chunk_pages(parse_result.pages)
        if not chunks:
            logger.warning("No chunks produced for %s — skipping", uri)
            results["SKIPPED"] += 1
            continue

        # Index
        try:
            summary = index_document(
                parse_result=parse_result,
                chunks=chunks,
                metadata=source,
                opensearch_client=os_client,
                embedding_fn=embedding_fn,
                force_reindex=force,
            )
            results[summary.status] += 1
            logger.info(
                "[%d/%d] %s → %s  (chunks: %d indexed, %d skipped)",
                i, total, uri, summary.status,
                summary.chunks_indexed, summary.chunks_skipped,
            )
        except Exception as e:
            logger.error("Indexing failed for %s: %s", uri, e)
            results["FAILED"] += 1

    # Summary
    logger.info("=" * 60)
    logger.info(
        "Ingestion complete — INDEXED: %d  SKIPPED: %d  FAILED: %d",
        results["INDEXED"], results["SKIPPED"], results["FAILED"],
    )
    logger.info("=" * 60)

    if results["FAILED"] > 0:
        sys.exit(1)


def _parse_document(content: bytes, source: dict):
    uri = source["source_uri"]
    source_type = source.get("source_type", "")
    if source_type == "pdf" or uri.lower().endswith(".pdf") or content.startswith(b"%PDF"):
        return parse_pdf(content, uri)
    return parse_text_document(content, uri)


def _source_timeout(source: dict) -> int:
    return int(source.get("request_timeout_seconds", 30))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest PDFs into OpenSearch knowledge base"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("config/corpus/ocp_sno_poc.yaml"),
        help="Path to corpus manifest YAML (default: config/corpus/ocp_sno_poc.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List sources that would be ingested without doing any work",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-index documents even when the same content hash is already present",
    )
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"ERROR: Manifest not found: {args.manifest}")
        sys.exit(1)

    run(manifest_path=args.manifest, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
