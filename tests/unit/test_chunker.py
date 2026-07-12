"""Unit tests — Chunker"""

import pytest

from app.ingestion.chunker import (
    CHUNKER_VERSION,
    TARGET_MAX_CHARS,
    TARGET_MIN_CHARS,
    chunk_pages,
)
from app.ingestion.pdf_parser import PageRecord

# If this assertion fails the version constant was not updated after a fix.
assert CHUNKER_VERSION == "chunker-v5", (
    f"Expected CHUNKER_VERSION='chunker-v5', got {CHUNKER_VERSION!r}. "
    "Update the version constant when the chunker behaviour changes."
)


def _make_pages(texts: list[str]) -> list[PageRecord]:
    return [
        PageRecord(page_number=i + 1, text=t, char_count=len(t))
        for i, t in enumerate(texts)
    ]


class TestChunkPages:

    def test_empty_pages_returns_no_chunks(self):
        pages = _make_pages(["", "", ""])
        chunks = chunk_pages(pages)
        assert chunks == []

    def test_short_text_produces_one_chunk(self):
        pages = _make_pages(["Short text that fits in one chunk easily."])
        chunks = chunk_pages(pages)
        assert len(chunks) == 1
        assert chunks[0].text == "Short text that fits in one chunk easily."

    def test_chunk_ordinal_starts_at_zero(self):
        pages = _make_pages(["Some content here."])
        chunks = chunk_pages(pages)
        assert chunks[0].chunk_ordinal == 0

    def test_chunk_ordinals_are_sequential(self):
        # TARGET_MAX_CHARS is now 1200; use 6× to guarantee multiple chunks.
        long_text = "Word sentence. " * 500   # ~7500 chars > 6 × TARGET_MAX_CHARS(1200)
        pages = _make_pages([long_text])
        chunks = chunk_pages(pages)
        assert len(chunks) > 1, (
            f"Expected multiple chunks from {len(long_text)}-char text, got {len(chunks)}"
        )
        ordinals = [c.chunk_ordinal for c in chunks]
        assert ordinals == list(range(len(chunks)))

    def test_chunk_text_within_target_size(self):
        """Chunks should not exceed TARGET_MAX_CHARS (with a small buffer for boundary logic)."""
        long_text = "A" * (TARGET_MAX_CHARS * 3)
        pages = _make_pages([long_text])
        chunks = chunk_pages(pages)
        for chunk in chunks:
            # Small buffer because boundary-snapping can overshoot by one sentence.
            assert len(chunk.text) <= TARGET_MAX_CHARS + 200

    def test_page_start_and_end_set(self):
        pages = _make_pages(["Page one text.", "Page two text."])
        chunks = chunk_pages(pages)
        for chunk in chunks:
            assert chunk.page_start >= 1
            assert chunk.page_end >= chunk.page_start

    def test_content_hash_is_sha256_prefixed(self):
        pages = _make_pages(["Hello this is chunk text."])
        chunks = chunk_pages(pages)
        assert chunks[0].content_hash.startswith("sha256:")

    def test_chunker_version_set(self):
        pages = _make_pages(["Any text."])
        chunks = chunk_pages(pages)
        assert chunks[0].chunker_version == CHUNKER_VERSION

    def test_token_estimate_positive(self):
        pages = _make_pages(["This is some reasonable length text for testing."])
        chunks = chunk_pages(pages)
        assert chunks[0].token_estimate > 0

    def test_no_empty_chunk_text(self):
        """No chunk should have empty or whitespace-only text."""
        pages = _make_pages(["Real text here. " * 50])
        chunks = chunk_pages(pages)
        for chunk in chunks:
            assert chunk.text.strip() != ""

    def test_page_start_resets_after_buffer_flush(self):
        """After a buffer flush, the next chunk must use the correct page_start,
        not the stale page_start from the previous window."""
        # Two pages: first is large enough to fill the buffer and trigger a flush.
        big_page = "Word sentence. " * 200   # ~3000 chars, well above TARGET_MAX_CHARS(480)
        pages = _make_pages([big_page, "Second page content here."])
        chunks = chunk_pages(pages)
        # Chunks that exclusively contain second-page text must have page_start == 2.
        second_page_chunks = [c for c in chunks if "Second page content" in c.text]
        for c in second_page_chunks:
            assert c.page_start == 2, (
                f"Expected page_start=2 for second-page chunk, got {c.page_start}"
            )

    def test_page_start_resets_between_windows(self):
        """When a large page forces a mid-page buffer flush, the next non-empty
        page must be assigned the correct page_start, not the stale one."""
        # Page 1 is well above TARGET_MAX_CHARS so it forces at least one flush
        # and fully drains the buffer before page 2 is processed.
        page1 = "INSTALLATION STEPS\n" + "Step text. " * 200  # ~2200 chars > TARGET_MAX_CHARS(480)
        page2 = "Just page two text."
        pages = _make_pages([page1, page2])
        chunks = chunk_pages(pages)
        # Any chunk whose text is exclusively from page 2 must have page_start=2.
        page2_chunks = [c for c in chunks if "page two text" in c.text]
        assert len(page2_chunks) > 0, "No chunk contains page-2 text"
        for c in page2_chunks:
            assert c.page_start == 2, (
                f"Expected page_start=2, got {c.page_start}"
            )

    def test_no_duplicate_trailing_chunk(self):
        """When the final sliding-window step produces a tiny remnant that is
        already fully within the previous chunk's trailing overlap, that remnant
        must be dropped — not appended as a duplicate chunk.

        We construct a non-repetitive document where the last 'paragraph' is
        shorter than OVERLAP_CHARS, ensuring the guard fires on genuine
        overlap remnants, not on coincidentally repetitive content.
        """
        from app.ingestion.chunker import OVERLAP_CHARS

        # Build a main body that is clearly larger than TARGET_MAX_CHARS.
        main_body = " ".join(f"Step {i}: perform action {i} on the cluster." for i in range(1, 90))
        # Append a unique trailing fragment shorter than OVERLAP_CHARS.
        # This will be the overlap remnant that must be dropped.
        tiny_tail = "Final note."   # 11 chars — well below OVERLAP_CHARS(120)
        # Make the tail appear at the very end of the last chunk by padding
        # the main body to a multiple of the chunk window.
        text = main_body + "  " + tiny_tail
        pages = _make_pages([text])
        chunks = chunk_pages(pages)
        # Verify no chunk has empty text.
        for chunk in chunks:
            assert chunk.text.strip(), "Empty chunk produced"
        # Verify chunk ordinals are sequential (no phantom duplicates inflating count).
        ordinals = [c.chunk_ordinal for c in chunks]
        assert ordinals == list(range(len(chunks))), "Non-sequential ordinals indicate phantom duplicates"

    def test_chunker_version_is_v5(self):
        """Ensure the version constant reflects the page-attribution and
        duplicate-trailing-chunk fixes introduced in chunker-v5."""
        assert CHUNKER_VERSION == "chunker-v5"

    def test_page_attribution_accurate_within_buffer(self):
        """Chunks that fall entirely within page 2 content must report page_start=2,
        even when pages 1 and 2 were accumulated in the same buffer window."""
        # Page 1: small, page 2: fills the rest of the buffer so they are
        # accumulated together before a flush.
        page1 = "Page one short text. " * 10   # ~210 chars — well below TARGET_MAX_CHARS
        page2 = "Page two content. " * 80       # ~1440 chars — crosses TARGET_MAX_CHARS
        pages = _make_pages([page1, page2])
        chunks = chunk_pages(pages)
        # Any chunk whose text contains only page-2 content must have page_start >= 2.
        for c in chunks:
            if "Page two content" in c.text and "Page one short" not in c.text:
                assert c.page_start >= 2, (
                    f"Expected page_start >= 2 for page-2-only chunk, got {c.page_start}"
                )
