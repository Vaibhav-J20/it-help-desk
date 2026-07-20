from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.ingestion.ibm_docs_crawler.catalog import CatalogTarget, MetadataCatalog
from app.ingestion.ibm_docs_crawler.models import FetchResult, SitemapEntry
from app.ingestion.ibm_docs_crawler.registry import CrawlTarget, Registry
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage
from app.retrieval.adaptive_router import (
    AdaptiveRetrievalRouter,
    _result_matches_target,
    _version_matches,
    _web_queries,
)
from app.retrieval.catalog_selector import CatalogCandidateSelector, _without_product_terms
from app.retrieval.live_docs import (
    LiveDocsRetriever,
    LiveDocsSettings,
    LiveRetrievalResult,
)
from app.retrieval.section_ranker import (
    candidate_set_is_confident,
    rank_artifact_chunks,
)
from app.retrieval.web_search import (
    HttpJsonWebSearchProvider,
    OpenAIResponsesWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchResult,
)
from app.ingestion.chunker import ChunkRecord
from app.ingestion.ibm_docs_crawler.models import ContentBlock, ExtractedDocument


def _target() -> CrawlTarget:
    return CrawlTarget(
        product_id="example",
        product_name="IBM Example",
        domain_id="ibm_products",
        docs_path_prefix="/docs/en/example/1.0",
        aliases=("example",),
        version_id="latest",
        product_version="1.0",
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=install",
        max_pages=10,
        sitemap_url="https://www.ibm.com/docs/en/example/sitemap.xml",
        run_context={"mode": "test"},
    )


def _registry() -> Registry:
    return Registry.model_validate({
        "registry_version": "test",
        "sitemap_url": "https://www.ibm.com/docs/en/sitemap.xml",
        "products": [{
            "product_id": "example",
            "product_name": "IBM Example",
            "domain_id": "ibm_products",
            "docs_path_prefix": "/docs/en/example/1.0",
            "aliases": ["example"],
            "max_pages": 10,
            "versions": [{
                "version_id": "latest",
                "product_version": "1.0",
                "seed_url": "https://www.ibm.com/docs/en/example/1.0?topic=install",
                "sitemap_url": "https://www.ibm.com/docs/en/example/sitemap.xml",
                "crawl_enabled": True,
            }],
        }],
    })


def _html(title: str, body: str, link: str = "") -> bytes:
    return f"""
    <html><body><main><h1>{title}</h1>
    <p>{body} {'Documented prerequisites and supported operating system details. ' * 3}</p>
    <h2>Run the command</h2><pre><code class="language-powershell">example install --accept-license</code></pre>
    {f'<a href="{link}">Verify installation</a>' if link else ''}
    </main></body></html>
    """.encode()


def test_catalog_search_and_graph_enrichment(tmp_path: Path):
    catalog = MetadataCatalog(tmp_path)
    target = _target()
    catalog.upsert_discovered(target, [
        SitemapEntry(
            "https://www.ibm.com/docs/en/example/1.0?topic=install-windows",
            "2026-07-01",
            target.sitemap_url,
        ),
        SitemapEntry(
            "https://www.ibm.com/docs/en/example/1.0?topic=troubleshooting-errors",
            None,
            target.sitemap_url,
        ),
    ])
    results = catalog.search(
        "install on windows", product_id="example", version_id="latest"
    )
    assert results[0].topic_slug == "install-windows"
    assert catalog.stats(product_id="example")["pages"] == 2


def test_live_retrieval_fetches_selected_pages_then_reuses_cache(tmp_path: Path):
    target = _target()
    catalog = MetadataCatalog(tmp_path)
    storage = CrawlStorage(tmp_path)
    verify_url = "https://www.ibm.com/docs/en/example/1.0?topic=verify"
    catalog.upsert_discovered(target, [
        SitemapEntry(target.seed_url, None, target.sitemap_url),
        SitemapEntry(verify_url, None, target.sitemap_url),
    ])
    calls: list[str] = []

    def fetch_batch(requests):
        output = {}
        for request in requests:
            calls.append(request.url)
            content = (
                _html("Install IBM Example", "Install the product on Windows.", verify_url)
                if request.url == target.seed_url
                else _html("Verify IBM Example", "Verify that the service is running.")
            )
            output[request.url] = FetchResult(
                requested_url=request.url,
                final_url=request.url,
                status_code=200,
                headers={"content-type": "text/html", "etag": '"v1"'},
                content=content,
            )
        return output

    retriever = LiveDocsRetriever(
        target,
        catalog,
        storage,
        LiveDocsSettings(
            user_agent="test@example.com",
            initial_pages=1,
            max_pages=2,
            related_depth=1,
            concurrency=2,
            cache_ttl_seconds=3600,
        ),
        fetch_batch=fetch_batch,
    )
    result = retriever.retrieve("Which command installs IBM Example on Windows?")
    assert len(calls) == 2
    assert any("example install --accept-license" in c["chunk_text"] for c in result.candidates)
    assert result.trace["network_fetches"] == 2
    assert catalog.neighbors(target.seed_url) == [verify_url]

    calls.clear()
    warm = retriever.retrieve("Which command installs IBM Example on Windows?")
    assert calls == []
    assert warm.trace["cache_hits"] == 2
    assert warm.candidates[0]["retrieval_origin"] == "persistent_cache"
    cached_artifacts = retriever.retrieve_cached_artifacts(
        "Which command installs IBM Example on Windows?"
    )
    assert cached_artifacts
    assert cached_artifacts[0].origin == "persistent_cache"


