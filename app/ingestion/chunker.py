"""
Chunker — IBM IT Help Desk Copilot
Owner: Developer B
Module: app/ingestion/chunker.py

Splits a list of PageRecords into overlapping ChunkRecords.
Target: safely below the embedding model's token input limit.

Token-budget strategy (chunker-v6):
  Technical prose, commands, tables, paths, and URLs have very different token
  density. A fixed chars/token ratio therefore cannot enforce the embedding
  model limit. v6 counts lexical/subword-like pieces, gives punctuation its own
  budget, and finds every chunk boundary against TARGET_MAX_TOKENS. A character
  ceiling remains only as a second safety bound.

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

CHUNKER_VERSION = "chunker-v6"

# Character limits remain an additional memory/response bound. They are no
# longer treated as the token counter.
CHARS_PER_TOKEN = 4
TARGET_MIN_TOKENS = 150
TARGET_MAX_TOKENS = 400
OVERLAP_TOKENS = 40

TARGET_MIN_CHARS = TARGET_MIN_TOKENS * CHARS_PER_TOKEN
TARGET_MAX_CHARS = TARGET_MAX_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN

_TOKEN_PIECE_RE = re.compile(r"[A-Za-z0-9_]+|[^\w\s]", re.UNICODE)

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


def estimate_tokens(text: str) -> int:
    """Conservative local token estimate for prose and dense technical text.

    Every punctuation character receives a token. Alphanumeric pieces are
    charged in four-character subword units, which catches long identifiers,
    hashes, paths, and minified values that a word counter would undercount.
    The embedding provider remains the final authority; the indexer has an
    adaptive split-and-retry path for provider-reported length errors.
    """
    if not text:
        return 0
    count = 0
    for piece in _TOKEN_PIECE_RE.findall(text):
        if piece[0].isalnum() or piece[0] == "_":
            count += max(1, (len(piece) + 3) // 4)
        else:
            count += 1
    return max(1, count)


def _estimate_tokens(text: str) -> int:
    """Backward-compatible private alias used by older tests/imports."""
    return estimate_tokens(text)


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
        hard_end = min(start + TARGET_MAX_CHARS, length)
        end = _end_for_token_budget(text, start, hard_end, TARGET_MAX_TOKENS)

        # If not at the very end, try to break at a natural boundary.
        if end < length:
            minimum_end = _end_for_token_budget(
                text, start, end, min(TARGET_MIN_TOKENS, TARGET_MAX_TOKENS)
            )
            # Prefer double newline (paragraph break).
            para_break = text.rfind("\n\n", minimum_end, end)
            if para_break != -1:
                end = para_break + 2
            else:
                # A line boundary keeps command sequences and table rows intact
                # more often than a blind character cut.
                line_break = text.rfind("\n", minimum_end, end)
                if line_break != -1:
                    end = line_break + 1
                else:
                # Fall back to sentence end.
                    sent_break = max(
                        text.rfind(". ", minimum_end, end),
                        text.rfind(".\n", minimum_end, end),
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

        if end >= length:
            break

        # Advance: move forward by (chunk size - overlap), always forward.
        next_start = _start_for_overlap(text, start, end, OVERLAP_TOKENS)
        if next_start <= start:
            # Safety: must always advance to avoid infinite loop.
            next_start = end
        start = next_start

    return results


def _end_for_token_budget(text: str, start: int, hard_end: int, budget: int) -> int:
    """Find the furthest character end whose local estimate fits the budget."""
    if start >= hard_end:
        return hard_end
    if estimate_tokens(text[start:hard_end]) <= budget:
        return hard_end
    low, high = start + 1, hard_end
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[start:middle]) <= budget:
            low = middle
        else:
            high = middle - 1
    return max(start + 1, low)


def _start_for_overlap(text: str, chunk_start: int, end: int, budget: int) -> int:
    """Choose a forward-moving overlap start bounded by an estimated token budget."""
    if budget <= 0:
        return end
    low = max(chunk_start + 1, end - OVERLAP_CHARS)
    for candidate in range(low, end):
        if estimate_tokens(text[candidate:end]) <= budget:
            # Avoid starting halfway through a word or identifier.
            boundary = re.search(r"\s", text[candidate:end])
            return candidate + boundary.end() if boundary else candidate
    return end


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
                token_estimate=estimate_tokens(chunk_text),
            ))
            ordinal += 1

    for page in pages:
        if not page.text:
            continue

        # Structured HTML parsing marks explicit section boundaries. PDF pages
        # leave section_path empty, so changing page headers do not force tiny
        # page-sized chunks during PDF ingestion.
        heading = page.section_path or _detect_section(page.text)
        # Structured web extraction emits one pseudo-page per heading path.
        # Do not merge a new section into the previous section merely because
        # both happen to be short; section precision is critical for commands.
        if (
            buffer_text
            and page.section_path
            and current_section
            and heading != current_section
        ):
            flush_buffer(buffer_text, buffer_page_boundaries)
            buffer_text = ""
            buffer_page_boundaries = []
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
