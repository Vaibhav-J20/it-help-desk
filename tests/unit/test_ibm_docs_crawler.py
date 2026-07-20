from __future__ import annotations

from dataclasses import replace
import gzip
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.ingestion.chunker import chunk_pages
from app.ingestion.ibm_docs_crawler.crawler import (
    _is_nonfatal_extraction_error,
    _topic_redirect_was_lost,
)
from app.ingestion.ibm_docs_crawler.extractor import (
    ExtractionError,
    extract_document,
    to_parse_result,
)
from app.ingestion.ibm_docs_crawler.fetcher import FetchSettings, PoliteFetcher
from app.ingestion.ibm_docs_crawler.promotion import index_run_to_staging
from app.ingestion.ibm_docs_crawler import promotion as promotion_module
from app.ingestion.ibm_docs_crawler.registry import (
    CrawlTarget,
    RegistryError,
    get_enabled_target,
    load_registry,
)
from app.ingestion.ibm_docs_crawler.robots import (
    RobotsPolicyError,
    load_robots_policy,
    policy_from_text,
)
from app.ingestion.ibm_docs_crawler.sitemap import SitemapError, parse_sitemap
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage
from app.ingestion.ibm_docs_crawler.urls import (
    canonicalize_url,
    is_in_target_scope,
    validate_ibm_docs_url,
)
def _target() -> CrawlTarget:
    return CrawlTarget(
        product_id="example",
        product_name="IBM Example",
        domain_id="ibm_products",
        docs_path_prefix="/docs/en/example/1.0",
        aliases=("example",),
        version_id="1.0",
        product_version="1.0",
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=start",
        max_pages=10,
        sitemap_url="https://www.ibm.com/docs/en/sitemap.xml",
        run_context={
            "mode": "public-ibm-docs",
            "registry_enabled": "true",
        },
    )


HTML = b"""
<html><head><title>Fallback</title><meta name="description" content="Example docs"></head>
<body><header>Navigation</header><main>
<h1>Install IBM Example</h1>
<p>This procedure installs the product on a supported workstation with the required tools.</p>
<h2>Run the installer</h2>
<p>Open a terminal and run the following exact commands.</p>
<pre><code class="language-powershell">$env:EXAMPLE_HOME='C:\\IBM\\Example'
example install --accept-license</code></pre>
<table><tr><th>Option</th><th>Meaning</th></tr><tr><td>--accept-license</td><td>Accept license</td></tr></table>
<a href="/docs/en/example/1.0?topic=verify">Verify the installation</a>
</main><footer>Footer</footer></body></html>
"""


def test_default_registry_enables_configured_public_target():
    registry = load_registry()
    target = get_enabled_target(registry, "ibm-mq", "latest")
    assert target.product_version == "9.4.x"
    assert target.sitemap_url.endswith("/SSFKSJ_9.4.0/0/sitemap.xml")


def test_registry_blocks_target_not_enabled_for_crawling(tmp_path: Path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        """
registry_version: '1'
products:
  - product_id: example
    product_name: IBM Example
    domain_id: ibm_products
    docs_path_prefix: /docs/en/example/1.0
    versions:
      - version_id: current
        product_version: '1.0'
        seed_url: https://www.ibm.com/docs/en/example/1.0?topic=start
        crawl_enabled: false
""",
        encoding="utf-8",
    )
    registry = load_registry(path)
    with pytest.raises(RegistryError, match="not enabled"):
        get_enabled_target(registry, "example", "current")


def test_url_scope_uses_path_boundary_and_keeps_topic():
    url = canonicalize_url(
        "http://ibm.com/docs/en/example/1.0/?utm_source=x&topic=install#step"
    )
    assert url == "https://www.ibm.com/docs/en/example/1.0?topic=install"
    assert is_in_target_scope(url, "/docs/en/example/1.0")
    assert not is_in_target_scope(
        "https://www.ibm.com/docs/en/example/1.01?topic=install",
        "/docs/en/example/1.0",
    )
    with pytest.raises(ValueError):
        validate_ibm_docs_url("https://evil.example/docs/en/example")


def test_topic_dropping_redirect_is_skipped():
    assert _topic_redirect_was_lost(
        "https://www.ibm.com/docs/en/example/1.0?topic=obsolete",
        "https://www.ibm.com/docs/en/example/1.0",
    )
    assert not _topic_redirect_was_lost(
        "https://www.ibm.com/docs/en/example/1.0?topic=current",
        "https://www.ibm.com/docs/en/example/1.0?topic=current",
    )
    assert _is_nonfatal_extraction_error(
        ExtractionError("extracted content is suspiciously short")
    )


