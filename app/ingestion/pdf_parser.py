"""
PDF Parser — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/pdf_parser.py

Extracts text from PDFs page by page, preserving page numbers.
Uses pdfminer.six for text-native extraction. No OCR.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextContainer

logger = logging.getLogger(__name__)

PARSER_VERSION = "pdf-parser-v1"


@dataclass
class PageRecord:
    """Text content extracted from a single PDF page."""
    page_number: int   # 1-based
    text: str
    char_count: int
    section_path: str = ""  # optional structured-document heading boundary


@dataclass
class ParseResult:
    """Result of parsing a single PDF document."""
    source_uri: str
    pages: list[PageRecord]
    total_pages: int
    content_hash: str          # SHA-256 of full concatenated text
    parser_version: str


def parse_pdf(content: bytes, source_uri: str) -> ParseResult:
    """
    Extract text from PDF bytes, page by page, using pdfminer.six.

    Args:
        content:    Raw PDF bytes (from COS or local file).
        source_uri: The document's source URI (for logging and tracing only).

    Returns:
        ParseResult with one PageRecord per page (1-based page numbers).
        Pages with no extractable text are included with empty text
        and char_count=0 so downstream chunker can skip them.

    Raises:
        ValueError: If content is not a valid PDF or pdfminer fails to open it.
    """
    try:
        pdf_file = BytesIO(content)
        laparams = LAParams(
            line_overlap=0.5,
            char_margin=2.0,
            word_margin=0.1,
            boxes_flow=0.5,
            detect_vertical=False,
        )
        page_layouts = list(extract_pages(pdf_file, laparams=laparams))
    except Exception as exc:
        raise ValueError(f"Cannot open PDF from {source_uri}: {exc}") from exc

    pages: list[PageRecord] = []
    full_text_parts: list[str] = []

    for i, page_layout in enumerate(page_layouts):
        page_number = i + 1
        page_text_parts: list[str] = []

        for element in page_layout:
            if isinstance(element, LTTextContainer):
                text = element.get_text()
                if text.strip():
                    page_text_parts.append(text)

        page_text = " ".join(page_text_parts).strip()
        # Normalise whitespace: collapse multiple spaces/newlines
        import re
        page_text = re.sub(r"\n{3,}", "\n\n", page_text)
        page_text = re.sub(r" {2,}", " ", page_text)

        pages.append(PageRecord(
            page_number=page_number,
            text=page_text,
            char_count=len(page_text),
        ))
        if page_text:
            full_text_parts.append(page_text)

    full_text = "\n".join(full_text_parts)
    content_hash = "sha256:" + hashlib.sha256(full_text.encode("utf-8")).hexdigest()

    non_empty = sum(1 for p in pages if p.char_count > 0)
    logger.info(
        "Parsed %s: %d pages, %d non-empty, hash=%s",
        source_uri, len(pages), non_empty, content_hash[:28] + "...",
    )

    return ParseResult(
        source_uri=source_uri,
        pages=pages,
        total_pages=len(pages),
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
    )
