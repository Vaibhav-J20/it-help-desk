"""
Text and HTML parser for web/documentation ingestion.

Converts Markdown, plain text, and simple HTML pages into PageRecord objects so
the existing chunker/indexer can treat web docs like PDF-derived documents.
"""

from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser

from app.ingestion.pdf_parser import PageRecord, ParseResult

PARSER_VERSION = "text-parser-v1"


class _ReadableHTMLParser(HTMLParser):
    """Small dependency-free HTML-to-text extractor."""

    _BLOCK_TAGS = {
        "article", "aside", "blockquote", "br", "div", "footer", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "li", "main", "nav", "ol", "p",
        "pre", "section", "table", "td", "th", "tr", "ul",
    }
    _SKIP_TAGS = {"script", "style", "svg", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return _normalise_text(html.unescape(" ".join(self.parts)))


def parse_text_document(content: bytes, source_uri: str) -> ParseResult:
    """
    Parse Markdown, HTML, or plain text into pseudo-pages.

    For web docs there are no real PDF pages, so page_number means section
    number. Citations still preserve source URI, title, and section path.
    """
    text = content.decode("utf-8", errors="replace")
    if _looks_like_html(text, source_uri):
        parser = _ReadableHTMLParser()
        parser.feed(text)
        text = parser.text()
    else:
        text = _strip_markdown_noise(text)
        text = _normalise_text(text)

    pages = _split_into_sections(text)
    full_text = "\n".join(page.text for page in pages if page.text)
    content_hash = "sha256:" + hashlib.sha256(full_text.encode("utf-8")).hexdigest()

    return ParseResult(
        source_uri=source_uri,
        pages=pages,
        total_pages=len(pages),
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
    )


def _looks_like_html(text: str, source_uri: str) -> bool:
    return source_uri.endswith((".html", "/")) or bool(re.search(r"<(?:html|body|main|article|h1|p)\b", text, re.I))


def _strip_markdown_noise(text: str) -> str:
    text = re.sub(r"```[a-zA-Z0-9_-]*", "\n```", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    return text


def _normalise_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_into_sections(text: str) -> list[PageRecord]:
    if not text.strip():
        return [PageRecord(page_number=1, text="", char_count=0)]

    heading_re = re.compile(r"(?m)^(#{1,4}\s+.+|[A-Z][A-Za-z0-9 /&().:-]{3,80})$")
    matches = list(heading_re.finditer(text))
    if not matches:
        return [PageRecord(page_number=1, text=text, char_count=len(text))]

    sections: list[str] = []
    first_start = matches[0].start()
    if first_start > 0 and text[:first_start].strip():
        sections.append(text[:first_start].strip())

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)

    return [
        PageRecord(page_number=i + 1, text=section, char_count=len(section))
        for i, section in enumerate(sections)
    ]
