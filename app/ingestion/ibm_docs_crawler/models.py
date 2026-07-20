"""Shared value objects for the IBM Documentation crawler."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    heading_path: list[str]
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    document_id: str
    canonical_url: str
    requested_url: str
    title: str
    product_id: str
    product_name: str
    product_version: str
    locale: str
    blocks: list[ContentBlock]
    links: list[str]
    content_hash: str
    fetched_at: str
    http_status: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    error: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


@dataclass(frozen=True)
class SitemapEntry:
    """One product page discovered from a sitemap without fetching its HTML."""

    canonical_url: str
    last_modified: str | None
    sitemap_url: str
    title: str = ""
    description: str = ""


@dataclass(frozen=True)
class CrawlReport:
    run_id: str
    product_id: str
    version_id: str
    discovered: int
    fetched: int
    staged: int
    unchanged: int
    skipped: int
    failed: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