def test_extractor_preserves_commands_tables_sections_and_links():
    document = extract_document(
        HTML,
        requested_url=_target().seed_url,
        final_url=_target().seed_url,
        http_status=200,
        target=_target(),
    )
    assert document.title == "Install IBM Example"
    code = next(block for block in document.blocks if block.kind == "code")
    assert code.text.startswith("```powershell")
    assert "example install --accept-license" in code.text
    assert any(block.kind == "table" for block in document.blocks)
    assert document.links == ["https://www.ibm.com/docs/en/example/1.0?topic=verify"]
    chunks = chunk_pages(to_parse_result(document).pages)
    assert any("example install --accept-license" in chunk.text for chunk in chunks)
    assert any("Run the installer" in chunk.section_path for chunk in chunks)
    assert all("Navigation" not in block.text for block in document.blocks)
    assert all("Footer" not in block.text for block in document.blocks)


def test_extractor_prefers_semantic_main_over_large_page_chrome():
    chrome = " ".join(f"Navigation item {index}" for index in range(100))
    html = f"""
    <html><head><title>Fallback</title></head><body>
    <nav>{chrome}</nav>
    <main><h1>Actual topic</h1><p>{'Documented product details. ' * 10}</p></main>
    <footer>{chrome}</footer>
    </body></html>
    """.encode()
    document = extract_document(
        html,
        requested_url=_target().seed_url,
        final_url=_target().seed_url,
        http_status=200,
        target=_target(),
    )
    assert document.title == "Actual topic"
    assert all("Navigation item" not in block.text for block in document.blocks)


def test_fetcher_revalidates_redirects_and_bounds_response():
    policy = policy_from_text("User-agent: *\nAllow: /docs/\n", "Crawler/1 contact@example.test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("topic") == "start":
            return httpx.Response(302, headers={"location": "?topic=next"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"ok")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    settings = FetchSettings(
        user_agent="Crawler/1 contact@example.test",
        delay_seconds=1,
        max_retries=1,
        max_response_bytes=10,
        validate_public_dns=False,
    )
    fetcher = PoliteFetcher(policy, settings, client=client, sleep=lambda _seconds: None)
    result = fetcher.fetch(_target().seed_url)
    assert result.status_code == 200
    assert result.final_url.endswith("?topic=next")

    big_client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 11))
    )
    too_big = PoliteFetcher(policy, settings, client=big_client, sleep=lambda _seconds: None)
    assert "exceeded" in (too_big.fetch(_target().seed_url).error or "")


def test_fetcher_does_not_follow_redirect_outside_product_scope():
    policy = policy_from_text("User-agent: *\nAllow: /docs/\n", "Crawler/1 contact@example.test")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={
            "location": "https://www.ibm.com/docs/en/different-product?topic=start"
        })

    fetcher = PoliteFetcher(
        policy,
        FetchSettings(
            user_agent="Crawler/1 contact@example.test",
            max_retries=1,
            validate_public_dns=False,
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _seconds: None,
    )
    result = fetcher.fetch(_target().seed_url, scope_prefix=_target().docs_path_prefix)
    assert "escaped" in (result.error or "")
    assert len(calls) == 1


def test_sitemap_gzip_is_detected_by_magic_bytes():
    xml = b"""<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
    <url><loc>https://www.ibm.com/docs/en/example/1.0?topic=start</loc></url></urlset>"""
    kind, entries = parse_sitemap(gzip.compress(xml))
    assert kind == "urlset"
    assert entries[0][0].endswith("?topic=start")


def test_sitemap_rejects_large_decompressed_payload():
    with pytest.raises(SitemapError, match="decompressed sitemap exceeded"):
        parse_sitemap(gzip.compress(b"x" * 1000), max_xml_bytes=100)


def test_robots_redirect_to_noncanonical_same_host_path_is_rejected():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(
            302,
            headers={"location": "https://www.ibm.com/docs/en/example"},
        )
    ))
    with pytest.raises(RobotsPolicyError, match="canonical URL"):
        load_robots_policy("Crawler/1 contact@example.test", client=client)


