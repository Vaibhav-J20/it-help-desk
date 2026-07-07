"""
Chunker — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/chunker.py

Splits a list of PageRecords into overlapping ChunkRecords.
Target: safely below the watsonx embedding model's 512-token input limit.
Uses a conservative character-count window because no tokenizer is available.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from app.ingestion.pdf_parser import PageRecord

logger = logging.getLogger(__name__)

CHUNKER_VERSION = "chunker-v3"

# Token estimation: PDF docs often tokenize denser than prose, so use a
# very conservative character window to stay under ibm/slate's 512-token
# embedding limit even for tables, commands, and URLs.
CHARS_PER_TOKEN = 2
TARGET_MIN_TOKENS = 180
TARGET_MAX_TOKENS = 240
OVERLAP_TOKENS = 40

TARGET_MIN_CHARS = TARGET_MIN_TOKENS * CHARS_PER_TOKEN
TARGET_MAX_CHARS = TARGET_MAX_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS    = OVERLAP_TOKENS    * CHARS_PER_TOKEN

# Heading detection: lines that look like section headings
_HEADING_RE = re.compile(
    r"^(?:\d+[\.\d]*\s+[A-Z]|[A-Z][A-Z\s]{4,}$|#{1,4}\s)",
    re.MULTILINE,
)


@dataclass
class ChunkRecord:
    """A single retrievable text chunk."""
    chunk_ordinal: int       # 0-based index within the document
    text: str
    page_start: int          # 1-based first page this chunk appears on
    page_end: int            # 1-based last page this chunk appears on
    section_path: str        # best-effort heading trail, e.g. "Installation > Bootstrap"
    content_hash: str        # sha256 of chunk text
    chunker_version: str
    token_estimate: int      # approximate token count


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _detect_section(text: str) -> str:
    """Extract a section heading from the start of a text block, best-effort."""
    lines = text.strip().splitlines()
    for line in lines[:5]:
        line = line.strip()
        if line and len(line) < 120 and _HEADING_RE.match(line):
            return line
    return ""


def _chunk_text(text: str, page_start: int, page_end: int) -> list[tuple[str, int, int]]:
    """
    Split a block of text into (chunk_text, page_start, page_end) tuples.
    Simple sliding-window split — section boundaries are respected where detected.
    """
    if not text.strip():
        return []

    results: list[tuple[str, int, int]] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + TARGET_MAX_CHARS, length)

        # If we're not at the very end, try to break at a sentence or paragraph boundary
        if end < length:
            # Prefer double newline (paragraph break)
            para_break = text.rfind("\n\n", start + TARGET_MIN_CHARS, end)
            if para_break != -1:
                end = para_break + 2
            else:
                # Fall back to sentence end
                sent_break = max(
                    text.rfind(". ", start + TARGET_MIN_CHARS, end),
                    text.rfind(".\n", start + TARGET_MIN_CHARS, end),
                )
                if sent_break != -1:
                    end = sent_break + 2

        chunk_text = text[start:end].strip()
        if chunk_text:
            results.append((chunk_text, page_start, page_end))

        # Advance: move forward by (chunk size - overlap), always forward
        next_start = end - OVERLAP_CHARS
        if next_start <= start:
            # Safety: must always advance to avoid infinite loop
            next_start = end
        start = next_start

    return results


def chunk_pages(pages: list[PageRecord]) -> list[ChunkRecord]:
    """
    Convert a list of PageRecords into a list of ChunkRecords.

    Strategy:
    - Concatenate consecutive pages until we reach TARGET_MAX_CHARS, then split.
    - Track which pages contribute to each chunk for page_start / page_end.
    - Pages with no text are skipped.

    Args:
        pages: Output of pdf_parser.parse_pdf().

    Returns:
        Ordered list of ChunkRecords, chunk_ordinal starting at 0.
    """
    chunks: list[ChunkRecord] = []
    ordinal = 0

    # Accumulate pages into windows
    buffer_text = ""
    buffer_page_start = 1
    buffer_page_end = 1
    current_section = ""

    def flush_buffer(text: str, p_start: int, p_end: int) -> None:
        nonlocal ordinal
        for chunk_text, cs, ce in _chunk_text(text, p_start, p_end):
            section = _detect_section(chunk_text) or current_section
            content_hash = "sha256:" + hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            chunks.append(ChunkRecord(
                chunk_ordinal=ordinal,
                text=chunk_text,
                page_start=cs,
                page_end=ce,
                section_path=section,
                content_hash=content_hash,
                chunker_version=CHUNKER_VERSION,
                token_estimate=_estimate_tokens(chunk_text),
            ))
            ordinal += 1

    for page in pages:
        if not page.text:
            continue

        # Detect heading at top of page to update section trail
        heading = _detect_section(page.text)
        if heading:
            current_section = heading

        if not buffer_text:
            buffer_page_start = page.page_number

        buffer_page_end = page.page_number
        buffer_text += "\n\n" + page.text if buffer_text else page.text

        # Flush when buffer is large enough
        if len(buffer_text) >= TARGET_MAX_CHARS:
            flush_buffer(buffer_text, buffer_page_start, buffer_page_end)
            buffer_text = ""

    # Flush any remaining text
    if buffer_text.strip():
        flush_buffer(buffer_text, buffer_page_start, buffer_page_end)

    logger.info("Chunked %d pages → %d chunks", len(pages), len(chunks))
    return chunks