def test_live_retrieval_follows_catalog_backed_cross_product_edge(tmp_path: Path):
    target = _target()
    catalog = MetadataCatalog(tmp_path)
    storage = CrawlStorage(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(target.seed_url, None, target.sitemap_url),
    ])
    software_hub = CatalogTarget(
        content_key="SOFTHUB_1.0",
        product_id="ibmdocs-family-softhub",
        product_key="FAMILY_SOFTHUB",
        product_name="IBM Software Hub",
        product_family="SOFTHUB",
        product_url_key="software-hub",
        version_id="SOFTHUB_1.0",
        product_version="1.0",
        docs_path_prefix="/docs/en/software-hub/1.0",
        seed_url="https://www.ibm.com/docs/en/software-hub/1.0?topic=installing",
        sitemap_url="https://www.ibm.com/docs/en/SOFTHUB_1.0/0/sitemap.xml",
        aliases=("software hub",),
        last_modified=None,
        is_latest=True,
    )
    catalog.upsert_target(software_hub)
    raw_install_url = (
        "https://www.ibm.com/docs/SOFTHUB_1.0/hub/install/install.html"
    )
    calls: list[str] = []

    def fetch_batch(requests):
        output = {}
        for request in requests:
            calls.append(request.url)
            if request.url == target.seed_url:
                content = _html(
                    "Installing IBM Example",
                    "Installation is documented in IBM Software Hub.",
                    raw_install_url,
                )
                final_url = request.url
            else:
                content = _html(
                    "Installing IBM Software Hub",
                    "Install the platform on an OpenShift cluster with cpd-cli.",
                ).replace(
                    b"example install --accept-license",
                    b"cpd-cli manage install-components --release=1.0",
                )
                final_url = software_hub.seed_url
            output[request.url] = FetchResult(
                requested_url=request.url,
                final_url=final_url,
                status_code=200,
                headers={"content-type": "text/html"},
                content=content,
            )
        return output

    result = LiveDocsRetriever(
        target,
        catalog,
        storage,
        LiveDocsSettings(
            user_agent="test@example.com",
            initial_pages=1,
            max_pages=2,
            related_depth=1,
            concurrency=2,
        ),
        fetch_batch=fetch_batch,
    ).retrieve("What commands install IBM Example on OpenShift?")

    assert calls == [target.seed_url, raw_install_url]
    assert result.trace["related_hops"] == 1
    assert any(
        "cpd-cli manage install-components" in candidate["chunk_text"]
        for candidate in result.candidates
    )