def test_storage_keeps_run_history_and_non_appending_artifacts(tmp_path: Path):
    storage = CrawlStorage(tmp_path)
    run_id = storage.start_run(_target())
    document = extract_document(
        HTML,
        requested_url=_target().seed_url,
        final_url=_target().seed_url,
        http_status=200,
        target=_target(),
    )
    chunks = chunk_pages(to_parse_result(document).pages)
    raw_path = storage.save_raw(run_id, document.document_id, HTML)
    storage.record_discovered(run_id, document.canonical_url)
    storage.stage_document(run_id, document, chunks, {"etag": "v1"}, raw_path)
    storage.finish_run(run_id, "STAGED", {"run_id": run_id, "status": "STAGED"})

    summary = storage.run_summary(run_id)
    assert summary["page_statuses"] == {"STAGED": 1}
    artifacts = list(storage.iter_staged_artifacts(run_id))
    assert len(artifacts) == 1
    assert len(artifacts[0][1]) == len(chunks)
    assert storage.cache_headers(document.canonical_url) == {"If-None-Match": "v1"}


def test_storage_records_nonfatal_skipped_page(tmp_path: Path):
    storage = CrawlStorage(tmp_path)
    run_id = storage.start_run(_target())
    storage.record_discovered(run_id, _target().seed_url)
    storage.mark_skipped(run_id, _target().seed_url, "obsolete topic", http_status=200)
    storage.finish_run(run_id, "STAGED", {"status": "STAGED"})
    assert storage.run_summary(run_id)["page_statuses"] == {"SKIPPED": 1}


def test_unchanged_page_without_prior_artifacts_fails_closed(tmp_path: Path):
    storage = CrawlStorage(tmp_path)
    run_id = storage.start_run(_target())
    storage.record_discovered(run_id, _target().seed_url)
    storage.mark_unchanged(run_id, _target().seed_url)
    storage.finish_run(run_id, "STAGED", {"run_id": run_id, "status": "STAGED"})
    with pytest.raises(RuntimeError, match="no normalized artifacts"):
        list(storage.iter_staged_artifacts(run_id))


class _ExistingIndices:
    def exists(self, *, index: str) -> bool:
        return True


class _StagingClient:
    indices = _ExistingIndices()


def _staged_storage(tmp_path: Path) -> tuple[CrawlStorage, str]:
    storage = CrawlStorage(tmp_path)
    run_id = storage.start_run(_target())
    document = extract_document(
        HTML,
        requested_url=_target().seed_url,
        final_url=_target().seed_url,
        http_status=200,
        target=_target(),
    )
    chunks = chunk_pages(to_parse_result(document).pages)
    raw_path = storage.save_raw(run_id, document.document_id, HTML)
    storage.record_discovered(run_id, document.canonical_url)
    storage.stage_document(run_id, document, chunks, {}, raw_path)
    storage.finish_run(run_id, "STAGED", {"run_id": run_id, "status": "STAGED"})
    return storage, run_id


def test_promotion_validates_metadata_before_indexing(tmp_path: Path):
    storage, run_id = _staged_storage(tmp_path)
    invalid_target = replace(_target(), classification="secret")
    with pytest.raises(ValueError, match="Metadata invalid"):
        index_run_to_staging(
            storage,
            run_id,
            invalid_target,
            chunks_index="knowledge_chunks_staging_v2",
            docs_index="knowledge_documents_staging_v2",
            opensearch_client=_StagingClient(),
            embedding_fn=lambda _text: [0.0] * 768,
        )


def test_promotion_indexes_only_after_metadata_preflight(tmp_path: Path, monkeypatch):
    storage, run_id = _staged_storage(tmp_path)
    calls = []

    def fake_index_document(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status="INDEXED")

    monkeypatch.setattr(promotion_module, "index_document", fake_index_document)
    report = index_run_to_staging(
        storage,
        run_id,
        _target(),
        chunks_index="knowledge_chunks_staging_v2",
        docs_index="knowledge_documents_staging_v2",
        opensearch_client=_StagingClient(),
        embedding_fn=lambda _text: [0.0] * 768,
    )
    assert report["status"] == "INDEXED_STAGING"
    assert len(calls) == 1


def test_promotion_rejects_production_index_names():
    with pytest.raises(ValueError, match="contain 'staging'"):
        index_run_to_staging(
            None,
            "run-1",
            _target(),
            chunks_index="knowledge_chunks_v2",
            docs_index="knowledge_documents_v2",
            opensearch_client=None,
            embedding_fn=None,
        )


def test_promotion_rejects_partial_run():
    class PartialStorage:
        def run_summary(self, _run_id):
            return {
                "product_id": "example",
                "version_id": "1.0",
                "status": "PARTIAL",
                "page_statuses": {"FAILED": 1},
            }

    with pytest.raises(ValueError, match="fully successful STAGED"):
        index_run_to_staging(
            PartialStorage(),
            "run-1",
            _target(),
            chunks_index="knowledge_chunks_staging_v2",
            docs_index="knowledge_documents_staging_v2",
            opensearch_client=None,
            embedding_fn=None,
        )
