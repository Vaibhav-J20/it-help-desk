from pathlib import Path

from scripts.audit_chunks import _validate_chunk, write_report


def _generic_chunk() -> dict:
    return {
        "chunk_id": "ibm_products:doc-1:rev-1:chunk-0000",
        "document_id": "doc-1",
        "revision_id": "rev-1",
        "domain_id": "ibm_products",
        "title": "Install IBM Example",
        "source_uri": "https://www.ibm.com/docs/en/example/1.0?topic=install",
        "source_type": "ibm_docs",
        "document_type": "installation_guide",
        "classification": "public",
        "access_scope": ["public", "isa_technical"],
        "product": "IBM Example",
        "product_version": "1.0",
        "locale": "en",
        "components": [],
        "topic_tags": ["example"],
        "section_path": "Install > Commands",
        "page_start": 1,
        "page_end": 1,
        "chunk_ordinal": 0,
        "chunk_text": "example install",
        "chunk_text_vector": [0.1] * 768,
        "content_hash": "sha256:test",
        "parser_version": "ibm-docs-html-v1",
        "chunker_version": "chunker-v6",
        "embedding_model_id": "ibm/granite-embedding-278m-multilingual",
        "embedding_dimension": 768,
        "ingested_at": "2026-07-14T00:00:00Z",
        "is_current": True,
    }


def test_audit_accepts_generic_ibm_product_chunk():
    assert _validate_chunk(_generic_chunk()) == []


def test_audit_requires_generic_product_version():
    chunk = _generic_chunk()
    del chunk["product_version"]
    assert any("product_version" in error for error in _validate_chunk(chunk))


def test_report_writer_does_not_remove_overall_status(tmp_path: Path):
    results = {
        "doc-1": {
            "total_chunks": 1,
            "sampled": 1,
            "errors_by_chunk": {},
            "pass": False,
            "title": "Example",
            "ocp_version": None,
            "display_version": "1.0",
        },
        "__overall_pass": False,
    }
    write_report(results, str(tmp_path / "report.md"))
    assert results["__overall_pass"] is False
