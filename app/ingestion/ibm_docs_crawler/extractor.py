"""Structure-preserving IBM Docs HTML extraction."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from app.ingestion.pdf_parser import PageRecord, ParseResult

from .models import ContentBlock, ExtractedDocument
from .registry import CrawlTarget
from .urls import canonicalize_url, is_in_target_scope

PARSER_VERSION = "ibm-docs-html-v1"
_REMOVABLE = (
    "script,style,noscript,template,svg,form,button,input,select,textarea,"
    "header,footer,nav,aside,[role=navigation],[aria-hidden=true]"
)
_BLOCK_TAGS = [
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "ul", "ol", "table",
    "blockquote", "dl",
]


class ExtractionError(ValueError):
    pass


def extract_document(
    content: bytes,
    *,
    requested_url: str,
    final_url: str,
    http_status: int,
    target: CrawlTarget,
) -> ExtractedDocument:
    canonical = canonicalize_url(final_url)
    if not is_in_target_scope(canonical, target.docs_path_prefix):
        raise ExtractionError("final URL is outside the approved product path")

    # html.parser is intentional: it is the pinned stdlib parsing behavior for
    # this extractor. Do not switch to lxml/html5lib without fixture review.
    soup = BeautifulSoup(content, "html.parser")
    main = _choose_main(soup)
    title = _extract_title(soup, main)
    breadcrumbs, parent_url = _extract_breadcrumbs(soup, canonical, target.docs_path_prefix)
    _normalize_html_semantics(main)
    for node in main.select(_REMOVABLE):
        node.decompose()
    _mark_inline_code(main)

    blocks = _extract_blocks(main, title)
    if sum(len(block.text) for block in blocks) < 120:
        raise ExtractionError(
            "extracted content is suspiciously short; the page may be client-rendered"
        )
    links = _extract_links(main, canonical, target.docs_path_prefix)
    outgoing_ibm_links, external_links = _extract_external_links(
        main, canonical, target.docs_path_prefix
    )
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
    description = _meta_content(soup, "description")

    return ExtractedDocument(
        document_id=document_id,
        canonical_url=canonical,
        requested_url=canonicalize_url(requested_url),
        title=title,
        product_id=target.product_id,
        product_name=target.product_name,
        product_version=target.product_version,
        locale="en",
        blocks=blocks,
        links=links,
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        http_status=http_status,
        metadata={
            "description": description,
            "domain_id": target.domain_id,
            "version_id": target.version_id,
            "parser_version": PARSER_VERSION,
            "breadcrumbs": breadcrumbs,
            "parent_url": parent_url,
            "outgoing_ibm_links": outgoing_ibm_links,
            "external_links": external_links,
        },
    )


def to_parse_result(document: ExtractedDocument) -> ParseResult:
    """Convert heading groups into pseudo-pages for the shared chunker."""
    grouped: OrderedDict[tuple[str, ...], list[str]] = OrderedDict()
    for block in document.blocks:
        key = tuple(block.heading_path or [document.title])
        grouped.setdefault(key, []).append(block.text)
    pages: list[PageRecord] = []
    for number, (heading_path, texts) in enumerate(grouped.items(), start=1):
        heading = " > ".join(part for part in heading_path if part)
        body = "\n\n".join(texts)
        text = f"# {heading}\n\n{body}" if heading else body
        pages.append(PageRecord(
            page_number=number,
            text=text,
            char_count=len(text),
            section_path=heading,
        ))
    return ParseResult(
        source_uri=document.canonical_url,
        pages=pages,
        total_pages=len(pages),
        content_hash=document.content_hash,
        parser_version=PARSER_VERSION,
    )


def _choose_main(soup: BeautifulSoup) -> Tag:
    """Prefer semantic content containers; use body only as a last resort."""
    candidates = [
        soup.find("main"),
        soup.find(attrs={"role": "main"}),
        soup.find("article"),
        soup.select_one("#content"),
        soup.select_one(".ibm-docs-content"),
        soup.body,
    ]
    tags = [candidate for candidate in candidates if isinstance(candidate, Tag)]
    if not tags:
        raise ExtractionError("HTML has no document body")
    return tags[0]


def _extract_title(soup: BeautifulSoup, main: Tag) -> str:
    h1 = main.find("h1")
    if h1 and _clean_text(h1.get_text(" ", strip=True)):
        return _clean_text(h1.get_text(" ", strip=True))
    for key in ("og:title", "twitter:title", "title"):
        meta = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if meta and meta.get("content"):
            return _clean_text(str(meta["content"]))
    if soup.title:
        return _clean_text(soup.title.get_text(" ", strip=True))
    raise ExtractionError("no document title found")


def _mark_inline_code(main: Tag) -> None:
    for code in main.find_all("code"):
        if code.find_parent("pre"):
            continue
        value = code.get_text(" ", strip=True)
        code.replace_with(f"`{value}`")


def _normalize_html_semantics(main: Tag) -> None:
    """Convert common design-system markup into extractable HTML blocks.

    IBM product landing pages use Carbon custom elements for product cards and
    put accordion titles inside buttons.  BeautifulSoup preserves those
    elements, but the block extractor intentionally reads only semantic HTML.
    Normalize the small set of structures here so product names and their
    descriptions are not silently lost.
    """
    for button in list(main.find_all("button")):
        if button.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"]):
            button.unwrap()

    for heading in list(main.select("[role=heading][aria-level]")):
        if heading.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        try:
            level = min(6, max(1, int(str(heading.get("aria-level") or "3"))))
        except ValueError:
            level = 3
        heading.name = f"h{level}"

    for card in main.find_all("c4d-card-group-item"):
        for child in card.find_all("div", recursive=False):
            if _clean_text(child.get_text(" ", strip=True)):
                child.name = "p"

    # The IBM product catalog is server-rendered, but its result count and
    # product cards are expressed with CSS classes rather than semantic tags.
    for summary in main.select("[data-slot=result-summary]"):
        summary.name = "p"
    for heading in main.select(".ibm-search__results__card .bx--card__heading"):
        # Catalog cards have no semantic section parent, so h2 prevents one
        # result from becoming a child of the preceding result.
        heading.name = "h2"
    for description in main.select(".ibm-search__results__card .bx--card__copy"):
        description.name = "p"


def _extract_blocks(main: Tag, title: str) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    heading_stack = [title]
    previous: tuple[str, tuple[str, ...], str] | None = None
    for node in main.find_all(_BLOCK_TAGS, recursive=True):
        if not isinstance(node, Tag):
            continue
        if node.name in {"p", "ul", "ol", "blockquote", "dl"} and node.find_parent(
            ["pre", "table", "ul", "ol", "blockquote", "dl"]
        ):
            continue
        name = node.name.lower()
        if name.startswith("h") and name[1:].isdigit():
            heading = _clean_text(node.get_text(" ", strip=True))
            if not heading:
                continue
            level = int(name[1:])
            if level == 1:
                heading_stack = [heading]
            else:
                heading_stack = heading_stack[: max(1, level - 1)] + [heading]
            continue
        kind, text = _block_text(node)
        if not text:
            continue
        signature = (kind, tuple(heading_stack), text)
        if signature == previous:
            continue
        blocks.append(ContentBlock(kind=kind, heading_path=list(heading_stack), text=text))
        previous = signature
    return blocks


def _block_text(node: Tag) -> tuple[str, str]:
    if node.name == "pre":
        language = ""
        code = node.find("code")
        if code:
            for class_name in code.get("class", []):
                if str(class_name).startswith("language-"):
                    language = str(class_name).removeprefix("language-")
                    break
        raw = node.get_text("\n", strip=False).strip("\n")
        return "code", f"```{language}\n{raw}\n```"
    if node.name in {"ul", "ol"}:
        ordered = node.name == "ol"
        lines = []
        for index, item in enumerate(node.find_all("li", recursive=False), start=1):
            text = _clean_text(item.get_text(" ", strip=True))
            if text:
                lines.append(f"{index}. {text}" if ordered else f"- {text}")
        return "list", "\n".join(lines)
    if node.name == "table":
        return "table", _table_to_markdown(node)
    if node.name == "blockquote":
        text = _clean_text(node.get_text(" ", strip=True))
        return "quote", "\n".join(f"> {line}" for line in text.splitlines())
    if node.name == "dl":
        pairs = []
        for term in node.find_all("dt", recursive=False):
            description = term.find_next_sibling("dd")
            if description:
                pairs.append(
                    f"- **{_clean_text(term.get_text(' ', strip=True))}:** "
                    f"{_clean_text(description.get_text(' ', strip=True))}"
                )
        return "definition_list", "\n".join(pairs)
    return "paragraph", _clean_text(node.get_text(" ", strip=True))


def _table_to_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        cells = [
            _clean_text(cell.get_text(" ", strip=True)).replace("|", "\\|")
            for cell in row.find_all(["th", "td"], recursive=False)
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    output = [
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(output)


def _extract_links(main: Tag, base_url: str, prefix: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for anchor in main.find_all("a", href=True):
        try:
            url = canonicalize_url(str(anchor["href"]), base_url)
        except ValueError:
            continue
        if url not in seen and is_in_target_scope(url, prefix):
            seen.add(url)
            links.append(url)
    return links


def _extract_breadcrumbs(
    soup: BeautifulSoup,
    base_url: str,
    prefix: str,
) -> tuple[list[str], str | None]:
    labels: list[str] = []
    parent_url: str | None = None
    containers: list[Tag] = []
    for node in soup.find_all(["nav", "ol", "ul", "div"]):
        if not isinstance(node, Tag):
            continue
        marker = " ".join((
            str(node.get("aria-label", "")),
            " ".join(str(value) for value in node.get("class", [])),
            str(node.get("data-testid", "")),
        )).lower()
        if "breadcrumb" in marker:
            containers.append(node)
    for container in containers[:1]:
        for anchor in container.find_all("a", href=True):
            label = _clean_text(anchor.get_text(" ", strip=True))
            if label and label not in labels:
                labels.append(label)
            try:
                candidate = canonicalize_url(str(anchor["href"]), base_url)
            except ValueError:
                continue
            if candidate != base_url and is_in_target_scope(candidate, prefix):
                parent_url = candidate
    return labels, parent_url


def _extract_external_links(
    main: Tag,
    base_url: str,
    prefix: str,
) -> tuple[list[str], list[str]]:
    ibm_links: list[str] = []
    external_links: list[str] = []
    seen: set[str] = set()
    for anchor in main.find_all("a", href=True):
        raw = str(anchor["href"]).strip()
        if not raw or raw.startswith(("mailto:", "tel:", "javascript:")):
            continue
        parsed = urlsplit(urljoin(base_url, raw))
        if parsed.scheme != "https" or not parsed.hostname:
            continue
        url = urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))
        if url in seen:
            continue
        seen.add(url)
        host = parsed.hostname.lower()
        if host in {"ibm.com", "www.ibm.com"} or host.endswith(".ibm.com"):
            try:
                canonical = canonicalize_url(url)
            except ValueError:
                canonical = url
            if not is_in_target_scope(canonical, prefix):
                ibm_links.append(canonical)
        else:
            external_links.append(url)
    return ibm_links, external_links


def _meta_content(soup: BeautifulSoup, name: str) -> str:
    meta = soup.find("meta", attrs={"name": name})
    return _clean_text(str(meta.get("content", ""))) if meta else ""


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
