"""
Web documentation discovery helpers.

Supports two approved discovery modes:
- web_index: fetch an llms.txt/Markdown index and expand links into sources
- web_crawl: crawl same-site documentation links from an entry page
"""

from __future__ import annotations

import re
import logging
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen

_USER_AGENT = "IT-help-desk-doc-ingestion/0.1"
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
logger = logging.getLogger(__name__)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title and data.strip():
            self.title_parts.append(data.strip())

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()


def expand_web_sources(sources: list[dict]) -> list[dict]:
    """Expand web_index/web_crawl manifest entries into concrete page sources."""
    expanded: list[dict] = []
    for source in sources:
        source_type = source.get("source_type")
        if source_type == "web_index":
            expanded.extend(_expand_web_index(source))
        elif source_type == "web_crawl":
            expanded.extend(_expand_web_crawl(source))
        else:
            expanded.append(source)
    return expanded


def fetch_url(url: str, timeout: int = 30) -> bytes:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _expand_web_index(source: dict) -> list[dict]:
    text = fetch_url(source["source_uri"], timeout=_request_timeout(source)).decode("utf-8", errors="replace")
    limit = int(source.get("max_pages", 200))
    allowed_prefixes = source.get("allowed_prefixes") or [_origin(source["source_uri"])]

    results: list[dict] = []
    seen: set[str] = set()
    for title, url in _MARKDOWN_LINK_RE.findall(text):
        url = _normalise_url(url)
        if url in seen or not _allowed(url, allowed_prefixes):
            continue
        seen.add(url)
        results.append(_page_source(source, url, title))
        if len(results) >= limit:
            break
    return results


def _expand_web_crawl(source: dict) -> list[dict]:
    start_url = source["source_uri"]
    limit = int(source.get("max_pages", 80))
    timeout = _request_timeout(source)
    allowed_prefixes = source.get("allowed_prefixes") or [start_url.rstrip("/")]

    queue: deque[str] = deque([start_url])
    seen: set[str] = set()
    results: list[dict] = []

    while queue and len(results) < limit:
        url = _normalise_url(queue.popleft())
        if url in seen or not _allowed(url, allowed_prefixes):
            continue
        seen.add(url)

        try:
            content = fetch_url(url, timeout=timeout)
        except Exception as exc:
            logger.warning("Skipping web page that could not be fetched: %s (%s)", url, exc)
            continue

        parser = _LinkParser()
        parser.feed(content.decode("utf-8", errors="replace"))
        title = parser.title or _title_from_url(url)
        results.append(_page_source(source, url, title))

        for href in parser.links:
            child = _normalise_url(urljoin(url, href))
            if child not in seen and _allowed(child, allowed_prefixes):
                queue.append(child)

    return results


def _page_source(parent: dict, url: str, title: str) -> dict:
    child = dict(parent)
    child["source_uri"] = url
    child["source_type"] = "markdown" if url.endswith(".md") else "html"
    child["title"] = title.strip() or parent.get("title") or _title_from_url(url)
    child.pop("max_pages", None)
    child.pop("allowed_prefixes", None)
    return child


def _normalise_url(url: str) -> str:
    url, _fragment = urldefrag(url)
    return url.rstrip("/")


def _allowed(url: str, prefixes: list[str]) -> bool:
    return any(url.startswith(prefix.rstrip("/")) for prefix in prefixes)


def _request_timeout(source: dict) -> int:
    return int(source.get("request_timeout_seconds", 10))


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _title_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return urlparse(url).netloc
    return path.split("/")[-1].replace("-", " ").replace("_", " ").removesuffix(".md").title()
