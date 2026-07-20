"""Unit tests for app/ingestion/indexer.py — ID generation and status logic."""
import hashlib
import pytest
import app.ingestion.indexer as indexer_module

from app.ingestion.indexer import (
    _embed_chunks_with_recovery,
    _make_document_id,
    _make_revision_id,
    _make_chunk_id,
)
from app.ingestion.chunker import ChunkRecord


# ── document ID ───────────────────────────────────────────────────────────────

def test_document_id_prefix():
    did = _make_document_id("cos://bucket/some/file.pdf")
    assert did.startswith("doc-")


def test_document_id_is_16_hex_chars():
    """The hex portion must be 16 characters (64 bits) to avoid collisions."""
    did = _make_document_id("cos://bucket/some/file.pdf")
    hex_part = did.removeprefix("doc-")
    assert len(hex_part) == 16
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_document_id_stable_for_same_uri():
    uri = "cos://my-bucket/path/doc.pdf"
    assert _make_document_id(uri) == _make_document_id(uri)


def test_document_id_different_for_different_uris():
    """Two distinct URIs must not produce the same 16-char ID."""
    # Use URIs that differ only in the last few characters — the old 4-char
    # truncation would collide for many such pairs.
    ids = {_make_document_id(f"cos://bucket/file-{i}.pdf") for i in range(50)}
    assert len(ids) == 50, "Collision detected among 50 distinct URIs"


# ── revision ID ───────────────────────────────────────────────────────────────

def test_revision_id_prefix():
    content_hash = "sha256:" + "a" * 64
    rev = _make_revision_id(content_hash)
    assert rev.startswith("rev-")


def test_revision_id_contains_date():
    """Revision ID format is rev-YYYY-MM-DD-<hash12>."""
    import re
    content_hash = "sha256:" + "b" * 64
    rev = _make_revision_id(content_hash)
    assert re.match(r"rev-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}", rev), rev


# ── chunk ID ──────────────────────────────────────────────────────────────────

def test_chunk_id_format():
    cid = _make_chunk_id("ocp_sno_support", "doc-abc123456789abcd", "rev-2026-01-01-abc123456789", 0)
    assert cid == "ocp_sno_support:doc-abc123456789abcd:rev-2026-01-01-abc123456789:chunk-0000"


def test_chunk_id_ordinal_zero_padded():
    cid = _make_chunk_id("ibm_bob", "doc-1234567890abcdef", "rev-2026-01-01-aaaaaaaaaaaa", 42)
    assert cid.endswith(":chunk-0042")


def test_embedding_length_error_is_split_and_recovered():
    text = "curl https://example.test/v1?a=1&b=2 --header x:y\n" * 40
    chunk = ChunkRecord(
        chunk_ordinal=0,
        text=text,
        page_start=7,
        page_end=7,
        section_path="Install > Commands",
        content_hash="sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        chunker_version="chunker-v6",
        token_estimate=800,
    )

    def embed(value: str) -> list[float]:
        if len(value) > 300:
            raise ValueError("input exceeds 512 token limit")
        return [1.0, 2.0]

    embedded, failures = _embed_chunks_with_recovery([chunk], embed)
    assert not failures
    assert len(embedded) > 1
    assert [item[0].chunk_ordinal for item in embedded] == list(range(len(embedded)))
    assert all(item[0].page_start == 7 for item in embedded)


def test_transient_embedding_error_is_not_split():
    text = "A normal chunk"
    chunk = ChunkRecord(0, text, 2, 2, "", "sha256:x", "chunker-v6", 3)

    def embed(_value: str) -> list[float]:
        raise RuntimeError("provider temporarily unavailable")

    embedded, failures = _embed_chunks_with_recovery([chunk], embed)
    assert embedded == []
    assert len(failures) == 1
    assert failures[0].pages == (2,)


def test_obsolete_embedding_path_is_absent():
    assert not hasattr(indexer_module, "_embed_chunks")
    assert not hasattr(indexer_module, "_embed_one")
