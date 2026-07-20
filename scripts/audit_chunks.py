"""
Chunk Quality Audit — OpenShift & SNO Support Copilot
Owner: Developer B (Anush)
Script: scripts/audit_chunks.py

Connects to local OpenSearch, samples chunks from every indexed document,
verifies all required fields are present, and prints a per-document report.

Usage:
    python scripts/audit_chunks.py
    python scripts/audit_chunks.py --index knowledge_chunks_v1 --sample 5
    python scripts/audit_chunks.py --doc-id doc-8e43 --sample 3

Exit codes:
    0 — all documents PASS
    1 — one or more documents FAIL
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from datetime import datetime, timezone

from dotenv import load_dotenv
from opensearchpy import OpenSearch

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Required fields every chunk must carry ────────────────────────────────────

REQUIRED_FIELDS: list[str] = [
    "chunk_id",
    "document_id",
    "revision_id",
    "domain_id",
    "title",
    "source_uri",
    "source_type",
    "document_type",
    "classification",
    "access_scope",
    "product",
    "components",
    "topic_tags",
    "section_path",
    "page_start",
    "page_end",
    "chunk_ordinal",
    "chunk_text",
    "chunk_text_vector",
    "content_hash",
    "parser_version",
    "chunker_version",
    "embedding_model_id",
    "embedding_dimension",
    "ingested_at",
    "is_current",
]

DOMAIN_REQUIRED_FIELDS = {
    "ocp_sno_support": ["ocp_version", "ocp_major", "ocp_minor", "deployment_type"],
    "ibm_products": ["product_version", "locale"],
}

TYPED_FIELDS: dict[str, type | tuple] = {
    "ocp_major": int,
    "ocp_minor": int,
    "embedding_dimension": int,
    "chunk_ordinal": int,
    "page_start": int,
    "page_end": int,
    "is_current": bool,
    "deployment_type": list,
    "components": list,
    "topic_tags": list,
    "access_scope": list,
    "chunk_text_vector": list,
}

VECTOR_DIM = 768


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_client() -> OpenSearch:
    from app.retrieval.opensearch_client import get_opensearch_client

    return get_opensearch_client()


def _list_document_ids(client: OpenSearch, index: str) -> list[str]:
    """Return all unique document_ids with is_current=True."""
    resp = client.search(
        index=index,
        body={
            "size": 0,
            "query": {"term": {"is_current": True}},
            "aggs": {"docs": {"terms": {"field": "document_id", "size": 10_000}}},
        },
    )
    buckets = resp["aggregations"]["docs"]["buckets"]
    return [b["key"] for b in buckets]


def _sample_chunks(
    client: OpenSearch, index: str, doc_id: str, n: int
) -> list[dict]:
    """Fetch n sample chunks for a given document_id (is_current only)."""
    resp = client.search(
        index=index,
        body={
            "size": n,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"document_id": doc_id}},
                        {"term": {"is_current": True}},
                    ]
                }
            },
            "sort": [{"chunk_ordinal": "asc"}],
        },
    )
    return [hit["_source"] for hit in resp["hits"]["hits"]]


def _count_chunks(client: OpenSearch, index: str, doc_id: str) -> int:
    resp = client.count(
        index=index,
        body={
            "query": {
                "bool": {
                    "must": [
                        {"term": {"document_id": doc_id}},
                        {"term": {"is_current": True}},
                    ]
                }
            }
        },
    )
    return resp["count"]


def _validate_chunk(chunk: dict) -> list[str]:
    """Return a list of validation error strings for a single chunk."""
    errors: list[str] = []

    # 1. Required fields present and non-null
    for field in REQUIRED_FIELDS:
        if field not in chunk or chunk[field] is None:
            errors.append(f"missing/null: {field}")
    for field in DOMAIN_REQUIRED_FIELDS.get(chunk.get("domain_id"), []):
        if field not in chunk or chunk[field] is None:
            errors.append(f"missing/null for {chunk.get('domain_id')}: {field}")

    # 2. Type checks
    for field, expected_type in TYPED_FIELDS.items():
        if field in chunk and chunk[field] is not None:
            if not isinstance(chunk[field], expected_type):
                errors.append(
                    f"type error: {field} is {type(chunk[field]).__name__}, "
                    f"expected {expected_type if isinstance(expected_type, str) else expected_type.__name__ if not isinstance(expected_type, tuple) else str(expected_type)}"
                )

    # 3. ocp_major / ocp_minor consistency
    version = chunk.get("ocp_version", "")
    if version and "." in str(version):
        parts = str(version).split(".")
        try:
            if int(parts[0]) != chunk.get("ocp_major"):
                errors.append(
                    f"ocp_major mismatch: ocp_version={version} but ocp_major={chunk.get('ocp_major')}"
                )
            if int(parts[1]) != chunk.get("ocp_minor"):
                errors.append(
                    f"ocp_minor mismatch: ocp_version={version} but ocp_minor={chunk.get('ocp_minor')}"
                )
        except (ValueError, IndexError):
            errors.append(f"unparseable ocp_version: {version}")

    # 4. Vector dimension
    vector = chunk.get("chunk_text_vector")
    if isinstance(vector, list) and len(vector) != VECTOR_DIM:
        errors.append(
            f"vector dim={len(vector)}, expected {VECTOR_DIM}"
        )

    # 5. page_start <= page_end
    ps = chunk.get("page_start")
    pe = chunk.get("page_end")
    if ps is not None and pe is not None and ps > pe:
        errors.append(f"page_start ({ps}) > page_end ({pe})")

    # 6. chunk_text non-empty
    text = chunk.get("chunk_text", "")
    if not text or len(text.strip()) == 0:
        errors.append("chunk_text is empty")

    # 7. chunk_id format check (domain:doc:rev:chunk-NNNN)
    chunk_id = chunk.get("chunk_id", "")
    parts = chunk_id.split(":")
    if len(parts) != 4:
        errors.append(f"chunk_id has wrong segment count: {chunk_id!r}")

    # 8. domain_id must be an active configured domain.
    from app.policy.domain_policy import is_in_scope

    if not is_in_scope(str(chunk.get("domain_id") or "")):
        errors.append(f"domain_id={chunk.get('domain_id')!r} is not active in config/domains.yaml")

    return errors


# ── Main audit logic ──────────────────────────────────────────────────────────

def audit(
    index: str,
    sample_n: int,
    target_doc_id: str | None,
) -> dict:
    """
    Run the chunk audit and return a results dict.

    Returns:
        {
          "doc_id": {
            "total_chunks": int,
            "sampled": int,
            "errors_by_chunk": { chunk_id: [error, ...] },
            "pass": bool,
            "title": str,
            "ocp_version": str,
          },
          ...
        }
    """
    client = _build_client()

    # Cluster health check
    health = client.cluster.health()
    print(f"\n✓ OpenSearch cluster status: {health['status']}  "
          f"(index: {index})\n")

    doc_ids = _list_document_ids(client, index)
    if not doc_ids:
        print("No documents found with is_current=True. Is the corpus indexed?")
        sys.exit(1)

    if target_doc_id:
        if target_doc_id not in doc_ids:
            print(f"ERROR: doc_id {target_doc_id!r} not found in index.")
            sys.exit(1)
        doc_ids = [target_doc_id]

    print(f"{'─'*70}")
    print(f"  Auditing {len(doc_ids)} document(s) — {sample_n} chunk(s) sampled each")
    print(f"{'─'*70}")

    results: dict = {}
    overall_pass = True

    for doc_id in doc_ids:
        total = _count_chunks(client, index, doc_id)
        samples = _sample_chunks(client, index, doc_id, sample_n)

        doc_result = {
            "total_chunks": total,
            "sampled": len(samples),
            "errors_by_chunk": {},
            "pass": True,
            "title": samples[0].get("title", "?") if samples else "?",
            "ocp_version": samples[0].get("ocp_version", "?") if samples else "?",
            "display_version": (
                samples[0].get("ocp_version")
                or samples[0].get("product_version")
                or "?"
            ) if samples else "?",
        }

        for chunk in samples:
            cid = chunk.get("chunk_id", "UNKNOWN")
            errors = _validate_chunk(chunk)
            if errors:
                doc_result["errors_by_chunk"][cid] = errors
                doc_result["pass"] = False
                overall_pass = False

        results[doc_id] = doc_result

        status = "PASS ✅" if doc_result["pass"] else "FAIL ❌"
        print(f"\n  {doc_id}  ({doc_result['display_version']})  →  {status}")
        print(f"    Title:        {textwrap.shorten(doc_result['title'], 60)}")
        print(f"    Total chunks: {total}")
        print(f"    Sampled:      {doc_result['sampled']}")

        if not doc_result["pass"]:
            for cid, errs in doc_result["errors_by_chunk"].items():
                print(f"    Chunk {cid}:")
                for e in errs:
                    print(f"      ✗ {e}")
        else:
            # Show a preview of first chunk text
            if samples:
                preview = textwrap.shorten(
                    samples[0].get("chunk_text", ""), width=120
                )
                print(f"    Text preview: {preview!r}")
                print(f"    Section:      {samples[0].get('section_path', '?')}")
                print(f"    Pages:        {samples[0].get('page_start')}–{samples[0].get('page_end')}")

    print(f"\n{'─'*70}")
    overall_label = "ALL PASS ✅" if overall_pass else "FAILURES DETECTED ❌"
    print(f"  Audit complete — {overall_label}")
    print(f"  Documents: {len(results)}   "
          f"Passed: {sum(1 for r in results.values() if r['pass'])}   "
          f"Failed: {sum(1 for r in results.values() if not r['pass'])}")
    print(f"{'─'*70}\n")

    results["__overall_pass"] = overall_pass
    return results


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(results: dict, out_path: str) -> None:
    """Write audit results as a Markdown file."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    overall = results.get("__overall_pass", True)
    results = {key: value for key, value in results.items() if key != "__overall_pass"}

    lines = [
        "# Chunk Quality Audit Report",
        "",
        f"**Date:** {now}  ",
        f"**Overall:** {'✅ ALL PASS' if overall else '❌ FAILURES DETECTED'}  ",
        f"**Documents audited:** {len(results)}  ",
        "",
        "---",
        "",
        "## Per-Document Results",
        "",
        "| Document ID | Product Version | Total Chunks | Sampled | Status |",
        "|---|---|---|---|---|",
    ]

    for doc_id, r in results.items():
        status = "PASS ✅" if r["pass"] else "FAIL ❌"
        lines.append(
            f"| {doc_id} | {r['display_version']} | {r['total_chunks']} "
            f"| {r['sampled']} | {status} |"
        )

    lines += ["", "---", "", "## Detail"]

    for doc_id, r in results.items():
        lines.append(f"\n### {doc_id} — {r['title']}")
        lines.append(f"- Product Version: `{r['display_version']}`")
        lines.append(f"- Total chunks (is_current=True): **{r['total_chunks']}**")
        lines.append(f"- Sampled: {r['sampled']}")

        if r["pass"]:
            lines.append("- Status: **PASS** — all sampled chunks contain required fields with correct types")
        else:
            lines.append("- Status: **FAIL** — errors found in sampled chunks:")
            for cid, errs in r["errors_by_chunk"].items():
                lines.append(f"\n  **Chunk:** `{cid}`")
                for e in errs:
                    lines.append(f"  - {e}")

    lines += [
        "",
        "---",
        "",
        "## Validation Rules Applied",
        "",
        "1. All required fields present and non-null",
        "2. Type correctness (`ocp_major`/`ocp_minor` = int, `is_current` = bool, arrays = list)",
        "3. `ocp_major`/`ocp_minor` consistent with `ocp_version` string",
        f"4. `chunk_text_vector` dimension = {VECTOR_DIM}",
        "5. `page_start` ≤ `page_end`",
        "6. `chunk_text` non-empty",
        "7. `chunk_id` has 4 colon-separated segments",
        "8. `domain_id` is active in `config/domains.yaml` and domain-specific fields exist",
        "",
        "---",
        "*Generated by `scripts/audit_chunks.py`*",
    ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  Report written to: {out_path}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit chunk quality in OpenSearch for all indexed documents"
    )
    parser.add_argument(
        "--index",
        default=os.getenv("OPENSEARCH_INDEX_CHUNKS", "knowledge_chunks_v1"),
        help="OpenSearch chunks index name (default: knowledge_chunks_v1)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Number of chunks to sample per document (default: 10)",
    )
    parser.add_argument(
        "--doc-id",
        default=None,
        help="Audit only this document_id (default: all documents)",
    )
    parser.add_argument(
        "--report",
        default="docs/operations/CHUNK_AUDIT.md",
        help="Path to write Markdown audit report (default: docs/operations/CHUNK_AUDIT.md)",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing the Markdown report",
    )
    args = parser.parse_args()

    results = audit(
        index=args.index,
        sample_n=args.sample,
        target_doc_id=args.doc_id,
    )

    if not args.no_report:
        write_report(results, args.report)

    sys.exit(0 if results.get("__overall_pass", True) else 1)


if __name__ == "__main__":
    main()
