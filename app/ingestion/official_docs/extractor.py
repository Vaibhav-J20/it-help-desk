"""Structure-preserving extraction for official Markdown and HTML docs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.ingestion.ibm_docs_crawler.models import ContentBlock, ExtractedDocument
from app.ingestion.ibm_docs_crawler.extractor import (
    ExtractionError,
    _choose_main,
    _extract_blocks as _extract_html_blocks,
    _extract_title as _extract_html_title,
    _mark_inline_code,
    _meta_content,
    _normalize_html_semantics,
)

from .registry import OfficialSourceTarget
from .urls import canonicalize_source_url, is_source_page_url

MARKDOWN_PARSER_VERSION = "official-docs-markdown-v1"
HTML_PARSER_VERSION = "official-docs-html-v1"
PARSER_VERSION = MARKDOWN_PARSER_VERSION
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")


def extract_markdown_document(
    content: bytes,
    *,
    requested_url: str,
    final_url: str,
    http_status: int,
    target: OfficialSourceTarget,
    fallback_title: str = "",
) -> ExtractedDocument:
    canonical = canonicalize_source_url(
        final_url,
        allowed_host=target.allowed_host,
        path_prefix=target.docs_path_prefix,
    )
    if not is_source_page_url(
        canonical,
        allowed_host=target.allowed_host,
        path_prefix=target.docs_path_prefix,
        content_format="markdown",
    ):
        raise ValueError("final URL is not an allowlisted Markdown page")
    text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    blocks, title = _parse_blocks(text, fallback_title=fallback_title)
    if sum(len(block.text) for block in blocks) < 120:
        raise ValueError("extracted Markdown content is suspiciously short")
    related, outgoing_ibm, external = _extract_links(text, canonical, target)
    normalized = {
        "title": title,
        "blocks": [
            {"kind": block.kind, "heading_path": block.heading_path, "text": block.text}
            for block in blocks
        ],
    }
    content_hash = "sha256:" + hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    document_id = "doc-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return ExtractedDocument(
        document_id=document_id,
        canonical_url=canonical,
        requested_url=canonicalize_source_url(
            requested_url,
            allowed_host=target.allowed_host,
            path_prefix=target.docs_path_prefix,
        ),
        title=title,
        product_id=target.product_id,
        product_name=target.product_name,
        product_version=target.product_version,
        locale="en",
        blocks=blocks,
        links=related,
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        http_status=http_status,
        metadata={
            "description": "",
            "domain_id": target.domain_id,
            "version_id": target.version_id,
            "source_id": target.source_id,
            "source_version": target.source_version,
            "parser_version": MARKDOWN_PARSER_VERSION,
            "breadcrumbs": _breadcrumbs(blocks, title),
            "parent_url": None,
            "outgoing_ibm_links": outgoing_ibm,
            "external_links": external,
        },
    )


def extract_html_document(
    content: bytes,
    *,
    requested_url: str,
    final_url: str,
    http_status: int,
    target: OfficialSourceTarget,
) -> ExtractedDocument:
    """Extract one allowlisted product page without relying on site chrome."""
    canonical = canonicalize_source_url(
        final_url,
        allowed_host=target.allowed_host,
        path_prefix=target.docs_path_prefix,
    )
    if not is_source_page_url(
        canonical,
        allowed_host=target.allowed_host,
        path_prefix=target.docs_path_prefix,
        content_format="html",
    ):
        raise ExtractionError("final URL is not an allowlisted HTML documentation page")
    soup = BeautifulSoup(content, "html.parser")
    main = _choose_main(soup)
    title = _extract_html_title(soup, main)
    _normalize_html_semantics(main)
    for node in main.select(
        "script,style,noscript,template,svg,form,button,input,select,textarea,"
        "header,footer,nav,aside,[role=navigation],[aria-hidden=true]"
    ):
        node.decompose()
    _mark_inline_code(main)
    blocks = _extract_html_blocks(main, title)
    if sum(len(block.text) for block in blocks) < 120:
        raise ExtractionError(
            "extracted HTML content is suspiciously short; the page may be client-rendered"
        )
    related, outgoing_ibm, external = _extract_html_links(main, canonical, target)
    normalized = {
        "title": title,
        "blocks": [
            {"kind": block.kind, "heading_path": block.heading_path, "text": block.text}
            for block in blocks
        ],
    }
    content_hash = "sha256:" + hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ExtractedDocument(
        document_id="doc-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
        canonical_url=canonical,
        requested_url=canonicalize_source_url(
            requested_url,
            allowed_host=target.allowed_host,
            path_prefix=target.docs_path_prefix,
        ),
        title=title,
        product_id=target.product_id,
        product_name=target.product_name,
        product_version=target.product_version,
        locale="en",
        blocks=blocks,
        links=related,
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        http_status=http_status,
        metadata={
            "description": _meta_content(soup, "description"),
            "domain_id": target.domain_id,
            "version_id": target.version_id,
            "source_id": target.source_id,
            "source_version": target.source_version,
            "parser_version": HTML_PARSER_VERSION,
            "breadcrumbs": _html_breadcrumbs(soup, title),
            "parent_url": None,
            "outgoing_ibm_links": outgoing_ibm,
            "external_links": external,
        },
    )


def _parse_blocks(text: str, *, fallback_title: str) -> tuple[list[ContentBlock], str]:
    lines = text.splitlines()
    blocks: list[ContentBlock] = []
    title = fallback_title.strip()
    headings: list[str] = [title] if title else []
    buffer: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal buffer
        while buffer and not buffer[0].strip():
            buffer.pop(0)
        while buffer and not buffer[-1].strip():
            buffer.pop()
        if not buffer:
            return
        value = "\n".join(buffer).strip()
        nonempty = [line.strip() for line in buffer if line.strip()]
        kind = "paragraph"
        if nonempty and all(re.match(r"^(?:[-+*]|\d+[.)])\s+", line) for line in nonempty):
            kind = "list"
        elif len(nonempty) >= 2 and "|" in nonempty[0] and re.match(
            r"^\s*\|?\s*:?-+", nonempty[1]
        ):
            kind = "table"
        elif nonempty and all(line.startswith(">") for line in nonempty):
            kind = "quote"
        blocks.append(ContentBlock(kind, list(headings or ([title] if title else [])), value))
        buffer = []

    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            code_lines = [line.rstrip()]
            index += 1
            closed = False
            while index < len(lines):
                code_line = lines[index]
                code_lines.append(code_line.rstrip())
                if re.match(rf"^\s*{re.escape(marker[0])}{{{len(marker)},}}\s*$", code_line):
                    closed = True
                    index += 1
                    break
                index += 1
            if not closed:
                code_lines.append(marker)
            blocks.append(ContentBlock("code", list(headings or ([title] if title else [])), "\n".join(code_lines)))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            value = re.sub(r"\s+#+\s*$", "", heading.group(2)).strip()
            if level == 1:
                title = value
                headings = [value]
            else:
                if not title:
                    title = fallback_title.strip() or value
                base = headings or [title]
                headings = base[:max(1, level - 1)] + [value]
            index += 1
            continue
        if not line.strip():
            flush()
        else:
            buffer.append(line.rstrip())
        index += 1
    flush()
    title = title or fallback_title.strip() or "Official product documentation"
    if not blocks:
        raise ValueError("Markdown page contained no extractable blocks")
    return blocks, title


def _extract_links(
    text: str,
    base_url: str,
    target: OfficialSourceTarget,
) -> tuple[list[str], list[str], list[str]]:
    related: list[str] = []
    outgoing_ibm: list[str] = []
    external: list[str] = []
    seen: set[str] = set()
    for raw in _LINK.findall(text):
        raw = raw.strip("<>")
        if raw.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, raw)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        clean = urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
        if clean in seen:
            continue
        seen.add(clean)
        try:
            source_url = canonicalize_source_url(
                clean,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
            )
            last_segment = urlsplit(source_url).path.rstrip("/").rsplit("/", 1)[-1]
            if is_source_page_url(
                source_url,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
            ):
                related.append(source_url)
            elif last_segment and "." not in last_segment:
                parsed_source = urlsplit(source_url)
                markdown_url = canonicalize_source_url(
                    urlunsplit((
                        parsed_source.scheme,
                        parsed_source.netloc,
                        parsed_source.path.rstrip("/") + ".md",
                        parsed_source.query,
                        "",
                    )),
                    allowed_host=target.allowed_host,
                    path_prefix=target.docs_path_prefix,
                )
                related.append(markdown_url)
            continue
        except ValueError:
            pass
        host = (parsed.hostname or "").lower()
        if host == "ibm.com" or host.endswith(".ibm.com"):
            outgoing_ibm.append(clean)
        else:
            external.append(clean)
    return related, outgoing_ibm, external


def _breadcrumbs(blocks: list[ContentBlock], title: str) -> list[str]:
    for block in blocks:
        if block.heading_path:
            return block.heading_path
    return [title]


def _extract_html_links(
    main: Tag,
    base_url: str,
    target: OfficialSourceTarget,
) -> tuple[list[str], list[str], list[str]]:
    related: list[str] = []
    outgoing_ibm: list[str] = []
    external: list[str] = []
    seen: set[str] = set()
    for anchor in main.find_all("a", href=True):
        raw = str(anchor.get("href") or "").strip()
        if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, raw)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        clean = urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
        if clean in seen:
            continue
        seen.add(clean)
        try:
            source_url = canonicalize_source_url(
                clean,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
            )
            if is_source_page_url(
                source_url,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
                content_format="html",
            ):
                related.append(source_url)
            continue
        except ValueError:
            pass
        host = (parsed.hostname or "").lower().rstrip(".")
        if host == "ibm.com" or host.endswith(".ibm.com"):
            outgoing_ibm.append(clean)
        else:
            external.append(clean)
    return related, outgoing_ibm, external


def _html_breadcrumbs(soup: BeautifulSoup, title: str) -> list[str]:
    values: list[str] = []
    for node in soup.select(
        "nav[aria-label*=breadcrumb i] a, .breadcrumb a, [data-testid*=breadcrumb i] a"
    ):
        value = " ".join(node.get_text(" ", strip=True).split())
        if value and value not in values:
            values.append(value)
    if title not in values:
        values.append(title)
    return values
