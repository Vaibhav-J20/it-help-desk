from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.ingestion.chunker import ChunkRecord
from app.ingestion.ibm_docs_crawler.catalog import MetadataCatalog
from app.ingestion.ibm_docs_crawler.models import FetchResult, SitemapEntry
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage
from app.ingestion.official_docs.discovery import parse_llms_index, parse_source_sitemap
from app.ingestion.official_docs.extractor import (
    extract_html_document,
    extract_markdown_document,
)
from app.ingestion.official_docs.registry import (
    OfficialSourceTarget,
    get_enabled_sources,
    load_official_source_registry,
)
from app.ingestion.ibm_docs_crawler.registry import (
    get_enabled_target,
    load_registry,
)
from app.retrieval.adaptive_router import AdaptiveRetrievalRouter, _rank_live_candidates
from app.retrieval.catalog_selector import CatalogCandidateSelector
from app.retrieval.live_docs import LiveRetrievalResult
from app.ingestion.official_docs.urls import canonicalize_source_url
from app.retrieval.live_docs import LiveDocsSettings, LiveDocumentArtifact
from app.retrieval.live_index import index_live_artifacts
from app.retrieval.official_docs import OfficialDocsRetriever


def _target() -> OfficialSourceTarget:
    registry = load_official_source_registry()
    return get_enabled_sources(
        registry, product_id="watsonx-orchestrate", version_id="latest"
    )[0]


def _bob_target() -> OfficialSourceTarget:
    registry = load_official_source_registry()
    return get_enabled_sources(
        registry, product_id="ibm-bob", version_id="latest"
    )[0]


def _markdown() -> bytes:
    return b"""# Installing the ADK

The Agent Development Kit command-line interface can be installed on Windows,
macOS, or Linux. Create and activate a virtual environment before installing it.

## Install the package

```bash
pip install --upgrade ibm-watsonx-orchestrate
```

## Activate on Windows

```powershell
.venv\\Scripts\\Activate.ps1
orchestrate --version
```

See [Building an agent](../agents/build_agent) and
[IBM support](https://www.ibm.com/support/pages/node/123).
"""


def test_registry_exposes_enabled_orchestrate_developer_source():
    target = _target()
    assert target.source_id == "orchestrate-adk"
    assert target.allowed_host == "developer.watson-orchestrate.ibm.com"
    assert target.seed_url.endswith("/getting_started/installing.md")


