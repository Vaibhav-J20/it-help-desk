"""Unit tests for app/ingestion/indexer.py — ID generation and status logic."""
import hashlib
import pytest

from app.ingestion.indexer import (
    _make_document_id,
    _make_revision_id,
    _make_chunk_id,
)


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
