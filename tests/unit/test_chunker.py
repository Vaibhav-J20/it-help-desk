"""Unit tests — Chunker"""

import pytest

from app.ingestion.chunker import (
    CHUNKER_VERSION,
    TARGET_MAX_CHARS,
    TARGET_MIN_CHARS,
    chunk_pages,
)
from app.ingestion.pdf_parser import PageRecord


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
        long_text = "Word sentence. " * 500   # ~7500 chars, will produce multiple chunks
        pages = _make_pages([long_text])
        chunks = chunk_pages(pages)
        assert len(chunks) > 1
        ordinals = [c.chunk_ordinal for c in chunks]
        assert ordinals == list(range(len(chunks)))

    def test_chunk_text_within_target_size(self):
        """Chunks should not exceed TARGET_MAX_CHARS (with a small buffer for edge cases)."""
        long_text = "A" * (TARGET_MAX_CHARS * 3)
        pages = _make_pages([long_text])
        chunks = chunk_pages(pages)
        for chunk in chunks:
            assert len(chunk.text) <= TARGET_MAX_CHARS + 100  # small buffer for boundary logic

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
        pages = _make_pages(["Real text here. " * 100])
        chunks = chunk_pages(pages)
        for chunk in chunks:
            assert chunk.text.strip() != ""
