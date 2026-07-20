"""Metadata-only discovery from an allowlisted llms.txt or XML sitemap."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import re
from urllib.parse import urlsplit

import httpx

from app.ingestion.ibm_docs_crawler.catalog import MetadataCatalog
from app.ingestion.ibm_docs_crawler.fetcher import _require_public_dns
from app.ingestion.ibm_docs_crawler.models import SitemapEntry
from app.ingestion.ibm_docs_crawler.sitemap import parse_sitemap

from .fetcher import load_official_robots_policy
from .registry import OfficialSourceTarget
from .urls import canonicalize_source_url, is_source_page_url

_LLMS_ENTRY = re.compile(
    r"^\s*-\s+\[([^\]]+)\]\(([^)]+)\)(?:\s*:\s*(.*))?\s*$"
)


@dataclass(frozen=True)
class OfficialDiscoveryReport:
    source_id: str
    discovered: int
    page_bodies_downloaded: int = 0
    chunks_generated: int = 0
    embeddings_generated: int = 0


def parse_llms_index(text: str, target: OfficialSourceTarget) -> list[SitemapEntry]:
    """Parse only allowlisted Markdown links; malformed and cross-host links are ignored."""
    entries: list[SitemapEntry] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _LLMS_ENTRY.match(line)
        if not match:
            continue
        title, raw_url, description = match.groups()
        try:
            url = canonicalize_source_url(
                raw_url,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
                base_url=target.index_url,
            )
        except ValueError:
            continue
        if url in seen or not is_source_page_url(
            url,
            allowed_host=target.allowed_host,
            path_prefix=target.docs_path_prefix,
            content_format=target.content_format,
        ):
            continue
        seen.add(url)
        entries.append(SitemapEntry(
            canonical_url=url,
            last_modified=None,
            sitemap_url=target.index_url,
            title=" ".join(title.split()),
            description=" ".join((description or "").split()),
        ))
    if target.seed_url not in seen:
        entries.append(SitemapEntry(
            canonical_url=target.seed_url,
            last_modified=None,
            sitemap_url=target.index_url,
            title="Installation",
        ))
    return entries


def parse_source_sitemap(
    content: bytes,
    target: OfficialSourceTarget,
    *,
    sitemap_url: str | None = None,
) -> tuple[str, list[SitemapEntry], list[str]]:
    """Parse one sitemap while enforcing the registered host and page prefix."""
    current = sitemap_url or target.index_url
    root_kind, raw_entries = parse_sitemap(content)
    pages: list[SitemapEntry] = []
    child_sitemaps: list[str] = []
    if root_kind == "sitemapindex":
        for raw_url, _last_modified in raw_entries:
            try:
                child = canonicalize_source_url(
                    raw_url,
                    allowed_host=target.allowed_host,
                    path_prefix="/",
                    base_url=current,
                )
            except ValueError:
                continue
            if urlsplit(child).path.lower().endswith((".xml", ".xml.gz")):
                child_sitemaps.append(child)
        return root_kind, pages, child_sitemaps

    seen: set[str] = set()
    for raw_url, last_modified in raw_entries:
        try:
            page = canonicalize_source_url(
                raw_url,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
                base_url=current,
            )
        except ValueError:
            continue
        if page in seen or not is_source_page_url(
            page,
            allowed_host=target.allowed_host,
            path_prefix=target.docs_path_prefix,
            content_format=target.content_format,
        ):
            continue
        seen.add(page)
        pages.append(SitemapEntry(page, last_modified, current))
    return root_kind, pages, child_sitemaps


def discover_official_source(
    target: OfficialSourceTarget,
    catalog: MetadataCatalog,
    *,
    user_agent: str,
    timeout_seconds: float = 30.0,
    max_bytes: int = 2_000_000,
    validate_public_dns: bool = True,
    client: httpx.Client | None = None,
) -> OfficialDiscoveryReport:
    """Download only catalog metadata; never fetch a product page body."""
    if not user_agent.strip():
        raise ValueError("IBM_DOCS_USER_AGENT is required for source discovery")
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
    try:
        policy = load_official_robots_policy(
            target,
            user_agent,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        entries: list[SitemapEntry] = []
        queue = deque([target.index_url])
        seen_indexes: set[str] = set()
        while queue and len(seen_indexes) < 100 and len(entries) < target.max_pages:
            index_url = queue.popleft()
            if index_url in seen_indexes:
                continue
            seen_indexes.add(index_url)
            policy.require_allowed(index_url, path_prefix="/")
            if validate_public_dns:
                _require_public_dns(index_url)
            content = _fetch_catalog_bytes(
                client,
                index_url,
                user_agent=user_agent,
                max_bytes=max_bytes,
                accept=(
                    "text/plain,text/markdown;q=0.9,*/*;q=0.1"
                    if target.index_format == "llms"
                    else "application/xml,text/xml,application/gzip,*/*;q=0.1"
                ),
                target=target,
            )
            if target.index_format == "llms":
                entries = parse_llms_index(
                    content.decode("utf-8", errors="replace"), target
                )
                break
            _kind, pages, children = parse_source_sitemap(
                content, target, sitemap_url=index_url
            )
            entries.extend(pages)
            for child in children:
                if child not in seen_indexes:
                    queue.append(child)
        entries = list({entry.canonical_url: entry for entry in entries}.values())[
            : target.max_pages
        ]
        if target.seed_url not in {entry.canonical_url for entry in entries}:
            entries.append(SitemapEntry(
                target.seed_url, None, target.index_url, target.product_name, ""
            ))
        if not entries:
            raise ValueError("official source catalog contained no allowlisted pages")
        discovered = catalog.upsert_discovered(
            target, entries, source_id=target.source_id
        )
        return OfficialDiscoveryReport(target.source_id, discovered)
    finally:
        if owns_client:
            client.close()


def _fetch_catalog_bytes(
    client: httpx.Client,
    url: str,
    *,
    user_agent: str,
    max_bytes: int,
    accept: str,
    target: OfficialSourceTarget,
) -> bytes:
    with client.stream(
        "GET", url, headers={"User-Agent": user_agent, "Accept": accept}
    ) as response:
        if response.is_redirect:
            raise ValueError("official source catalog redirects are not accepted")
        response.raise_for_status()
        final = canonicalize_source_url(
            str(response.url), allowed_host=target.allowed_host, path_prefix="/"
        )
        if final != url:
            raise ValueError("official source catalog resolved outside its registered URL")
        content = bytearray()
        for part in response.iter_bytes():
            content.extend(part)
            if len(content) > max_bytes:
                raise ValueError("official source catalog exceeded the response-size limit")
    return bytes(content)