def test_adaptive_router_checks_opensearch_before_answering_from_cache(tmp_path: Path):
    candidate = {
        "chunk_id": "cached-1",
        "title": "Install IBM Example",
        "chunk_text": "Use the example install command to install IBM Example.",
        "section_path": "Installation",
        "source_uri": _target().seed_url,
    }

    class FakeRetriever:
        def retrieve_cached(self, _query):
            return [candidate]

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        live_retriever_factory=lambda *_args, **_kwargs: FakeRetriever(),
    )
    indexed_called = False

    def indexed_retrieve():
        nonlocal indexed_called
        indexed_called = True
        return []

    result = router.retrieve(
        {
            "retrieval_query": "How do I install IBM Example?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=indexed_retrieve,
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )
    assert indexed_called
    assert result.candidates == [candidate]
    assert result.trace["selected_stage"] == "persistent_cache"


def test_adaptive_router_prefers_confident_opensearch_over_confident_cache(
    tmp_path: Path,
):
    cached = {
        "chunk_id": "cached-1",
        "title": "Install IBM Example",
        "chunk_text": "Use the cached example install command to install IBM Example.",
        "section_path": "Installation",
        "source_uri": _target().seed_url,
        "retrieval_origin": "persistent_cache",
    }
    indexed = {
        **cached,
        "chunk_id": "indexed-1",
        "chunk_text": "Use the indexed example install command to install IBM Example.",
        "retrieval_origin": "opensearch",
    }

    class FakeRetriever:
        def retrieve_cached(self, _query):
            return [cached]

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        live_retriever_factory=lambda *_args, **_kwargs: FakeRetriever(),
    )

    result = router.retrieve(
        {
            "retrieval_query": "How do I install IBM Example?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=lambda: [indexed],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.trace["selected_stage"] == "opensearch"
    assert result.candidates == [indexed]


def test_adaptive_router_uses_pydantic_ibm_docs_settings(tmp_path: Path):
    """FastAPI reads .env through Settings, so live config must not use os.getenv."""
    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            ibm_docs_user_agent="IBM-Docs-Test test@example.com",
            ibm_docs_data_dir=str(tmp_path),
            ibm_docs_delay_seconds=2.0,
            ibm_docs_validate_public_dns=False,
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
    )

    live = router._live_settings()
    assert live.user_agent == "IBM-Docs-Test test@example.com"
    assert live.delay_seconds == 2.0
    assert live.validate_public_dns is False


def test_dedicated_domain_never_falls_through_to_global_catalog(
    tmp_path: Path, monkeypatch,
):
    catalog = MetadataCatalog(tmp_path)

    def fail_global_resolution(*_args, **_kwargs):
        raise AssertionError("dedicated domain consulted the global product catalog")

    monkeypatch.setattr(catalog, "resolve_targets", fail_global_resolution)
    router = AdaptiveRetrievalRouter(
        settings=Settings(_env_file=None, ibm_docs_data_dir=str(tmp_path)),
        catalog=catalog,
        storage=CrawlStorage(tmp_path),
        registry=Registry.model_validate({
            "registry_version": "test",
            "sitemap_url": "https://www.ibm.com/docs/en/sitemap.xml",
            "products": [],
        }),
    )
    state = {
        "retrieval_query": "The SNO node rebooted; what should I check?",
        "extracted_scope": {"domain_id": "ocp_sno_support"},
    }

    assert router._target_for_state(state) is None
    assert router._metadata_candidates(state["retrieval_query"], state) == []


def test_registry_target_uses_global_catalog_identity_without_losing_label(
    tmp_path: Path,
):
    catalog = MetadataCatalog(tmp_path)
    global_target = CatalogTarget(
        content_key="EXAMPLE_1.0",
        product_id="ibmdocs-family-example",
        product_key="FAMILY_EXAMPLE",
        product_name="IBM Examples Example",
        product_family="EXAMPLE",
        product_url_key="example",
        version_id="EXAMPLE_1.0",
        product_version="1.0",
        docs_path_prefix="/docs/en/example/1.0",
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=overview",
        sitemap_url="https://www.ibm.com/docs/en/EXAMPLE_1.0/0/sitemap.xml",
        aliases=("example",),
        last_modified=None,
        is_latest=True,
    )
    install_url = (
        "https://www.ibm.com/docs/en/example/1.0?topic="
        "installing-administering-example"
    )
    component_url = (
        "https://www.ibm.com/docs/en/example/1.0?topic="
        "connectors-installing-remote"
    )
    catalog.upsert_target(global_target)
    catalog.upsert_global_discovered(global_target, [
        SitemapEntry(
            install_url,
            None,
            global_target.sitemap_url,
            title="Installing and administering IBM Example",
        ),
        SitemapEntry(
            component_url,
            None,
            global_target.sitemap_url,
            title="Installing remote connectors",
        ),
    ])
    router = AdaptiveRetrievalRouter(
        settings=Settings(_env_file=None, ibm_docs_data_dir=str(tmp_path)),
        catalog=catalog,
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
    )
    state = {
        "retrieval_query": "How do I install IBM Example on OpenShift?",
        "extracted_scope": {
            "domain_id": "ibm_products",
            "product": "IBM Example",
            "product_version": "1.0",
        },
    }

    runtime_target = router._target_for_state(state)
    assert isinstance(runtime_target, CrawlTarget)
    assert runtime_target.product_name == "IBM Example"
    assert runtime_target.seed_url == _target().seed_url
    assert runtime_target.run_context["catalog_product_id"] == global_target.product_id
    assert runtime_target.run_context["catalog_version_id"] == global_target.version_id
    pages = CatalogCandidateSelector(catalog).select(
        "What are the documented steps or commands to install IBM Example "
        "on OpenShift?",
        runtime_target,
        limit=1,
    )
    assert pages[0].canonical_url == install_url


def test_router_continues_to_live_docs_when_indexed_platform_is_wrong(tmp_path: Path):
    linux_candidate = {
        "chunk_id": "linux-indexed",
        "product": "IBM Example",
        "title": "Linux installation",
        "section_path": "Install on Linux",
        "chunk_text": "Install IBM Example on Linux or UNIX.",
        "source_uri": "https://www.ibm.com/docs/en/example/1.0?topic=linux-install",
        "_sources": ["bm25", "vector"],
    }
    windows_candidate = {
        "chunk_id": "windows-live",
        "product": "IBM Example",
        "title": "Windows installation",
        "section_path": "Install on Windows",
        "chunk_text": "Install IBM Example on a Windows server.",
        "source_uri": "https://www.ibm.com/docs/en/example/1.0?topic=windows-install",
        "retrieval_origin": "live_ibm_docs",
    }

    class FakeRetriever:
        def retrieve_cached(self, _query):
            return []

        def retrieve(self, _query):
            return LiveRetrievalResult(
                candidates=[windows_candidate],
                artifacts=[],
                trace={"network_fetches": 1},
            )

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=True,
            enable_live_official_sources=False,
            ibm_docs_user_agent="IBM-Docs-Test test@example.com",
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        live_retriever_factory=lambda *_args, **_kwargs: FakeRetriever(),
    )

    result = router.retrieve(
        {
            "retrieval_query": "How do I install IBM Example on Windows?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=lambda: [linux_candidate],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.candidates == [windows_candidate]
    assert result.trace["selected_stage"] == "live_ibm_docs"


def test_http_web_search_provider_rejects_non_allowlisted_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"results": [
            {
                "title": "IBM Docs result",
                "url": "https://www.ibm.com/docs/en/example/1.0?topic=install",
                "snippet": "Official IBM documentation explains the complete installation procedure.",
            },
            {
                "title": "Untrusted result",
                "url": "https://evil.example/install",
                "snippet": "This result is long enough but must never cross the configured domain boundary.",
            },
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = HttpJsonWebSearchProvider(
        "https://search.internal.example/query",
        allowed_domains=("ibm.com",),
        client=client,
    )
    results = provider.search("install IBM Example", max_results=5)
    assert [result.title for result in results] == ["IBM Docs result"]


def test_openai_web_search_forces_search_and_keeps_only_allowlisted_sources():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert body["tool_choice"] == "required"
        assert body["tools"][0]["type"] == "web_search"
        assert body["tools"][0]["external_web_access"] is True
        assert body["tools"][0]["filters"]["allowed_domains"] == ["ibm.com"]
        return httpx.Response(200, json={"output": [
            {
                "type": "web_search_call",
                "action": {"sources": [
                    {"url": "https://www.ibm.com/docs/en/example", "title": "IBM Docs"},
                    {"url": "https://evil.example/answer", "title": "Untrusted"},
                ]},
            },
            {
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": "The official IBM documentation describes the supported installation command and its prerequisites.",
                    "annotations": [],
                }],
            },
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAIResponsesWebSearchProvider(
        api_key="test-key",
        allowed_domains=("ibm.com",),
        client=client,
    )
    results = provider.search("install IBM Example", max_results=5)
    assert [result.url for result in results] == [
        "https://www.ibm.com/docs/en/example"
    ]
    assert results[0].provider == "openai-responses-web-search"


def test_tavily_web_search_restricts_request_and_filters_response():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-tavily-key"
        assert body["search_depth"] == "advanced"
        assert body["include_domains"] == ["ibm.com"]
        assert body["include_answer"] is False
        assert body["include_raw_content"] == "markdown"
        return httpx.Response(200, json={"results": [
            {
                "title": "IBM Concert overview",
                "url": "https://www.ibm.com/products/concert",
                "content": "IBM Concert provides application management capabilities described by IBM.",
                "raw_content": (
                    "# IBM Concert\n\nIBM Concert helps teams identify and "
                    "prioritize application risks.\n\n## Deployment\n\nFollow "
                    "the documented deployment workflow for your environment."
                ),
                "score": 0.91,
            },
            {
                "title": "Untrusted result",
                "url": "https://evil.example/concert",
                "content": "This result is long enough but must be rejected by the local allowlist.",
            },
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TavilyWebSearchProvider(
        api_key="test-tavily-key",
        allowed_domains=("ibm.com",),
        endpoint="https://api.tavily.com/search",
        client=client,
    )
    results = provider.search("What is IBM Concert?", max_results=5)

    assert [result.url for result in results] == [
        "https://www.ibm.com/products/concert"
    ]
    assert results[0].provider == "tavily-web-search"
    assert results[0].score == 0.91
    assert "prioritize application risks" in results[0].snippet


def test_web_query_variants_focus_event_and_certificate_lifecycle():
    event_queries = _web_queries(
        "What did IBM announce about IBM Example at Think 2026?",
        _target(),
        max_variants=2,
    )
    certificate_queries = _web_queries(
        "What commands rotate internal TLS certificates for IBM Example?",
        _target(),
        max_variants=2,
    )

    assert event_queries[0] == "IBM Think 2026 IBM Example announcement"
    assert certificate_queries[0].startswith("site:support.ibm.com")
    assert certificate_queries[0].endswith(
        "IBM Example internal-tls certificate lifespan"
    )


def test_version_family_matches_user_shorthand():
    assert _version_matches("5.4", "latest", "5.4.x")
    assert _version_matches("5.4.2", "5.4.x")
    assert not _version_matches("5.3", "5.4.x")


def test_router_resolves_product_alias_and_version_family(tmp_path: Path):
    registry = Registry.model_validate({
        "registry_version": "test",
        "sitemap_url": "https://www.ibm.com/docs/en/sitemap.xml",
        "products": [{
            "product_id": "cloud-pak-data",
            "product_name": "IBM Cloud Pak for Data",
            "domain_id": "ibm_products",
            "docs_path_prefix": "/docs/en/cloud-paks/cp-data/5.4.x",
            "aliases": ["cloud pak for data", "cpd"],
            "versions": [{
                "version_id": "latest",
                "product_version": "5.4.x",
                "seed_url": (
                    "https://www.ibm.com/docs/en/cloud-paks/cp-data/5.4.x"
                ),
                "crawl_enabled": True,
            }],
        }],
    })
    router = AdaptiveRetrievalRouter(
        settings=Settings(_env_file=None, ibm_docs_data_dir=str(tmp_path)),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=registry,
    )

    target = router._target_for_state({
        "retrieval_query": "Rotate Cloud Pak for Data 5.4 certificates",
        "extracted_scope": {
            "domain_id": "ibm_products",
            "product": "Cloud Pak for Data",
            "product_version": "5.4",
        },
    })

    assert target is not None
    assert target.product_id == "cloud-pak-data"
    assert target.product_version == "5.4.x"


def test_event_result_requires_exact_event_and_product_identity():
    question = "What did IBM announce about IBM Example at Think 2026?"
    exact = WebSearchResult(
        title="IBM Example at Think 2026",
        url="https://newsroom.ibm.com/2026-example",
        snippet="At Think 2026, IBM announced new IBM Example capabilities.",
        provider="test",
    )
    wrong_event = WebSearchResult(
        title="IBM Example release notes",
        url="https://www.ibm.com/new/announcements/example",
        snippet="IBM Example received a February 2026 maintenance update.",
        provider="test",
    )

    assert _result_matches_target(exact, _target(), question)
    assert not _result_matches_target(wrong_event, _target(), question)


def test_web_result_rejects_procedure_explicitly_limited_to_older_versions():
    target = replace(_target(), product_version="5.4.x")
    obsolete = WebSearchResult(
        title="Old certificate refresh issue",
        url="https://www.ibm.com/support/pages/old-refresh-issue",
        snippet=(
            "IBM Example users with expired certificates on versions lower "
            "than 4.5.0 must use this manual refresh procedure. The issue was "
            "fixed in version 4.5.0."
        ),
        provider="test",
    )

    assert not _result_matches_target(
        obsolete,
        target,
        "How do I rotate IBM Example 5.4 internal TLS certificates?",
    )


def test_product_overview_query_prioritizes_canonical_seed(tmp_path: Path):
    target = replace(
        _target(),
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=overview",
    )
    integration_url = (
        "https://www.ibm.com/docs/en/example/1.0?topic="
        "integrated-observability-products"
    )
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(
            target.seed_url, None, target.sitemap_url,
            "IBM Example overview", "Overview of the IBM Example product.",
        ),
        SitemapEntry(
            integration_url, None, target.sitemap_url,
            "Integrated products", "A brief description of product integrations.",
        ),
    ])

    selected = CatalogCandidateSelector(catalog).select(
        "Give me a brief description of IBM Example product",
        target,
        limit=2,
    )

    assert selected[0].canonical_url == target.seed_url


def test_product_overview_routing_does_not_override_feature_query(tmp_path: Path):
    target = replace(
        _target(),
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=overview",
    )
    feature_url = "https://www.ibm.com/docs/en/example/1.0?topic=agent-mode"
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(
            target.seed_url, None, target.sitemap_url,
            "IBM Example overview", "Overview of IBM Example.",
        ),
        SitemapEntry(
            feature_url, None, target.sitemap_url,
            "Agent mode", "Use Agent mode to run specialized agents.",
        ),
    ])

    selected = CatalogCandidateSelector(catalog).select(
        "What is Agent mode in IBM Example?",
        target,
        limit=1,
    )

    assert selected[0].canonical_url == feature_url


def test_router_uses_official_web_fallback_after_local_miss(tmp_path: Path):
    class FakeProvider:
        def search(self, query: str, *, max_results: int):
            assert "IBM Example" in query
            assert max_results == 5
            return [WebSearchResult(
                title="IBM Example overview",
                url="https://www.ibm.com/docs/en/example/1.0?topic=overview",
                snippet=(
                    "IBM Example is an official IBM product for observing and "
                    "managing example workloads with documented product features."
                ),
                provider="fake-official-search",
            )]

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            enable_live_official_sources=False,
            enable_live_web_search=True,
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        web_search_provider=FakeProvider(),
    )
    result = router.retrieve(
        {
            "retrieval_query": "Give me a brief description of IBM Example product",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=lambda: [],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.trace["selected_stage"] == "official_live_web"
    assert result.candidates[0]["retrieval_origin"] == "official_live_web"
    assert result.candidates[0]["web_search_provider"] == "fake-official-search"


def test_router_web_searches_when_product_has_no_registry_target(tmp_path: Path):
    class FakeProvider:
        def search(self, query: str, *, max_results: int):
            assert "IBM FutureProduct" in query
            return [WebSearchResult(
                title="IBM FutureProduct overview",
                url="https://www.ibm.com/products/future-product",
                snippet=(
                    "IBM FutureProduct is an official IBM offering described "
                    "on the IBM product website with current product details."
                ),
                provider="fake-official-search",
            )]

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            enable_live_official_sources=False,
            enable_live_web_search=True,
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        web_search_provider=FakeProvider(),
    )
    result = router.retrieve(
        {
            "retrieval_query": "What is IBM FutureProduct and what does it do?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM FutureProduct",
            },
        },
        indexed_retrieve=lambda: [],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.trace["target"] is None
    assert result.trace["selected_stage"] == "official_live_web"
    assert result.candidates[0]["source_uri"] == (
        "https://www.ibm.com/products/future-product"
    )


def test_current_announcement_bypasses_stale_index_and_promotes_web_result(
    tmp_path: Path,
):
    indexed = {
        "chunk_id": "old-think",
        "product": "IBM Example",
        "title": "THINK presentation",
        "section_path": "THINK",
        "chunk_text": "IBM announced an IBM Example update at Think 2025.",
        "retrieval_origin": "opensearch",
        "_sources": ["bm25", "vector"],
    }
    indexed_calls = []

    def stale_indexed_retrieve():
        indexed_calls.append(True)
        return [indexed]

    web = WebSearchResult(
        title="IBM Example at Think 2026",
        url="https://www.ibm.com/new/announcements/example-think-2026",
        snippet=(
            "IBM announced the current IBM Example capabilities at Think 2026 "
            "and described their availability."
        ),
        provider="fake-official-search",
    )

    class FakeProvider:
        def search(self, _query: str, *, max_results: int):
            assert max_results == 5
            return [web]

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            enable_live_official_sources=False,
            enable_live_web_search=True,
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        web_search_provider=FakeProvider(),
    )

    result = router.retrieve(
        {
            "retrieval_query": "What did IBM announce about IBM Example at Think 2026?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=stale_indexed_retrieve,
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.trace["freshness_required"] is True
    assert indexed_calls == []
    assert any(
        stage.get("stage") == "opensearch_skipped"
        for stage in result.trace["stages"]
    )
    assert result.trace["selected_stage"] == "official_live_web"
    assert result.candidates[0]["source_uri"] == web.url
    assert result.candidates[0]["retrieval_origin"] == "official_live_web"
    assert len(result.candidates) == 1


def test_portfolio_target_uses_exact_official_ibm_pages(tmp_path: Path):
    router = AdaptiveRetrievalRouter(
        settings=Settings(_env_file=None, ibm_docs_data_dir=str(tmp_path)),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
    )

    watsonx = router._target_for_state({
        "extracted_scope": {
            "domain_id": "ibm_products",
            "portfolio_family": "watsonx",
        }
    })
    ibm = router._target_for_state({
        "extracted_scope": {
            "domain_id": "ibm_products",
            "portfolio_family": "ibm",
        }
    })

    assert watsonx is not None
    assert watsonx.seed_url == "https://www.ibm.com/products/watsonx"
    assert watsonx.docs_path_prefix == "/products/watsonx"
    assert ibm is not None
    assert ibm.seed_url == "https://www.ibm.com/products"


def test_portfolio_confidence_rejects_one_product_and_accepts_family_evidence():
    question = "What are the watsonx products that IBM has to offer?"
    orchestrate_only = [{
        "chunk_id": "orchestrate-only",
        "product": "watsonx Orchestrate",
        "title": "Getting started with watsonx Orchestrate",
        "section_path": "Overview",
        "chunk_text": "watsonx Orchestrate creates and manages AI agents.",
    }]
    portfolio = [{
        "chunk_id": "watsonx-portfolio",
        "product": "IBM watsonx portfolio",
        "title": "IBM watsonx",
        "section_path": "Products",
        "chunk_text": (
            "The portfolio includes watsonx.ai, watsonx.data, "
            "watsonx.governance, watsonx Orchestrate, and watsonx BI."
        ),
    }]

    assert not candidate_set_is_confident(question, orchestrate_only)
    assert candidate_set_is_confident(question, portfolio)


def test_router_fetches_official_portfolio_after_wrong_single_product_hit(
    tmp_path: Path,
):
    official_candidate = {
        "chunk_id": "watsonx-portfolio",
        "document_id": "watsonx-portfolio-page",
        "domain_id": "ibm_products",
        "product": "IBM watsonx portfolio",
        "product_version": "current",
        "title": "IBM watsonx",
        "section_path": "Products",
        "source_uri": "https://www.ibm.com/products/watsonx",
        "chunk_text": (
            "IBM watsonx products include watsonx.ai, watsonx.data, "
            "watsonx.governance, watsonx Orchestrate, watsonx BI, and "
            "watsonx Code Assistant."
        ),
        "retrieval_origin": "official_live_docs",
    }

    class FakeRetriever:
        def retrieve_cached(self, _query):
            return []

        def retrieve(self, _query):
            return LiveRetrievalResult(
                candidates=[official_candidate],
                artifacts=[],
                trace={"network_fetches": 1},
            )

    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            enable_live_official_sources=True,
            ibm_docs_user_agent="IBM-Docs-Test test@example.com",
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
        official_retriever_factory=lambda *_args, **_kwargs: FakeRetriever(),
    )
    wrong_single_product = {
        **official_candidate,
        "chunk_id": "orchestrate-only",
        "product": "watsonx Orchestrate",
        "source_uri": "https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base",
        "chunk_text": "watsonx Orchestrate creates and manages AI agents.",
        "retrieval_origin": "opensearch",
    }

    result = router.retrieve(
        {
            "user_question": "What are the watsonx products that IBM has to offer?",
            "retrieval_query": "What are the watsonx products that IBM has to offer?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "portfolio_family": "watsonx",
            },
        },
        indexed_retrieve=lambda: [wrong_single_product],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.trace["selected_stage"] == "official_live_web"
    assert result.candidates[0]["retrieval_origin"] == "official_live_web"
    assert result.candidates[0]["web_search_provider"] == "ibm-official-portfolio"


def test_misconfigured_enabled_web_fallback_fails_closed(tmp_path: Path):
    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_adaptive_retrieval=True,
            enable_live_ibm_docs=False,
            enable_live_official_sources=False,
            enable_live_web_search=True,
            live_web_search_provider="http_json",
            live_web_search_endpoint="",
            ibm_docs_data_dir=str(tmp_path),
        ),
        catalog=MetadataCatalog(tmp_path),
        storage=CrawlStorage(tmp_path),
        registry=_registry(),
    )

    result = router.retrieve(
        {
            "retrieval_query": "Explain IBM Example observability",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "1.0",
            },
        },
        indexed_retrieve=lambda: [],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )

    assert result.candidates == []
    assert "LIVE_WEB_SEARCH_ENDPOINT is required" in result.trace["web_search_error"]


