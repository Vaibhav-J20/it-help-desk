#!/usr/bin/env python3
"""Plan, run, and audit governed IBM Documentation crawls."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.ibm_docs_crawler.config import CrawlerSettings
from app.ingestion.ibm_docs_crawler.catalog import MetadataCatalog
from app.ingestion.ibm_docs_crawler.catalog_discovery import discover_to_catalog
from app.ingestion.ibm_docs_crawler.global_discovery import discover_global_catalog
from app.ingestion.ibm_docs_crawler.crawler import crawl_to_staging
from app.ingestion.ibm_docs_crawler.registry import (
    DEFAULT_REGISTRY_PATH,
    RegistryError,
    get_enabled_target,
    get_target,
    load_registry,
)
from app.ingestion.ibm_docs_crawler.promotion import index_run_to_staging
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage
from app.ingestion.official_docs.discovery import discover_official_source
from app.ingestion.official_docs.registry import (
    DEFAULT_OFFICIAL_SOURCE_REGISTRY,
    OfficialSourceRegistryError,
    get_enabled_source,
    load_official_source_registry,
)
from app.retrieval.live_docs import LiveDocsSettings
from app.retrieval.live_index import index_live_artifacts
from app.retrieval.official_docs import OfficialDocsRetriever


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument(
        "--official-sources",
        type=Path,
        default=DEFAULT_OFFICIAL_SOURCE_REGISTRY,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Validate and display a registry target")
    _add_target_args(plan)

    crawl = subparsers.add_parser("crawl", help="Crawl a configured target into staging")
    _add_target_args(crawl)
    crawl.add_argument("--max-pages", type=int)
    crawl.add_argument("--no-sitemap", action="store_true")

    catalog = subparsers.add_parser(
        "catalog", help="Discover sitemap metadata without downloading page bodies"
    )
    _add_target_args(catalog)
    catalog.add_argument("--max-urls", type=int)

    catalog_all = subparsers.add_parser(
        "catalog-all", help="Catalog metadata for every enabled registry target"
    )
    catalog_all.add_argument(
        "--product", action="append", dest="products",
        help="Limit to a product ID; repeat for multiple products",
    )
    catalog_all.add_argument("--max-urls-per-product", type=int)

    catalog_global = subparsers.add_parser(
        "catalog-global",
        help=(
            "Build the complete IBM Docs product/version/topic link graph from "
            "the public sitemap hierarchy without downloading page bodies"
        ),
    )
    catalog_global.add_argument("--max-sitemaps", type=int)
    catalog_global.add_argument("--max-urls-per-sitemap", type=int, default=500_000)
    catalog_global.add_argument("--concurrency", type=int, default=6)
    catalog_global.add_argument(
        "--content-key",
        action="append",
        dest="content_keys",
        help="Limit to an exact sitemap content key; repeat for multiple targets",
    )
    catalog_global.add_argument(
        "--force-refresh",
        action="store_true",
        help="Refetch sitemap targets even when their last-modified metadata is unchanged",
    )

    catalog_stats = subparsers.add_parser(
        "catalog-stats", help="Show local metadata catalog counts"
    )
    catalog_stats.add_argument("--product")
    catalog_stats.add_argument("--data-dir", type=Path)

    catalog_finalize = subparsers.add_parser(
        "catalog-finalize",
        help="Normalize product identities, graph structure, latest versions, and FTS",
    )
    catalog_finalize.add_argument("--data-dir", type=Path)

    source_plan = subparsers.add_parser(
        "source-plan", help="Validate an official developer-documentation source"
    )
    source_plan.add_argument("--source", required=True)

    source_catalog = subparsers.add_parser(
        "source-catalog", help="Catalog an official source from its registered metadata index"
    )
    source_catalog.add_argument("--source", required=True)

    source_retrieve = subparsers.add_parser(
        "source-retrieve",
        help="Run one bounded cold/warm retrieval against an official source",
    )
    source_retrieve.add_argument("--source", required=True)
    source_retrieve.add_argument("--query", required=True)
    source_retrieve.add_argument("--max-pages", type=int, default=3)
    source_retrieve.add_argument("--no-related", action="store_true")
    source_retrieve.add_argument(
        "--summary", action="store_true", help="Omit full chunk text from CLI output"
    )
    source_retrieve.add_argument(
        "--index-staging",
        action="store_true",
        help="Synchronously embed and write retrieved pages to explicit staging indices",
    )
    source_retrieve.add_argument("--chunks-index")
    source_retrieve.add_argument("--docs-index")

    audit = subparsers.add_parser("audit", help="Show the durable status of a crawl run")
    audit.add_argument("--run-id", required=True)
    audit.add_argument("--data-dir", type=Path)

    index_staging = subparsers.add_parser(
        "index-staging", help="Index an audited crawl run into explicit staging indices"
    )
    _add_target_args(index_staging)
    index_staging.add_argument("--run-id", required=True)
    index_staging.add_argument("--chunks-index", required=True)
    index_staging.add_argument("--docs-index", required=True)
    index_staging.add_argument("--data-dir", type=Path)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        if args.command == "audit":
            data_dir = args.data_dir or _default_data_dir()
            print(json.dumps(CrawlStorage(data_dir).run_summary(args.run_id), indent=2))
            return 0
        if args.command == "catalog-stats":
            data_dir = args.data_dir or _default_data_dir()
            print(json.dumps(
                MetadataCatalog(data_dir).stats(product_id=args.product), indent=2
            ))
            return 0
        if args.command == "catalog-finalize":
            data_dir = args.data_dir or _default_data_dir()
            metadata_catalog = MetadataCatalog(data_dir)
            metadata_catalog.normalize_global_product_identities()
            metadata_catalog.connect_discovered_product_hierarchy()
            metadata_catalog.mark_latest_targets()
            metadata_catalog.finalize_global_structure()
            print(json.dumps({
                "status": "FINALIZED",
                "catalog": metadata_catalog.stats(),
            }, indent=2))
            return 0
        if args.command == "catalog-global":
            report = discover_global_catalog(
                CrawlerSettings.from_env(),
                max_sitemaps=args.max_sitemaps,
                max_urls_per_sitemap=args.max_urls_per_sitemap,
                concurrency=args.concurrency,
                force_refresh=args.force_refresh,
                content_keys=tuple(args.content_keys or ()),
            )
            print(json.dumps(report, indent=2))
            return 0 if report["status"] == "CATALOGED" else 2
        if args.command in {"source-plan", "source-catalog", "source-retrieve"}:
            source_registry = load_official_source_registry(args.official_sources)
            source_target = get_enabled_source(source_registry, args.source)
            if args.command == "source-plan":
                print(json.dumps({
                    "source_id": source_target.source_id,
                    "product_id": source_target.product_id,
                    "version_id": source_target.version_id,
                    "origin": source_target.origin,
                    "index_url": source_target.index_url,
                    "seed_url": source_target.seed_url,
                    "content_format": source_target.content_format,
                    "action": "No network request was made.",
                }, indent=2))
                return 0
            settings = CrawlerSettings.from_env()
            catalog = MetadataCatalog(settings.data_dir)
            if args.command == "source-catalog":
                report = discover_official_source(
                    source_target,
                    catalog,
                    user_agent=settings.user_agent,
                    timeout_seconds=settings.timeout_seconds,
                    max_bytes=min(settings.max_response_bytes, 2_000_000),
                    validate_public_dns=settings.validate_public_dns,
                )
                print(json.dumps({
                    "status": "CATALOGED",
                    **asdict(report),
                    "catalog": catalog.stats(product_id=source_target.product_id),
                }, indent=2))
                return 0
            maximum = min(5, max(1, args.max_pages))
            retriever = OfficialDocsRetriever(
                source_target,
                catalog,
                CrawlStorage(settings.data_dir),
                LiveDocsSettings(
                    user_agent=settings.user_agent,
                    delay_seconds=settings.delay_seconds,
                    timeout_seconds=settings.timeout_seconds,
                    max_retries=settings.max_retries,
                    max_response_bytes=settings.max_response_bytes,
                    validate_public_dns=settings.validate_public_dns,
                    initial_pages=min(3, maximum),
                    max_pages=maximum,
                    related_depth=0 if args.no_related else 1,
                    concurrency=3,
                    max_chunks_per_document=settings.max_chunks_per_document,
                ),
            )
            result = retriever.retrieve(args.query)
            index_report = None
            if args.index_staging:
                if not args.chunks_index or not args.docs_index:
                    raise ValueError(
                        "--chunks-index and --docs-index are required with --index-staging"
                    )
                if "staging" not in args.chunks_index or "staging" not in args.docs_index:
                    raise ValueError("source-retrieve indexing is restricted to staging indices")
                from app.ingestion.run import _build_opensearch_client, _get_embedding_fn

                index_report = index_live_artifacts(
                    result.artifacts,
                    source_target,
                    opensearch_client=_build_opensearch_client(),
                    embedding_fn=_get_embedding_fn(),
                    chunks_index=args.chunks_index,
                    docs_index=args.docs_index,
                )
            candidates = result.candidates
            if args.summary:
                candidates = [
                    {
                        "title": candidate.get("title"),
                        "source_uri": candidate.get("source_uri"),
                        "section_path": candidate.get("section_path"),
                        "retrieval_origin": candidate.get("retrieval_origin"),
                    }
                    for candidate in result.candidates[:5]
                ]
            print(json.dumps({
                "status": "RETRIEVED" if result.candidates else "NO_EVIDENCE",
                "source_id": source_target.source_id,
                "trace": result.trace,
                "candidate_count": len(result.candidates),
                "candidates": candidates,
                "index_report": index_report,
            }, indent=2))
            return 0

        registry = load_registry(args.registry)
        if args.command == "plan":
            target = get_target(
                registry, args.product, args.version, require_enabled=False
            )
            print(json.dumps({
                "product_id": target.product_id,
                "version_id": target.version_id,
                "seed_url": target.seed_url,
                "docs_path_prefix": target.docs_path_prefix,
                "max_pages": target.max_pages,
                "document_type": target.document_type,
                "classification": target.classification,
                "access_scope": list(target.access_scope),
                "run_context": target.run_context,
                "action": "No network request was made.",
            }, indent=2))
            return 0

        if args.command == "index-staging":
            target = get_enabled_target(registry, args.product, args.version)
            from app.ingestion.run import _build_opensearch_client, _get_embedding_fn

            report = index_run_to_staging(
                CrawlStorage(args.data_dir or _default_data_dir()),
                args.run_id,
                target,
                chunks_index=args.chunks_index,
                docs_index=args.docs_index,
                opensearch_client=_build_opensearch_client(),
                embedding_fn=_get_embedding_fn(),
            )
            print(json.dumps(report, indent=2))
            return 0 if report["status"] == "INDEXED_STAGING" else 2

        if args.command == "catalog":
            target = get_enabled_target(registry, args.product, args.version)
            report = discover_to_catalog(
                target,
                CrawlerSettings.from_env(),
                max_urls=args.max_urls,
            )
            print(json.dumps(report, indent=2))
            return 0

        if args.command == "catalog-all":
            selected = set(args.products or [])
            settings = CrawlerSettings.from_env()
            reports = []
            failures = []
            for product in registry.products:
                if selected and product.product_id not in selected:
                    continue
                for version in product.versions:
                    if not version.crawl_enabled:
                        continue
                    target = get_enabled_target(
                        registry, product.product_id, version.version_id
                    )
                    try:
                        reports.append(discover_to_catalog(
                            target,
                            settings,
                            max_urls=args.max_urls_per_product,
                        ))
                    except Exception as exc:
                        logging.exception(
                            "Catalog discovery failed for %s/%s",
                            product.product_id,
                            version.version_id,
                        )
                        failures.append({
                            "product_id": product.product_id,
                            "version_id": version.version_id,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
            if selected:
                known = {product.product_id for product in registry.products}
                unknown = sorted(selected - known)
                if unknown:
                    raise RegistryError(
                        "Unknown IBM Docs product_id(s): " + ", ".join(unknown)
                    )
            payload = {
                "status": "CATALOGED" if not failures else "PARTIAL",
                "targets_succeeded": len(reports),
                "targets_failed": len(failures),
                "reports": reports,
                "failures": failures,
            }
            print(json.dumps(payload, indent=2))
            return 0 if not failures else 2

        target = get_enabled_target(registry, args.product, args.version)

        report = crawl_to_staging(
            target,
            CrawlerSettings.from_env(),
            max_pages=args.max_pages,
            use_sitemap=not args.no_sitemap,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.status == "STAGED" else 2
    except (RegistryError, OfficialSourceRegistryError, ValueError, KeyError) as exc:
        parser.error(str(exc))
        return 2


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--product", required=True)
    parser.add_argument("--version", required=True)


def _default_data_dir() -> Path:
    import os

    return Path(
        os.path.expandvars(os.getenv(
            "IBM_DOCS_DATA_DIR",
            str(Path.home() / ".local" / "share" / "it-helpdesk" / "ibm-docs-crawler"),
        ))
    ).expanduser()


if __name__ == "__main__":
    raise SystemExit(main())
