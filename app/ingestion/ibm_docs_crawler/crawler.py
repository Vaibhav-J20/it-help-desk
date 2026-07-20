"""Top-level governed crawl-to-staging orchestration."""

from __future__ import annotations

from collections import deque
import hashlib
import logging
from urllib.parse import parse_qsl, urlsplit

from app.ingestion.chunker import chunk_pages

from .config import CrawlerSettings
from .extractor import ExtractionError, extract_document, to_parse_result
from .fetcher import FetchSettings, PoliteFetcher
from .models import CrawlReport
from .registry import CrawlTarget
from .robots import load_robots_policy
from .sitemap import SitemapError, discover_product_urls
from .storage import CrawlStorage
from .urls import canonicalize_url, is_in_target_scope

logger = logging.getLogger(__name__)


def crawl_to_staging(
    target: CrawlTarget,
    settings: CrawlerSettings,
    *,
    max_pages: int | None = None,
    use_sitemap: bool = True,
) -> CrawlReport:
    """Crawl a configured target and write artifacts; never writes OpenSearch."""
    page_limit = min(max_pages or target.max_pages, target.max_pages)
    if page_limit < 1:
        raise ValueError("max_pages must be at least 1")

    storage = CrawlStorage(settings.data_dir)
    run_id = storage.start_run(target)
    fetched = staged = unchanged = skipped = failed = 0
    discovered_urls: list[str] = []
    attempt_limit = max(page_limit * 3, page_limit + 5)

    try:
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
            if use_sitemap:
                try:
                    discovered_urls = discover_product_urls(
                        target.sitemap_url,
                        target.docs_path_prefix,
                        fetcher,
                        max_urls=max(page_limit * 4, page_limit),
                    )
                except SitemapError as exc:
                    logger.warning("Sitemap discovery failed; continuing from seed URL: %s", exc)

            queue = deque([target.seed_url, *discovered_urls])
            queued = {canonicalize_url(url) for url in queue}
            visited: set[str] = set()
            while queue and staged + unchanged < page_limit and fetched < attempt_limit:
                url = canonicalize_url(queue.popleft())
                if url in visited or not is_in_target_scope(url, target.docs_path_prefix):
                    continue
                visited.add(url)
                storage.record_discovered(run_id, url)
                result = fetcher.fetch(
                    url,
                    conditional_headers=storage.cache_headers(url),
                    scope_prefix=target.docs_path_prefix,
                )
                fetched += 1

                if result.error:
                    failed += 1
                    storage.mark_failed(run_id, url, result.error, http_status=result.status_code)
                    continue
                if _topic_redirect_was_lost(url, result.final_url):
                    skipped += 1
                    storage.mark_skipped(
                        run_id,
                        url,
                        "redirect dropped or changed the requested topic",
                        http_status=result.status_code,
                    )
                    continue
                if result.not_modified:
                    unchanged += 1
                    storage.mark_unchanged(run_id, url)
                    continue
                if result.status_code in {404, 410}:
                    skipped += 1
                    storage.mark_skipped(
                        run_id,
                        url,
                        f"obsolete sitemap URL returned HTTP {result.status_code}",
                        http_status=result.status_code,
                    )
                    continue
                if result.status_code != 200:
                    failed += 1
                    storage.mark_failed(
                        run_id, url, f"unexpected HTTP status {result.status_code}",
                        http_status=result.status_code,
                    )
                    continue

                raw_document_id = "doc-" + hashlib.sha256(
                    result.final_url.encode("utf-8")
                ).hexdigest()[:16]
                raw_path = storage.save_raw(run_id, raw_document_id, result.content)
                content_type = result.headers.get("content-type", "").lower()
                if content_type and "html" not in content_type:
                    failed += 1
                    storage.mark_failed(
                        run_id, url, f"unsupported Content-Type: {content_type}",
                        http_status=result.status_code, raw_path=raw_path,
                    )
                    continue
                try:
                    document = extract_document(
                        result.content,
                        requested_url=url,
                        final_url=result.final_url,
                        http_status=result.status_code,
                        target=target,
                    )
                    chunks = chunk_pages(to_parse_result(document).pages)
                    if not chunks:
                        raise ValueError("no chunks were produced")
                    if len(chunks) > settings.max_chunks_per_document:
                        raise ValueError(
                            f"document produced {len(chunks)} chunks, exceeding the "
                            f"sanity limit of {settings.max_chunks_per_document}"
                        )
                    storage.stage_document(
                        run_id, document, chunks, result.headers, raw_path
                    )
                    staged += 1
                    for link in document.links:
                        if link not in queued and link not in visited:
                            queued.add(link)
                            queue.append(link)
                except ExtractionError as exc:
                    if _is_nonfatal_extraction_error(exc):
                        skipped += 1
                        storage.mark_skipped(
                            run_id,
                            url,
                            f"{type(exc).__name__}: {exc}",
                            http_status=result.status_code,
                            raw_path=raw_path,
                        )
                        continue
                    failed += 1
                    storage.mark_failed(
                        run_id,
                        url,
                        f"{type(exc).__name__}: {exc}",
                        http_status=result.status_code,
                        raw_path=raw_path,
                    )
                except Exception as exc:
                    failed += 1
                    storage.mark_failed(
                        run_id, url, f"{type(exc).__name__}: {exc}",
                        http_status=result.status_code, raw_path=raw_path,
                    )
    except KeyboardInterrupt:
        report = CrawlReport(
            run_id=run_id,
            product_id=target.product_id,
            version_id=target.version_id,
            discovered=len(set(discovered_urls) | {target.seed_url}),
            fetched=fetched,
            staged=staged,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed,
            status="ABORTED",
        )
        storage.finish_run(run_id, report.status, report.to_dict())
        raise
    except Exception as exc:
        report = CrawlReport(
            run_id=run_id,
            product_id=target.product_id,
            version_id=target.version_id,
            discovered=len(set(discovered_urls) | {target.seed_url}),
            fetched=fetched,
            staged=staged,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed + 1,
            status="FAILED",
        )
        payload = {**report.to_dict(), "fatal_error": f"{type(exc).__name__}: {exc}"}
        storage.finish_run(run_id, report.status, payload)
        raise

    if failed:
        status = "PARTIAL" if staged or unchanged else "FAILED"
    else:
        status = "STAGED" if staged or unchanged else "FAILED"
    report = CrawlReport(
        run_id=run_id,
        product_id=target.product_id,
        version_id=target.version_id,
        discovered=len(visited),
        fetched=fetched,
        staged=staged,
        unchanged=unchanged,
        skipped=skipped,
        failed=failed,
        status=status,
    )
    storage.finish_run(run_id, status, report.to_dict())
    return report


def _topic_redirect_was_lost(requested_url: str, final_url: str) -> bool:
    requested_topic = dict(parse_qsl(urlsplit(requested_url).query)).get("topic")
    final_topic = dict(parse_qsl(urlsplit(final_url).query)).get("topic")
    return bool(requested_topic and requested_topic != final_topic)


def _is_nonfatal_extraction_error(exc: ExtractionError) -> bool:
    return "suspiciously short" in str(exc).lower()