def test_command_boost_requires_non_product_intent_overlap():
    def document(title: str, url: str) -> ExtractedDocument:
        return ExtractedDocument(
            document_id=title.lower().replace(" ", "-"),
            canonical_url=url,
            requested_url=url,
            title=title,
            product_id="example",
            product_name="IBM Example",
            product_version="1.0",
            locale="en",
            blocks=[ContentBlock("paragraph", [title], "content")],
            links=[],
            content_hash="sha256:test",
            fetched_at="2026-07-15T00:00:00+00:00",
            http_status=200,
        )

    irrelevant = ChunkRecord(
        0, "```python\nprint('custom client')\n```", 1, 1,
        "Building a custom API client", "sha256:irrelevant", "test", 10,
    )
    relevant = ChunkRecord(
        0, "Run the ADK installation command from your terminal.", 1, 1,
        "Installing the ADK CLI", "sha256:relevant", "test", 10,
    )
    ranked = rank_artifact_chunks(
        "How do I install the IBM Example ADK CLI commands?",
        [
            (document("Custom client", _target().seed_url), [irrelevant], "cache"),
            (document("ADK installation", _target().seed_url), [relevant], "cache"),
        ],
        _target(),
        limit=2,
    )
    assert ranked[0]["section_path"] == "Installing the ADK CLI"


