"""Global IBM Docs link-graph discovery without downloading topic page bodies."""

from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import logging
import re
import time
from urllib.parse import urlsplit

from .catalog import (
    CatalogTarget,
    MetadataCatalog,
    ProductNode,
    global_product_id,
)
from .config import CrawlerSettings
from .fetcher import FetchSettings, PoliteFetcher, RequestRateLimiter
from .models import SitemapEntry
from .robots import load_robots_policy
from .sitemap import SitemapError, parse_sitemap
from .urls import canonicalize_url

logger = logging.getLogger(__name__)

GLOBAL_SITEMAP_URL = "https://www.ibm.com/docs/en/sitemap.xml"
GLOBAL_SITEMAP_MAX_BYTES = 100_000_000


@dataclass(frozen=True)
class ProductDescriptor:
    name: str
    key: str
    product_url_key: str
    aliases: tuple[str, ...]

    @property
    def node(self) -> ProductNode:
        return ProductNode(
            product_key=self.key,
            product_name=self.name,
            product_url_key=self.product_url_key,
            aliases=self.aliases,
        )


@dataclass(frozen=True)
class SitemapDescriptor:
    url: str
    last_modified: str | None
    content_key: str


@dataclass(frozen=True)
class DiscoveredDocumentationSet:
    target: CatalogTarget
    entries: tuple[SitemapEntry, ...]


