"""Sitemap-only metadata discovery; no product page bodies or embeddings."""

from __future__ import annotations

from .catalog import MetadataCatalog
from .config import CrawlerSettings
from .fetcher import FetchSettings, PoliteFetcher
from .registry import CrawlTarget
from .robots import load_robots_policy
from .sitemap import discover_product_metadata


def discover_to_catalog(
    target: CrawlTarget,
    settings: CrawlerSettings,
    *,
    max_urls: int | None = None,
) -> dict:
    # Metadata discovery is intentionally independent from the page-body crawl
    # ceiling. A product may have thousands of URLs in the catalog while live
    # retrieval still fetches at most five page bodies for one question.
    limit = min(max_urls or 100_000, 100_000)
    if limit < 1:
        raise ValueError("max_urls must be at least 1")
    policy = load_robots_policy(
        settings.user_agent,
        timeout_seconds=settings.timeout_seconds,
    )
    fetch_settings = FetchSettings(
        user_agent=settings.user_agent,
        delay_seconds=settings.delay_seconds,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        max_response_bytes=settings.max_response_bytes,
        validate_public_dns=settings.validate_public_dns,
    )
    with PoliteFetcher(policy, fetch_settings) as fetcher:
        entries = discover_product_metadata(
            target.sitemap_url,
            target.docs_path_prefix,
            fetcher,
            max_urls=limit,
        )
    catalog = MetadataCatalog(settings.data_dir)
    catalog.ensure_seed(target)
    inserted = catalog.upsert_discovered(target, entries)
    return {
        "status": "CATALOGED",
        "product_id": target.product_id,
        "version_id": target.version_id,
        "discovered": len(entries),
        "upserted": inserted,
        "downloaded_page_bodies": 0,
        "embeddings_generated": 0,
        "catalog": catalog.stats(product_id=target.product_id),
    }
