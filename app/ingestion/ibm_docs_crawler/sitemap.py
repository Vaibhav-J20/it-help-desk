"""Bounded recursive sitemap discovery for an enabled product path."""

from __future__ import annotations

from collections import deque
import gzip
from io import BytesIO
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from .fetcher import PoliteFetcher
from .models import SitemapEntry
from .urls import canonicalize_url, is_in_target_scope, validate_ibm_docs_url


class SitemapError(RuntimeError):
    pass


def parse_sitemap(
    content: bytes,
    *,
    max_xml_bytes: int = 50_000_000,
) -> tuple[str, list[tuple[str, str | None]]]:
    """Return (root_kind, entries), detecting gzip by bytes rather than suffix."""
    if content.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=BytesIO(content)) as compressed:
            content = compressed.read(max_xml_bytes + 1)
    if len(content) > max_xml_bytes:
        raise SitemapError(f"decompressed sitemap exceeded {max_xml_bytes} bytes")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SitemapError(f"invalid sitemap XML: {exc}") from exc

    root_kind = _local_name(root.tag)
    if root_kind not in {"urlset", "sitemapindex"}:
        raise SitemapError(f"unsupported sitemap root element: {root_kind}")
    child_kind = "url" if root_kind == "urlset" else "sitemap"
    entries: list[tuple[str, str | None]] = []
    for item in root:
        if _local_name(item.tag) != child_kind:
            continue
        loc: str | None = None
        lastmod: str | None = None
        for child in item:
            name = _local_name(child.tag)
            value = (child.text or "").strip()
            if name == "loc":
                loc = value or None
            elif name == "lastmod":
                lastmod = value or None
        if loc:
            entries.append((loc, lastmod))
    return root_kind, entries


def discover_product_urls(
    sitemap_url: str,
    docs_path_prefix: str,
    fetcher: PoliteFetcher,
    *,
    max_urls: int,
    max_sitemaps: int = 200,
) -> list[str]:
    """Discover only URLs within the exact enabled product path boundary."""
    return [
        entry.canonical_url
        for entry in discover_product_metadata(
            sitemap_url,
            docs_path_prefix,
            fetcher,
            max_urls=max_urls,
            max_sitemaps=max_sitemaps,
        )
    ]


def discover_product_metadata(
    sitemap_url: str,
    docs_path_prefix: str,
    fetcher: PoliteFetcher,
    *,
    max_urls: int,
    max_sitemaps: int = 200,
) -> list[SitemapEntry]:
    """Discover metadata only; product HTML is never requested here."""
    queue = deque([validate_ibm_docs_url(sitemap_url)])
    seen_sitemaps: set[str] = set()
    seen_pages: set[str] = set()
    output: list[SitemapEntry] = []

    while queue and len(seen_sitemaps) < max_sitemaps and len(output) < max_urls:
        current = queue.popleft()
        if current in seen_sitemaps:
            continue
        seen_sitemaps.add(current)
        result = fetcher.fetch(
            current,
            accept="application/xml,text/xml,application/gzip,*/*;q=0.1",
            scope_prefix="/docs",
        )
        if result.error or result.status_code != 200:
            raise SitemapError(
                f"sitemap fetch failed ({result.status_code}): {result.error or current}"
            )
        root_kind, entries = parse_sitemap(result.content)
        if root_kind == "sitemapindex":
            for loc, _lastmod in entries:
                try:
                    child = validate_ibm_docs_url(loc)
                except ValueError:
                    continue
                path = urlsplit(child).path.lower()
                if path.endswith((".xml", ".xml.gz")) and child not in seen_sitemaps:
                    queue.append(child)
            continue

        for loc, last_modified in entries:
            try:
                canonical = canonicalize_url(loc)
            except ValueError:
                continue
            if canonical in seen_pages or not is_in_target_scope(canonical, docs_path_prefix):
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


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