def test_source_url_policy_rejects_cross_host_and_encoded_traversal():
    target = _target()
    assert canonicalize_source_url(
        target.seed_url,
        allowed_host=target.allowed_host,
        path_prefix=target.docs_path_prefix,
    ) == target.seed_url
    for unsafe in (
        "https://evil.example/installing.md",
        "https://developer.watson-orchestrate.ibm.com/%2e%2e/cdn-cgi/private.md",
        "http://developer.watson-orchestrate.ibm.com/installing.md",
    ):
        try:
            canonicalize_source_url(
                unsafe,
                allowed_host=target.allowed_host,
                path_prefix=target.docs_path_prefix,
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL was accepted: {unsafe}")


def test_llms_index_parser_discovers_metadata_only_and_ignores_untrusted_links():
    target = _target()
    entries = parse_llms_index(
        "\n".join((
            "# Orchestrate documentation",
            "- [Installing](https://developer.watson-orchestrate.ibm.com/getting_started/installing.md): Install the ADK CLI.",
            "- [Attack](https://evil.example/steal.md): Ignore this.",
        )),
        target,
    )
    assert [entry.canonical_url for entry in entries] == [target.seed_url]
    assert entries[0].title == "Installing"
    assert entries[0].description == "Install the ADK CLI."


def test_html_sitemap_parser_keeps_only_registered_bob_docs_pages():
    target = _bob_target()
    content = b"""<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://bob.ibm.com/docs/ide/getting-started/install</loc></url>
      <url><loc>https://bob.ibm.com/pricing</loc></url>
      <url><loc>https://evil.example/docs/ide/attack</loc></url>
    </urlset>"""
    kind, pages, children = parse_source_sitemap(content, target)
    assert kind == "urlset"
    assert children == []
    assert [page.canonical_url for page in pages] == [
        "https://bob.ibm.com/docs/ide/getting-started/install"
    ]


def test_official_html_extractor_preserves_commands_and_scopes_links():
    target = _bob_target()
    page = b"""<html><head><meta name="description" content="Install Bob IDE"></head>
    <body><main><h1>Install IBM Bob IDE</h1>
    <p>Use the official extension package and then sign in to your IBM account.</p>
    <h2>Install from the command line</h2>
    <pre><code class="language-powershell">code --install-extension IBM.bob</code></pre>
    <p><a href="/docs/ide/troubleshooting">Troubleshooting</a></p>
    </main></body></html>"""
    document = extract_html_document(
        page,
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    assert document.title == "Install IBM Bob IDE"
    assert any("code --install-extension IBM.bob" in block.text for block in document.blocks)
    assert document.links == ["https://bob.ibm.com/docs/ide/troubleshooting"]
    assert document.metadata["source_id"] == "bob-docs"


def test_official_html_extractor_preserves_carbon_cards_and_accordion_titles():
    target = _bob_target()
    page = b"""<html><body><main><h1>IBM product family</h1>
    <h2>Data and analytics</h2>
    <h3><button><span>IBM watsonx.data</span></button></h3>
    <p>Prepare and integrate trusted data for analytics and AI applications.</p>
    <h2>AI assistants and agents</h2>
    <c4d-card-group>
      <a href="/docs/ide/orchestrate"><c4d-card-group-item>
        <c4d-card-heading role="heading" aria-level="3">watsonx Orchestrate</c4d-card-heading>
        <div>Create and manage AI assistants and agents across workflows.</div>
      </c4d-card-group-item></a>
      <a href="/docs/ide/bob"><c4d-card-group-item>
        <c4d-card-heading role="heading" aria-level="3">IBM Bob</c4d-card-heading>
        <div>An AI coding agent with deep codebase context for development tasks.</div>
      </c4d-card-group-item></a>
    </c4d-card-group></main></body></html>"""
    document = extract_html_document(
        page,
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    paths = {" > ".join(block.heading_path) for block in document.blocks}
    text = "\n".join(block.text for block in document.blocks)
    assert any("IBM watsonx.data" in path for path in paths)
    assert any("watsonx Orchestrate" in path for path in paths)
    assert any("IBM Bob" in path for path in paths)
    assert "Create and manage AI assistants" in text
    assert "deep codebase context" in text


def test_official_html_extractor_preserves_ibm_product_catalog_results():
    target = _bob_target()
    page = b"""<html><body><main><h1>IBM Products</h1>
    <h2>Product Categories</h2>
    <p>Artificial intelligence, Data and analytics, Security, Storage, Compute.</p>
    <div data-slot="result-summary"><span data-count-total="827">1 - 30 of 827 items</span></div>
    <div class="ibm-search__results">
      <div class="ibm-search__results__card" role="region" aria-label="IBM Example">
        <a href="/docs/ide/example"><div class="bx--card__heading">IBM Example</div>
        <div class="bx--card__copy">An example IBM software product.</div></a>
      </div>
    </div></main></body></html>"""
    document = extract_html_document(
        page,
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    text = "\n".join(block.text for block in document.blocks)
    paths = {" > ".join(block.heading_path) for block in document.blocks}
    assert "1 - 30 of 827 items" in text
    assert "An example IBM software product" in text
    assert any("IBM Example" in path for path in paths)


def test_markdown_extractor_preserves_commands_and_classifies_links():
    target = _target()
    document = extract_markdown_document(
        _markdown(),
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    code = "\n".join(block.text for block in document.blocks if block.kind == "code")
    assert "pip install --upgrade ibm-watsonx-orchestrate" in code
    assert ".venv\\Scripts\\Activate.ps1" in code
    assert document.links == [
        "https://developer.watson-orchestrate.ibm.com/agents/build_agent.md"
    ]
    assert document.metadata["outgoing_ibm_links"] == [
        "https://www.ibm.com/support/pages/node/123"
    ]


def test_source_filtered_catalog_does_not_mix_ibm_docs_and_developer_docs(tmp_path: Path):
    target = _target()
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(
            target.seed_url,
            None,
            target.index_url,
            "Installing the ADK CLI",
            "Install using pip on Windows.",
        )
    ], source_id=target.source_id)
    assert catalog.search(
        "install CLI",
        product_id=target.product_id,
        version_id=target.version_id,
        source_ids=(target.source_id,),
    )
    assert catalog.search(
        "install CLI",
        product_id=target.product_id,
        version_id=target.version_id,
        source_ids=("ibm-docs",),
    ) == []


def test_catalog_prefers_generic_cli_install_over_unrequested_specializations(
    tmp_path: Path,
):
    target = _target()
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(
            target.seed_url, None, target.index_url, "Getting started with the ADK", ""
        ),
        SitemapEntry(
            "https://developer.watson-orchestrate.ibm.com/adk_extension/installing_adk_extension.md",
            None,
            target.index_url,
            "Installing the VS Code Orchestrate ADK extension",
            "",
        ),
        SitemapEntry(
            "https://developer.watson-orchestrate.ibm.com/mcp_server/wxOmcp_installation.md",
            None,
            target.index_url,
            "Installing the watsonx Orchestrate ADK MCP Server",
            "",
        ),
    ], source_id=target.source_id)
    selector = CatalogCandidateSelector(catalog)
    generic = selector.select(
        "Install the Orchestrate ADK CLI on Windows and give me the commands",
        target,
        limit=1,
        source_ids=(target.source_id,),
    )
    assert generic[0].canonical_url == target.seed_url
    extension = selector.select(
        "Install the Orchestrate ADK VS Code extension",
        target,
        limit=1,
        source_ids=(target.source_id,),
    )
    assert "adk_extension/installing_adk_extension.md" in extension[0].canonical_url


def test_product_alias_terms_do_not_crowd_out_exact_verify_deployment_page(
    tmp_path: Path,
):
    target = get_enabled_sources(
        load_official_source_registry(),
        product_id="security-verify-access",
        version_id="latest",
    )[0]
    catalog = MetadataCatalog(tmp_path)
    entries = [
        SitemapEntry(
            f"https://docs.verify.ibm.com/ibm-security-verify-access/reference/api-{index}.md",
            None,
            target.index_url,
            f"IBM Verify Identity Access API endpoint {index}",
            "Authorize access and return required identity fields.",
        )
        for index in range(40)
    ]
    entries.append(SitemapEntry(
        "https://docs.verify.ibm.com/ibm-security-verify-access/docs/deployment-openshift.md",
        None,
        target.index_url,
        "Red Hat OpenShift deployment",
        "Deploy the runtime on OpenShift with commands and templates.",
    ))
    catalog.upsert_discovered(target, entries, source_id=target.source_id)
    selected = CatalogCandidateSelector(catalog).select(
        "Deploy IBM Verify Identity Access on OpenShift with commands",
        target,
        limit=1,
        source_ids=(target.source_id,),
    )
    assert selected[0].canonical_url.endswith("/deployment-openshift.md")


def test_cross_source_catalog_prefers_adk_cli_page_over_product_install_page(
    tmp_path: Path,
):
    ibm_target = get_enabled_target(load_registry(), "watsonx-orchestrate", "latest")
    source_target = _target()
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(ibm_target, [
        SitemapEntry(
            "https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=notes-installing-watsonx-orchestrate-premises",
            None,
            ibm_target.sitemap_url,
            "Installing on IBM watsonx Orchestrate On-premises",
            "",
        )
    ])
    catalog.upsert_discovered(source_target, [
        SitemapEntry(
            source_target.seed_url,
            None,
            source_target.index_url,
            "Getting started with the ADK",
            "",
        )
    ], source_id=source_target.source_id)
    page = CatalogCandidateSelector(catalog).select(
        "Install the watsonx Orchestrate ADK CLI on Windows with exact commands",
        ibm_target,
        limit=1,
        source_ids=("ibm-docs", source_target.source_id),
    )[0]
    assert page.source_id == source_target.source_id
    assert page.canonical_url == source_target.seed_url


def test_official_retriever_cold_then_warm_preserves_exact_command(tmp_path: Path):
    target = _target()
    catalog = MetadataCatalog(tmp_path)
    storage = CrawlStorage(tmp_path)
    catalog.upsert_discovered(target, [
        SitemapEntry(
            target.seed_url,
            None,
            target.index_url,
            "Installing the ADK CLI",
            "Install the Orchestrate ADK command-line interface on Windows.",
        )
    ], source_id=target.source_id)
    calls: list[str] = []

    def fetch_batch(requests):
        calls.extend(request.url for request in requests)
        return {
            request.url: FetchResult(
                request.url,
                request.url,
                200,
                {"content-type": "text/markdown", "etag": '"v1"'},
                _markdown(),
            )
            for request in requests
        }

    retriever = OfficialDocsRetriever(
        target,
        catalog,
        storage,
        LiveDocsSettings(
            user_agent="test@example.com",
            initial_pages=1,
            max_pages=1,
            related_depth=0,
            cache_ttl_seconds=3600,
        ),
        fetch_batch=fetch_batch,
    )
    cold = retriever.retrieve("How do I install the Orchestrate ADK CLI on Windows?")
    assert calls == [target.seed_url]
    assert cold.trace["network_fetches"] == 1
    assert any(
        "pip install --upgrade ibm-watsonx-orchestrate" in item["chunk_text"]
        for item in cold.candidates
    )

    calls.clear()
    warm = retriever.retrieve("How do I install the Orchestrate ADK CLI on Windows?")
    assert calls == []
    assert warm.trace["cache_hits"] == 1
    assert warm.candidates[0]["retrieval_origin"] == "persistent_cache"


def test_install_command_outranks_environment_configuration_command():
    target = _target()
    document = extract_markdown_document(
        _markdown(),
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    chunks = [
        ChunkRecord(
            0,
            "Use the ADK CLI.\n```bash\norchestrate env add -n dev -u https://example\n```",
            1,
            1,
            "Setting up and installing the ADK",
            "sha256:env",
            "test",
            20,
        ),
        ChunkRecord(
            1,
            "On Windows, install the package.\n```bash\npip install --upgrade ibm-watsonx-orchestrate\n```",
            1,
            1,
            "Setting up and installing the ADK",
            "sha256:install",
            "test",
            20,
        ),
    ]
    from app.retrieval.section_ranker import rank_artifact_chunks

    ranked = rank_artifact_chunks(
        "How do I install the Orchestrate ADK CLI on Windows?",
        [(document, chunks, "official_live_docs")],
        target,
        limit=2,
    )
    assert "pip install --upgrade" in ranked[0]["chunk_text"]


def test_adaptive_router_selects_command_rich_official_source(
    tmp_path: Path,
    monkeypatch,
):
    ibm_registry = load_registry()
    ibm_target = get_enabled_target(ibm_registry, "watsonx-orchestrate", "latest")
    source_registry = load_official_source_registry()
    source_target = _target()
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(ibm_target, [
        SitemapEntry(
            ibm_target.seed_url,
            None,
            ibm_target.sitemap_url,
            "Getting started with watsonx Orchestrate",
            "Product overview.",
        )
    ])
    catalog.upsert_discovered(source_target, [
        SitemapEntry(
            source_target.seed_url,
            None,
            source_target.index_url,
            "Installing the Orchestrate ADK CLI",
            "Install the Python package and activate it on Windows.",
        )
    ], source_id=source_target.source_id)
    called: list[str] = []

    class FakeRetriever:
        def __init__(self, target):
            self.target = target

        def retrieve_cached(self, _query):
            return []

        def retrieve(self, _query):
            source_id = getattr(self.target, "source_id", "ibm-docs")
            called.append(source_id)
            candidate = {
                "chunk_id": f"{source_id}:1",
                "title": "Installing the Orchestrate ADK CLI",
                "section_path": "Install the package on Windows",
                "chunk_text": "Run pip install --upgrade ibm-watsonx-orchestrate.",
                "product": "watsonx Orchestrate",
                "source_uri": self.target.seed_url,
            }
            return LiveRetrievalResult([candidate], [], {
                "network_fetches": 1,
                "cache_hits": 0,
                "failed_pages": 0,
            })

    monkeypatch.setenv("IBM_DOCS_USER_AGENT", "test@example.com")
    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_live_ibm_docs=True,
            enable_live_official_sources=True,
        ),
        catalog=catalog,
        storage=CrawlStorage(tmp_path),
        registry=ibm_registry,
        official_source_registry=source_registry,
        live_retriever_factory=lambda target, *_args, **_kwargs: FakeRetriever(target),
        official_retriever_factory=lambda target, *_args, **_kwargs: FakeRetriever(target),
    )
    result = router.retrieve(
        {
            "retrieval_query": "How do I install the Orchestrate ADK CLI on Windows?",
            "extracted_scope": {
                "domain_id": "watsonx_orchestrate",
                "product": "watsonx Orchestrate",
                "product_version": "current",
            },
        },
        indexed_retrieve=lambda: [],
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )
    assert called == ["orchestrate-adk"]
    assert result.trace["selected_stage"] == "official_live_docs"
    assert "ibm-watsonx-orchestrate" in result.candidates[0]["chunk_text"]