def test_overview_chunk_ranking_prefers_canonical_about_page():
    target = replace(
        _target(),
        seed_url="https://www.ibm.com/docs/en/example/1.0?topic=overview",
    )

    def document(title: str, url: str) -> ExtractedDocument:
        return ExtractedDocument(
            document_id=title.lower().replace(" ", "-"),
            canonical_url=url,
            requested_url=url,
            title=title,
            product_id="example",
            product_name="IBM Example",
            product_version="1.0",
            locale="en",
            blocks=[ContentBlock("paragraph", [title], "content")],
            links=[],
            content_hash="sha256:test",
            fetched_at="2026-07-15T00:00:00+00:00",
            http_status=200,
        )

    overview = ChunkRecord(
        0,
        "About IBM Example. It observes applications and helps teams understand service health.",
        1, 1, "About IBM Example", "sha256:overview", "test", 16,
    )
    integration = ChunkRecord(
        0,
        "A brief description of product integrations and shared navigation.",
        1, 1, "Integrated products", "sha256:integration", "test", 12,
    )
    ranked = rank_artifact_chunks(
        "Give me a brief description of IBM Example product",
        [
            (document("About IBM Example", target.seed_url), [overview], "cache"),
            (document(
                "Integrated products",
                "https://www.ibm.com/docs/en/example/1.0?topic=integrations",
            ), [integration], "cache"),
        ],
        target,
        limit=2,
    )

    assert ranked[0]["title"] == "About IBM Example"
    assert candidate_set_is_confident(
        "Give me a brief description of IBM Example product", ranked
    )


