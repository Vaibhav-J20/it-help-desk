"""Unit tests for RRF fusion."""
import pytest
from app.retrieval.fusion import reciprocal_rank_fusion


def _chunk(cid: str, **extra) -> dict:
    return {"chunk_id": cid, "chunk_text": "test", **extra}


def test_single_list_ordering():
    bm25 = [_chunk("a"), _chunk("b"), _chunk("c")]
    result = reciprocal_rank_fusion(bm25, [], k=60)
    ids = [r["chunk_id"] for r in result]
    assert ids == ["a", "b", "c"]


def test_two_lists_overlap_boosts_score():
    bm25 = [_chunk("a"), _chunk("b")]
    vector = [_chunk("b"), _chunk("c")]
    result = reciprocal_rank_fusion(bm25, vector, k=60)
    ids = [r["chunk_id"] for r in result]
    # "b" appears in both lists — should rank first
    assert ids[0] == "b"


def test_no_overlap_preserves_both():
    bm25 = [_chunk("a"), _chunk("b")]
    vector = [_chunk("c"), _chunk("d")]
    result = reciprocal_rank_fusion(bm25, vector, k=60)
    assert len(result) == 4
    assert {r["chunk_id"] for r in result} == {"a", "b", "c", "d"}


def test_empty_both_returns_empty():
    assert reciprocal_rank_fusion([], []) == []


def test_empty_bm25_uses_vector():
    vector = [_chunk("x"), _chunk("y")]
    result = reciprocal_rank_fusion([], vector, k=60)
    assert [r["chunk_id"] for r in result] == ["x", "y"]


def test_rrf_score_is_added():
    bm25 = [_chunk("a")]
    result = reciprocal_rank_fusion(bm25, [], k=60)
    assert "_rrf_score" in result[0]
    assert result[0]["_rrf_score"] == pytest.approx(1 / 61, rel=1e-4)


def test_sources_tracking():
    bm25 = [_chunk("a")]
    vector = [_chunk("a")]
    result = reciprocal_rank_fusion(bm25, vector, k=60)
    assert sorted(result[0]["_sources"]) == ["bm25", "vector"]