def test_cached_live_candidates_are_merged_by_comparable_section_score():
    ranked = _rank_live_candidates([
        {"chunk_id": "overview", "_live_score": 12.0},
        {"chunk_id": "exact-command", "_live_score": 31.5},
        {"chunk_id": "unscored"},
    ])
    assert [candidate["chunk_id"] for candidate in ranked] == [
        "exact-command",
        "overview",
        "unscored",
    ]


def test_adaptive_cache_returns_only_the_selected_confident_source(
    tmp_path: Path,
    monkeypatch,
):
    ibm_registry = load_registry()
    ibm_target = get_enabled_target(ibm_registry, "watsonx-orchestrate", "latest")
    source_registry = load_official_source_registry()
    source_target = _target()
    catalog = MetadataCatalog(tmp_path)
    catalog.upsert_discovered(ibm_target, [
        SitemapEntry(
            ibm_target.seed_url,
            None,
            ibm_target.sitemap_url,
            "Building a custom API client",
            "Write a custom client application.",
        )
    ])
    catalog.upsert_discovered(source_target, [
        SitemapEntry(
            source_target.seed_url,
            None,
            source_target.index_url,
            "Getting started with the ADK",
            "Install the ADK CLI package on Windows.",
        )
    ], source_id=source_target.source_id)

    class FakeRetriever:
        def __init__(self, target):
            self.target = target

        def retrieve_cached(self, _query):
            source_id = getattr(self.target, "source_id", "ibm-docs")
            if source_id == "orchestrate-adk":
                return [{
                    "chunk_id": "official-install",
                    "title": "Getting started with the ADK",
                    "section_path": "Installing the ADK on Windows",
                    "chunk_text": "pip install --upgrade ibm-watsonx-orchestrate",
                    "product": "watsonx Orchestrate",
                    "source_uri": self.target.seed_url,
                    "source_id": source_id,
                    "source_type": "official_product_docs",
                    "_live_score": 40.0,
                }]
            return [{
                "chunk_id": "ibm-custom-client",
                "title": "Building a custom API client",
                "section_path": "Client loop",
                "chunk_text": "Run the custom client command in Python.",
                "product": "watsonx Orchestrate",
                "source_uri": self.target.seed_url,
                "source_id": source_id,
                "_live_score": 35.0,
            }]

        def retrieve(self, _query):
            raise AssertionError("confident selected cache should avoid live retrieval")

    monkeypatch.setenv("IBM_DOCS_USER_AGENT", "test@example.com")
    router = AdaptiveRetrievalRouter(
        settings=Settings(
            _env_file=None,
            enable_live_ibm_docs=True,
            enable_live_official_sources=True,
        ),
        catalog=catalog,
        storage=CrawlStorage(tmp_path),
        registry=ibm_registry,
        official_source_registry=source_registry,
        live_retriever_factory=lambda target, *_args, **_kwargs: FakeRetriever(target),
        official_retriever_factory=lambda target, *_args, **_kwargs: FakeRetriever(target),
    )
    result = router.retrieve(
        {
            "retrieval_query": "Install the Orchestrate ADK CLI on Windows",
            "extracted_scope": {
                "domain_id": "watsonx_orchestrate",
                "product": "watsonx Orchestrate",
                "product_version": "current",
            },
        },
        indexed_retrieve=lambda: (_ for _ in ()).throw(
            AssertionError("confident selected cache should avoid OpenSearch")
        ),
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
    )
    assert [candidate["chunk_id"] for candidate in result.candidates] == [
        "official-install"
    ]
    assert result.trace["selected_cache_source"] == "orchestrate-adk"


def test_live_indexing_requires_and_forwards_explicit_index_names(monkeypatch):
    target = _target()
    document = extract_markdown_document(
        _markdown(),
        requested_url=target.seed_url,
        final_url=target.seed_url,
        http_status=200,
        target=target,
    )
    chunk = ChunkRecord(
        0,
        "pip install --upgrade ibm-watsonx-orchestrate",
        1,
        1,
        "Installing the ADK",
        "sha256:chunk",
        "test",
        10,
    )
    captured = {}

    def fake_index_document(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="INDEXED")

    monkeypatch.setattr("app.retrieval.live_index.index_document", fake_index_document)
    report = index_live_artifacts(
        [LiveDocumentArtifact(document, [chunk], "official_live_docs")],
        target,
        opensearch_client=object(),
        embedding_fn=lambda _text: [0.0],
        chunks_index="knowledge_chunks_test_staging",
        docs_index="knowledge_documents_test_staging",
    )
    assert report["INDEXED"] == 1
    assert captured["chunks_index"] == "knowledge_chunks_test_staging"
    assert captured["docs_index"] == "knowledge_documents_test_staging"
    assert captured["metadata"]["source_type"] == "official_product_docs_live"