def test_product_identity_question_accepts_substantial_product_evidence():
    candidates = [{
        "chunk_id": "web-concert",
        "product": "IBM Concert",
        "title": "IBM Concert",
        "section_path": "Search result excerpt",
        "chunk_text": (
            "IBM Concert provides application management capabilities that "
            "help teams understand operational risk, prioritize issues, and "
            "coordinate remediation across their application environments."
        ),
        "source_uri": "https://www.ibm.com/products/concert",
        "retrieval_origin": "official_live_web",
        "web_search_provider": "tavily-web-search",
    }]

    assert candidate_set_is_confident("What is IBM Concert?", candidates)


def test_feature_term_in_product_alias_is_not_removed_from_query():
    target = replace(_target(), aliases=("example adk",))
    cleaned = _without_product_terms(
        "How do I install the IBM Example ADK CLI?", target
    )
    assert "adk" in cleaned
    assert "cli" in cleaned


def test_confidence_rejects_linux_evidence_for_explicit_windows_question():
    candidates = [{
        "chunk_id": "linux-1",
        "product": "IBM Guardium Data Protection",
        "title": "Linux-UNIX: Install and configure S-TAPs",
        "section_path": "Procedure",
        "chunk_text": "Install the Guardium S-TAP agent on Linux or UNIX.",
        "source_uri": "https://www.ibm.com/docs/en/gdp/12.x?topic=linux-install",
        "_sources": ["bm25", "vector"],
    }]

    assert not candidate_set_is_confident(
        "How to install Guardium on Windows?", candidates
    )


