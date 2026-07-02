"""
Pure function: Reciprocal Rank Fusion over two ranked result lists.
No I/O — fully unit testable.

Formula: RRF(d) = Σ 1 / (k + rank_i(d))
Default k=60; read from settings in production.
"""


def reciprocal_rank_fusion(
    bm25_results: list[dict],
    vector_results: list[dict],
    k: int = 60,
    id_field: str = "chunk_id",
) -> list[dict]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    Args:
        bm25_results:   Ordered list of chunk dicts from BM25 search (index 0 = rank 1).
        vector_results: Ordered list of chunk dicts from vector kNN search.
        k:              RRF constant (default 60). Higher = flatter score distribution.
        id_field:       Field name used to deduplicate results.

    Returns:
        Merged list of chunk dicts ordered by descending RRF score.
        Each dict gets a "_rrf_score" key added.
        Each dict gets a "_sources" key: list of which searches found it ("bm25", "vector").
    """
    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}
    sources: dict[str, list[str]] = {}

    for rank, chunk in enumerate(bm25_results, start=1):
        cid = chunk[id_field]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        chunks[cid] = chunk
        sources.setdefault(cid, []).append("bm25")

    for rank, chunk in enumerate(vector_results, start=1):
        cid = chunk[id_field]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in chunks:
            chunks[cid] = chunk
        sources.setdefault(cid, []).append("vector")

    ranked = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

    result = []
    for cid in ranked:
        entry = dict(chunks[cid])
        entry["_rrf_score"] = round(scores[cid], 6)
        entry["_sources"] = sources[cid]
        result.append(entry)

    return result