def discover_global_catalog(
    settings: CrawlerSettings,
    *,
    max_sitemaps: int | None = None,
    max_urls_per_sitemap: int = 500_000,
    concurrency: int = 6,
    force_refresh: bool = False,
    content_keys: tuple[str, ...] = (),
) -> dict:
    """Populate every robots-allowed public product/version/topic sitemap link."""
    if max_sitemaps is not None and max_sitemaps < 1:
        raise ValueError("max_sitemaps must be at least 1")
    if max_urls_per_sitemap < 1:
        raise ValueError("max_urls_per_sitemap must be at least 1")
    concurrency = min(8, max(1, concurrency))

    policy = load_robots_policy(
        settings.user_agent,
        timeout_seconds=settings.timeout_seconds,
    )
    limiter = RequestRateLimiter()
    fetch_settings = FetchSettings(
        user_agent=settings.user_agent,
        delay_seconds=settings.delay_seconds,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        # Topic pages retain the normal response ceiling. This fetcher reads
        # only XML sitemaps; some valid portfolio sitemaps exceed 20 MB.
        max_response_bytes=max(
            settings.max_response_bytes, GLOBAL_SITEMAP_MAX_BYTES
        ),
        validate_public_dns=settings.validate_public_dns,
    )
    catalog = MetadataCatalog(settings.data_dir)
    started = time.monotonic()

    with PoliteFetcher(
        policy,
        fetch_settings,
        rate_limiter=limiter,
    ) as sitemap_fetcher:
        # IBM's robots.txt excludes /docs/api. Product/version identity is
        # therefore derived from canonical sitemap URLs, and no API bypass or
        # documentation page-body request is attempted here.
        products: list[ProductDescriptor] = []
        sitemaps = _load_global_sitemaps(sitemap_fetcher)
        if content_keys:
            wanted = {value.casefold() for value in content_keys}
            sitemaps = [
                descriptor for descriptor in sitemaps
                if descriptor.content_key.casefold() in wanted
            ]
        if max_sitemaps is not None:
            sitemaps = sitemaps[:max_sitemaps]

        pending_sitemaps: list[SitemapDescriptor] = []
        skipped_unchanged = 0
        for descriptor in sitemaps:
            if not force_refresh and catalog.sitemap_is_cataloged(
                descriptor.content_key,
                descriptor.url,
                descriptor.last_modified,
            ):
                skipped_unchanged += 1
            else:
                pending_sitemaps.append(descriptor)

        totals = {
            "sitemaps_discovered": len(sitemaps),
            "content_key_filter": list(content_keys),
            "sitemaps_skipped_unchanged": skipped_unchanged,
            "sitemaps_processed": 0,
            "sitemaps_failed": 0,
            "targets_upserted": 0,
            "topic_urls_upserted": 0,
        }
        failures: list[dict[str, str]] = []
        product_index = tuple(sorted(
            products,
            key=lambda item: len(item.product_url_key),
            reverse=True,
        ))

        def discover_one(descriptor: SitemapDescriptor) -> DiscoveredDocumentationSet:
            entries = _load_sitemap_entries(
                descriptor.url,
                sitemap_fetcher,
                max_urls=max_urls_per_sitemap,
            )
            if not entries:
                raise SitemapError(f"sitemap contained no English topic URLs: {descriptor.url}")
            target = _target_from_sitemap(descriptor, entries, product_index)
            return DiscoveredDocumentationSet(
                target=target,
                entries=tuple(entries),
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            iterator = iter(pending_sitemaps)
            pending: dict[Future, SitemapDescriptor] = {}
            for _ in range(concurrency):
                descriptor = next(iterator, None)
                if descriptor is not None:
                    pending[executor.submit(discover_one, descriptor)] = descriptor
            while pending:
                future = next(as_completed(pending))
                descriptor = pending.pop(future)
                try:
                    discovered = future.result()
                    catalog.upsert_target(discovered.target)
                    catalog.connect_root_product(discovered.target.product_key)
                    catalog.upsert_global_discovered(
                        discovered.target, discovered.entries
                    )
                    totals["targets_upserted"] += 1
                    totals["topic_urls_upserted"] += len(discovered.entries)
                    totals["sitemaps_processed"] += 1
                    processed = totals["sitemaps_processed"] + totals["sitemaps_failed"]
                    if processed % 25 == 0 or processed == len(pending_sitemaps):
                        logger.info(
                            "Global catalog progress: %s/%s pending sitemaps "
                            "(%s unchanged), %s topic URLs",
                            processed,
                            len(pending_sitemaps),
                            skipped_unchanged,
                            totals["topic_urls_upserted"],
                        )
                except Exception as exc:
                    totals["sitemaps_failed"] += 1
                    failures.append({
                        "sitemap_url": descriptor.url,
                        "stage": "sitemap",
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    logger.warning("Global sitemap failed for %s: %s", descriptor.url, exc)
                next_descriptor = next(iterator, None)
                if next_descriptor is not None:
                    pending[
                        executor.submit(discover_one, next_descriptor)
                    ] = next_descriptor

    catalog.normalize_global_product_identities()
    catalog.connect_discovered_product_hierarchy()
    catalog.mark_latest_targets()
    catalog.finalize_global_structure()
    return {
        "status": "CATALOGED" if not failures else "PARTIAL",
        **totals,
        "downloaded_page_bodies": 0,
        "embeddings_generated": 0,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "catalog": catalog.stats(),
        "failure_count": len(failures),
        "failures": failures[:100],
    }


def _load_global_sitemaps(fetcher: PoliteFetcher) -> list[SitemapDescriptor]:
    result = fetcher.fetch(
        GLOBAL_SITEMAP_URL,
        accept="application/xml,text/xml,application/gzip,*/*;q=0.1",
        scope_prefix="/docs/en",
    )
    if result.error or result.status_code != 200:
        raise SitemapError(
            f"global sitemap failed ({result.status_code}): {result.error or result.final_url}"
        )
    root_kind, entries = parse_sitemap(result.content)
    if root_kind != "sitemapindex":
        raise SitemapError("IBM Docs global sitemap is not a sitemap index")
    output: list[SitemapDescriptor] = []
    seen: set[tuple[str, str]] = set()
    for url, last_modified in entries:
        content_key = _content_key_from_sitemap(url)
        identity = (content_key, url)
        if content_key and identity not in seen:
            seen.add(identity)
            output.append(SitemapDescriptor(url, last_modified, content_key))
    return output


def _load_sitemap_entries(
    initial_url: str,
    fetcher: PoliteFetcher,
    *,
    max_urls: int,
) -> list[SitemapEntry]:
    queue = deque([initial_url])
    seen_sitemaps: set[str] = set()
    seen_pages: set[str] = set()
    output: list[SitemapEntry] = []
    while queue and len(output) < max_urls:
        current = queue.popleft()
        if current in seen_sitemaps:
            continue
        seen_sitemaps.add(current)
        result = fetcher.fetch(
            current,
            accept="application/xml,text/xml,application/gzip,*/*;q=0.1",
            scope_prefix="/docs/en",
        )
        if result.error or result.status_code != 200:
            raise SitemapError(
                f"sitemap failed ({result.status_code}): {result.error or current}"
            )
        root_kind, entries = parse_sitemap(result.content)
        if root_kind == "sitemapindex":
            queue.extend(url for url, _lastmod in entries if url not in seen_sitemaps)
            continue
        for raw_url, last_modified in entries:
            try:
                canonical = canonicalize_url(raw_url)
            except ValueError:
                continue
            if not urlsplit(canonical).path.startswith("/docs/en/"):
                continue
            if canonical in seen_pages:
                continue
            seen_pages.add(canonical)
            output.append(SitemapEntry(
                canonical_url=canonical,
                last_modified=last_modified,
                sitemap_url=current,
            ))
            if len(output) >= max_urls:
                break
    return output


def _target_from_sitemap(
    descriptor: SitemapDescriptor,
    entries: list[SitemapEntry],
    products: tuple[ProductDescriptor, ...],
) -> CatalogTarget:
    first = entries[0].canonical_url
    docs_path = urlsplit(first).path.rstrip("/")
    relative = docs_path.removeprefix("/docs/en/")
    product = next((
        item for item in products
        if relative == item.product_url_key
        or relative.startswith(item.product_url_key.rstrip("/") + "/")
    ), None)
    if product is None:
        product_url_key, inferred_version = _split_product_path(relative)
        product = ProductDescriptor(
            name=_humanize_product_path(product_url_key),
            key=_product_key_from_path(product_url_key),
            product_url_key=product_url_key,
            aliases=(),
        )
    else:
        inferred_version = ""
    remainder = relative[len(product.product_url_key):].strip("/")
    product_version = remainder or inferred_version or "current"
    family = product.product_url_key.split("/", 1)[0].replace("-", " ")
    aliases = tuple(dict.fromkeys((
        *product.aliases,
        product.name.removeprefix("IBM ").strip(),
        product.product_url_key.replace("/", " ").replace("-", " "),
    )))
    return CatalogTarget(
        content_key=descriptor.content_key,
        product_id=global_product_id(product.key),
        product_key=product.key,
        product_name=product.name,
        product_family=family,
        product_url_key=product.product_url_key,
        version_id=descriptor.content_key,
        product_version=product_version,
        docs_path_prefix=docs_path,
        seed_url=first,
        sitemap_url=descriptor.url,
        aliases=tuple(dict.fromkeys((*aliases, *_known_path_aliases(
            product.product_url_key
        )))),
        last_modified=descriptor.last_modified,
        is_latest=False,
    )


def _content_key_from_sitemap(url: str) -> str:
    match = re.fullmatch(
        r"/docs/en/(?P<key>[^/]+)/0/sitemap\.xml(?:\.gz)?",
        urlsplit(url).path,
    )
    return match.group("key") if match else ""


def _product_key_from_path(product_url_key: str) -> str:
    normalized = re.sub(
        r"[^A-Z0-9]+", "_", product_url_key.upper()
    ).strip("_")
    return f"PATH_{normalized or 'UNKNOWN'}"


def _split_product_path(relative: str) -> tuple[str, str]:
    parts = [part for part in relative.strip("/").split("/") if part]
    if len(parts) > 1 and re.fullmatch(
        r"(?:v?\d[0-9a-z.-]*|base|current|latest|saas|beta)",
        parts[-1],
        flags=re.IGNORECASE,
    ):
        return "/".join(parts[:-1]), parts[-1]
    return "/".join(parts), ""


def _humanize_product_path(product_url_key: str) -> str:
    words = product_url_key.replace("/", " ").replace("-", " ").split()
    output: list[str] = []
    for word in words:
        lowered = word.casefold()
        if lowered == "4z":
            output.extend(("for", "Z"))
        elif lowered == "watsonx":
            output.append("watsonx")
        elif lowered in {"wdi", "cpd", "zos", "db2", "mq"}:
            output.append(word.upper())
        else:
            output.append(word.capitalize())
    return "IBM " + " ".join(output)


def _known_path_aliases(product_url_key: str) -> tuple[str, ...]:
    """Expand only unambiguous public IBM Docs path abbreviations."""
    lowered = product_url_key.casefold().strip("/")
    aliases: list[str] = []
    if lowered.endswith("/wdi") or lowered == "wdi":
        aliases.extend((
            "IBM watsonx.data intelligence",
            "IBM watsonx.data integration",
            "watsonx data intelligence",
            "watsonx data integration",
            "watsonx.data intelligence",
            "watsonx.data integration",
            "WDI",
        ))
    if "watsonx-code-assistant-4z" in lowered:
        aliases.extend((
            "IBM watsonx Code Assistant for Z",
            "watsonx Code Assistant for Z",
            "WCA for Z",
            "WCA4Z",
        ))
    if lowered.endswith("/cpd") or lowered == "cpd":
        aliases.extend(("IBM Cloud Pak for Data", "Cloud Pak for Data", "CPD"))
    return tuple(aliases)