def test_confidence_accepts_windows_evidence_for_explicit_windows_question():
    candidates = [{
        "chunk_id": "windows-1",
        "product": "IBM Guardium Data Protection",
        "title": "Windows: Install S-TAP agents",
        "section_path": "Windows installation flow",
        "chunk_text": "Install the S-TAP agent on a Windows server.",
        "source_uri": (
            "https://www.ibm.com/docs/en/gdp/12.x?topic="
            "agent-windows-install-s-tap-agents-installation-flow"
        ),
        "_sources": ["bm25", "vector"],
    }]

    assert candidate_set_is_confident(
        "How to install Guardium on Windows?", candidates
    )


def test_confidence_requires_both_versions_for_comparison():
    question = "What changed in SNO installation between OCP 4.14 and OCP 4.16?"
    one_version = [{
        "chunk_id": "v416",
        "product": "OpenShift",
        "ocp_version": "4.16",
        "title": "SNO installation",
        "section_path": "Installation process",
        "chunk_text": "OpenShift SNO installation process and prerequisites.",
    }]
    both_versions = [
        *one_version,
        {
            **one_version[0],
            "chunk_id": "v414",
            "ocp_version": "4.14",
        },
    ]

    assert not candidate_set_is_confident(question, one_version)
    assert candidate_set_is_confident(question, both_versions)


def test_confidence_requires_exact_event_year():
    candidates = [{
        "chunk_id": "think-2025",
        "product": "watsonx Orchestrate",
        "title": "THINK presentation",
        "section_path": "Announcement",
        "chunk_text": (
            "IBM announced new watsonx Orchestrate capabilities at Think 2025."
        ),
        "_sources": ["bm25", "vector"],
    }]

    assert not candidate_set_is_confident(
        "What did IBM announce about watsonx Orchestrate at Think 2026?",
        candidates,
    )


