#!/usr/bin/env python3
"""Crawl and optionally index a bounded portfolio of public IBM Docs products."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.ibm_docs_crawler.config import CrawlerSettings
from app.ingestion.ibm_docs_crawler.crawler import crawl_to_staging
from app.ingestion.ibm_docs_crawler.promotion import index_run_to_staging
from app.ingestion.ibm_docs_crawler.registry import (
    DEFAULT_REGISTRY_PATH,
    get_enabled_target,
    load_registry,
)
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage


DEFAULT_PRODUCTS = (
    "ibm-mq",
    "api-connect",
    "db2",
    "websphere-application-server",
    "storage-scale",
    "cloud-pak-data",
    "storage-protect",
    "security-verify-access",
    "app-connect",
    "datapower-gateway",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--products", nargs="+", default=list(DEFAULT_PRODUCTS))
    parser.add_argument("--version", default="latest")
    parser.add_argument("--max-pages-per-product", type=int, default=10)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--chunks-index", default="knowledge_chunks_ibm_docs_staging_v2")
    parser.add_argument("--docs-index", default="knowledge_documents_ibm_docs_staging_v2")
    args = parser.parse_args()

    if not 1 <= args.max_pages_per_product <= 100_000:
        parser.error("--max-pages-per-product must be from 1 to 100000")
    if args.index and (
        "staging" not in args.chunks_index.lower()
        or "staging" not in args.docs_index.lower()
    ):
        parser.error("portfolio indexing requires explicit staging index names")

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    registry = load_registry(args.registry)
    settings = CrawlerSettings.from_env()
    if args.data_dir:
        settings = replace(settings, data_dir=args.data_dir.expanduser())
    storage = CrawlStorage(settings.data_dir)

    opensearch_client = embedding_fn = None
    if args.index:
        from app.ingestion.run import _build_opensearch_client, _get_embedding_fn

        opensearch_client = _build_opensearch_client()
        embedding_fn = _get_embedding_fn()

    portfolio: dict = {
        "started_at": _now(),
        "max_pages_per_product": args.max_pages_per_product,
        "chunks_index": args.chunks_index if args.index else None,
        "docs_index": args.docs_index if args.index else None,
        "products": [],
    }

    for product_id in args.products:
        entry: dict = {"product_id": product_id, "version_id": args.version}
        try:
            target = get_enabled_target(registry, product_id, args.version)
            crawl_report = crawl_to_staging(
                target,
                settings,
                max_pages=args.max_pages_per_product,
                use_sitemap=True,
            )
            entry["crawl"] = crawl_report.to_dict()
            if args.index and crawl_report.status == "STAGED":
                entry["index"] = index_run_to_staging(
                    storage,
                    crawl_report.run_id,
                    target,
                    chunks_index=args.chunks_index,
                    docs_index=args.docs_index,
                    opensearch_client=opensearch_client,
                    embedding_fn=embedding_fn,
                )
            elif args.index:
                entry["index"] = {
                    "status": "SKIPPED",
                    "reason": "crawl was not fully STAGED",
                }
        except Exception as exc:
            logging.exception("Portfolio product failed: %s", product_id)
            entry["error"] = f"{type(exc).__name__}: {exc}"
        portfolio["products"].append(entry)

    portfolio["finished_at"] = _now()
    portfolio["summary"] = _summarize(portfolio["products"], indexing=args.index)
    report_path = settings.data_dir / "runs" / (
        "portfolio-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    portfolio["report_path"] = str(report_path)
    report_path.write_text(json.dumps(portfolio, indent=2), encoding="utf-8")
    print(json.dumps(portfolio, indent=2))
    return 0 if portfolio["summary"]["failed_products"] == 0 else 2


def _summarize(products: list[dict], *, indexing: bool) -> dict[str, int]:
    staged = sum(item.get("crawl", {}).get("status") == "STAGED" for item in products)
    indexed = sum(
        item.get("index", {}).get("status") == "INDEXED_STAGING" for item in products
    )
    failed = sum(
        "error" in item
        or item.get("crawl", {}).get("status") != "STAGED"
        or (indexing and item.get("index", {}).get("status") != "INDEXED_STAGING")
        for item in products
    )
    return {
        "requested_products": len(products),
        "staged_products": staged,
        "indexed_products": indexed,
        "failed_products": failed,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
