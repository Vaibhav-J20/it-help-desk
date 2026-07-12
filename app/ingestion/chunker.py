"""
Chunker — IBM IT Help Desk Copilot
Owner: Developer B
Module: app/ingestion/chunker.py

Splits a list of PageRecords into overlapping ChunkRecords.
Target: safely below the embedding model's token input limit.

Token-estimation strategy:
  IBM technical documentation (tables, commands, URLs) tokenises at roughly
  3–4 characters per token under most BPE tokenizers.  Using CHARS_PER_TOKEN=3
  (conservative end of that range) ensures chunks stay below the embedding
  model's 512-token hard limit with comfortable headroom.

  Previous value was 2 chars/token, which could produce chunks of up to
  480–960 actual tokens — well above the 512-token limit.

Page-attribution fix (chunker-v5):
  Each page boundary in the accumulated buffer is tracked so that chunks that
  span the buffer flush window are assigned the correct page_start/page_end,
  not the stale page_start from the beginning of the entire window.

Duplicate trailing-chunk fix (chunker-v5):
  When the sliding window's final step produces a chunk whose text is already
  fully contained within the previous chunk (as an overlap artefact), the
  duplicate is dropped.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from app.ingestion.pdf_parser import PageRecord

logger = logging.getLogger(__name__)

CHUNKER_VERSION = "chunker-v5"

# Conservative character-per-token estimate for dense IBM technical text.
# Set to 3 so that TARGET_MAX_TOKENS=400 → 1200 chars, giving a safe margin
# below a 512-token embedding model limit even for code-heavy pages.
CHARS_PER_TOKEN = 3
TARGET_MIN_TOKENS = 150
TARGET_MAX_TOKENS = 400
OVERLAP_TOKENS = 40

TARGET_MIN_CHARS = TARGET_MIN_TOKENS * CHARS_PER_TOKEN   # 450
TARGET_MAX_CHARS = TARGET_MAX_TOKENS * CHARS_PER_TOKEN   # 1200
OVERLAP_CHARS    = OVERLAP_TOKENS    * CHARS_PER_TOKEN   # 120

# Heading detection: lines that look like section headings.
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


def _chunk_text(
    text: str,
    page_boundaries: list[tuple[int, int]],
) -> list[tuple[str, int, int]]:
    """
    Split a block of text into (chunk_text, page_start, page_end) tuples.

    Uses a sliding window with overlap.  Paragraph and sentence boundaries are
    preferred over hard character limits.  Duplicate trailing chunks (where the
    final window is a strict suffix of the previous chunk) are dropped.

    Args:
        text:            The accumulated text to split.
        page_boundaries: Ordered list of (char_offset, page_number) pairs
                         marking where each page starts within `text`.
                         The first entry always has offset 0.

    Returns:
        List of (chunk_text, page_start, page_end) tuples.
    """
    if not text.strip():
        return []

    results: list[tuple[str, int, int]] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + TARGET_MAX_CHARS, length)

        # If not at the very end, try to break at a natural boundary.
        if end < length:
            # Prefer double newline (paragraph break).
            para_break = text.rfind("\n\n", start + TARGET_MIN_CHARS, end)
            if para_break != -1:
                end = para_break + 2
            else:
                # Fall back to sentence end.
                sent_break = max(
                    text.rfind(". ", start + TARGET_MIN_CHARS, end),
                    text.rfind(".\n", start + TARGET_MIN_CHARS, end),
                )
                if sent_break != -1:
                    end = sent_break + 2

        chunk_text = text[start:end].strip()

        if chunk_text:
            # Duplicate-trailing-chunk guard: drop this chunk only when it is
            # entirely within the overlap region of the previous chunk AND its
            # length is no greater than OVERLAP_CHARS.  This handles the case
            # where the final sliding-window step produces a tiny remnant that
            # is already fully covered by the previous chunk's trailing overlap.
            # We do NOT use a general endswith() check — that would incorrectly
            # drop legitimate chunks from repetitive text (e.g. test fixtures).
            is_overlap_duplicate = (
                results
                and len(chunk_text) <= OVERLAP_CHARS
                and results[-1][0].endswith(chunk_text)
            )
            if is_overlap_duplicate:
                pass  # drop — already covered by the previous chunk's overlap
            else:
                page_start, page_end = _page_range_for_span(start, end, page_boundaries)
                results.append((chunk_text, page_start, page_end))

        # Advance: move forward by (chunk size - overlap), always forward.
        next_start = end - OVERLAP_CHARS
        if next_start <= start:
            # Safety: must always advance to avoid infinite loop.
            next_start = end
        start = next_start

    return results


def _page_range_for_span(
    char_start: int,
    char_end: int,
    page_boundaries: list[tuple[int, int]],
) -> tuple[int, int]:
    """
    Return the (page_start, page_end) for the character span [char_start, char_end).

    page_boundaries is a sorted list of (char_offset, page_number) pairs.
    The page for a character position is the page whose offset is the largest
    offset that does not exceed the character position.
    """
    if not page_boundaries:
        return 1, 1

    def _page_at(pos: int) -> int:
        page = page_boundaries[0][1]
        for offset, pnum in page_boundaries:
            if offset <= pos:
                page = pnum
            else:
                break
        return page

    return _page_at(char_start), _page_at(char_end - 1)


def chunk_pages(pages: list[PageRecord]) -> list[ChunkRecord]:
    """
    Convert a list of PageRecords into a list of ChunkRecords.

    Strategy:
    - Concatenate consecutive pages until we reach TARGET_MAX_CHARS, then split.
    - Track character offsets of each page boundary within the buffer so that
      page_start / page_end on each chunk reflect the actual pages it covers.
    - Pages with no text are skipped.

    Args:
        pages: Output of pdf_parser.parse_pdf().

    Returns:
        Ordered list of ChunkRecords, chunk_ordinal starting at 0.
    """
    chunks: list[ChunkRecord] = []
    ordinal = 0

    # Buffer accumulates text across pages until a flush is triggered.
    buffer_text = ""
    # page_boundaries: list of (char_offset_in_buffer, page_number).
    # Rebuilt from scratch when the buffer is flushed.
    buffer_page_boundaries: list[tuple[int, int]] = []
    current_section = ""

    def flush_buffer(text: str, boundaries: list[tuple[int, int]]) -> None:
        nonlocal ordinal, current_section
        for chunk_text, ps, pe in _chunk_text(text, boundaries):
            # Prefer a heading detected within the chunk over the inherited trail.
            section = _detect_section(chunk_text) or current_section
            if _detect_section(chunk_text):
                current_section = _detect_section(chunk_text)
            content_hash = "sha256:" + hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            chunks.append(ChunkRecord(
                chunk_ordinal=ordinal,
                text=chunk_text,
                page_start=ps,
                page_end=pe,
                section_path=section,
                content_hash=content_hash,
                chunker_version=CHUNKER_VERSION,
                token_estimate=_estimate_tokens(chunk_text),
            ))
            ordinal += 1

    for page in pages:
        if not page.text:
            continue

        # Detect heading at top of page to update the section trail.
        heading = _detect_section(page.text)
        if heading:
            current_section = heading

        # Record this page's start offset in the buffer before appending.
        page_offset = len(buffer_text) + (2 if buffer_text else 0)  # +2 for the "\n\n" separator
        buffer_page_boundaries.append((page_offset, page.page_number))

        buffer_text += "\n\n" + page.text if buffer_text else page.text

        # Flush when buffer is large enough, then reset completely.
        if len(buffer_text) >= TARGET_MAX_CHARS:
            flush_buffer(buffer_text, buffer_page_boundaries)
            buffer_text = ""
            buffer_page_boundaries = []

    # Flush any remaining text.
    if buffer_text.strip():
        flush_buffer(buffer_text, buffer_page_boundaries)

    logger.info("Chunked %d pages → %d chunks", len(pages), len(chunks))
    return chunks