def test_confidence_accepts_exact_event_despite_output_format_instructions():
    candidates = [{
        "chunk_id": "think-2026",
        "product": "watsonx Orchestrate",
        "title": "IBM announcements at Think 2026",
        "section_path": "Agentic Control Plane",
        "chunk_text": (
            "At Think 2026, IBM announced the next generation of watsonx "
            "Orchestrate as a unified agentic control plane for multi-agent "
            "orchestration and governance."
        ),
        "retrieval_origin": "official_live_web",
    }]

    assert candidate_set_is_confident(
        "What did IBM announce about watsonx Orchestrate at Think 2026? "
        "Use current official IBM sources and provide clickable URLs.",
        candidates,
    )


def test_confidence_rejects_tls_rotation_page_without_commands():
    candidates = [{
        "chunk_id": "tls-overview",
        "product": "Cloud Pak for Data",
        "product_version": "5.4.x",
        "title": "TLS certificate overview",
        "section_path": "Security",
        "chunk_text": (
            "Cloud Pak for Data uses internal TLS certificates and supports "
            "certificate rotation as part of security administration."
        ),
        "_sources": ["bm25", "vector"],
    }]

    assert not candidate_set_is_confident(
        "What are the documented steps and commands for rotating internal "
        "TLS certificates in Cloud Pak for Data 5.4.x?",
        candidates,
    )


def test_confidence_accepts_documented_automatic_certificate_renewal():
    candidates = [{
        "chunk_id": "tls-auto-renewal",
        "product": "Cloud Pak for Data",
        "product_version": "5.4.x",
        "title": "How to change the lifespan for internal-tls?",
        "section_path": "Summary",
        "chunk_text": (
            "The internal-tls certificate updates every 60 days and expires "
            "in 90 days. The renewal happens 30 days before expiry."
        ),
        "retrieval_origin": "official_live_web",
    }]

    assert candidate_set_is_confident(
        "What are the documented steps and commands for rotating internal "
        "TLS certificates in Cloud Pak for Data 5.4.x?",
        candidates,
    )


def test_confidence_accepts_passive_automatic_certificate_renewal_wording():
    candidates = [{
        "chunk_id": "tls-passive-auto-renewal",
        "product": "IBM Cloud Pak for Data",
        "product_version": "5.4.x",
        "title": "How to change the lifespan for internal-tls?",
        "section_path": "Question and answer",
        "chunk_text": (
            "The certificate named internal-tls is updated every 60 days and "
            "expires in 90 days. Renewal occurs 30 days before expiry."
        ),
        "retrieval_origin": "official_live_web",
    }]

    assert candidate_set_is_confident(
        "According to IBM Cloud Pak for Data 5.4.x documentation, what are "
        "the documented steps and commands for rotating internal TLS "
        "certificates?",
        candidates,
    )


def test_confidence_rejects_franken_evidence_across_unrelated_chunks():
    candidates = [
        {
            "chunk_id": "tls-overview",
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4.x",
            "title": "TLS certificate overview",
            "section_path": "Certificate rotation",
            "chunk_text": (
                "Cloud Pak for Data uses internal TLS certificates and "
                "supports certificate rotation."
            ),
        },
        {
            "chunk_id": "unrelated-command",
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4.x",
            "title": "Checking service status",
            "section_path": "Diagnostics",
            "chunk_text": "Run cpd-cli manage status to inspect service status.",
        },
    ]

    assert not candidate_set_is_confident(
        "What are the documented steps and commands for rotating internal "
        "TLS certificates in Cloud Pak for Data 5.4.x?",
        candidates,
    )


def test_confidence_rejects_inspection_command_as_rotation_procedure():
    candidates = [{
        "chunk_id": "tls-status-command",
        "product": "IBM Cloud Pak for Data",
        "product_version": "5.4.x",
        "title": "TLS certificate rotation",
        "section_path": "Diagnostics",
        "chunk_text": (
            "Internal TLS certificate rotation is part of administration. "
            "Run cpd-cli manage status to inspect the deployment."
        ),
    }]

    assert not candidate_set_is_confident(
        "What commands are used for rotating internal TLS certificates in "
        "Cloud Pak for Data 5.4.x?",
        candidates,
    )


def test_confidence_accepts_action_specific_rotation_command():
    candidates = [{
        "chunk_id": "tls-rotation-command",
        "product": "IBM Cloud Pak for Data",
        "product_version": "5.4.x",
        "title": "Rotating internal TLS certificates",
        "section_path": "Documented procedure and commands",
        "chunk_text": (
            "Use this documented step to rotate the internal TLS certificate:\n"
            "```bash\noc delete secret internal-tls -n cpd-instance\n```"
        ),
    }]

    assert candidate_set_is_confident(
        "What are the documented steps and commands for rotating internal "
        "TLS certificates in Cloud Pak for Data 5.4.x?",
        candidates,
    )


@pytest.mark.parametrize(
    ("question_verb", "evidence_verb"),
    [
        ("reveal", "unveiled"),
        ("introduce", "launched"),
        ("announce", "delivered"),
        ("expand", "expanded"),
    ],
)
def test_confidence_recognizes_think_announcement_synonyms(
    question_verb,
    evidence_verb,
):
    candidates = [{
        "chunk_id": f"think-2026-{question_verb}",
        "product": "watsonx Orchestrate",
        "title": "IBM at Think 2026",
        "section_path": "Agentic control plane",
        "chunk_text": (
            f"At Think 2026, IBM {evidence_verb} the next generation of "
            "watsonx Orchestrate as an agentic control plane."
        ),
        "retrieval_origin": "official_live_web",
    }]

    assert candidate_set_is_confident(
        f"What did IBM {question_verb} about watsonx Orchestrate at Think 2026?",
        candidates,
    )
