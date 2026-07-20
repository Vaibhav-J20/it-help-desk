"""Regression tests for bounded live-web retrieval and source attribution."""

from __future__ import annotations

from dataclasses import replace

from app.ingestion.ibm_docs_crawler.registry import CrawlTarget
from app.retrieval.adaptive_router import (
    _result_matches_target,
    _search_web_queries,
    _verified_web_product_version,
)
from app.retrieval.web_search import WebSearchResult, _select_relevant_content


def _target() -> CrawlTarget:
    return CrawlTarget(
        product_id="cloud-pak-data",
        product_name="IBM Cloud Pak for Data",
        domain_id="ibm_products",
        docs_path_prefix="/docs/en/cloud-paks/cp-data/5.4.x",
        aliases=("cloud pak for data", "cpd"),
        version_id="latest",
        product_version="5.4.x",
        seed_url="https://www.ibm.com/docs/en/cloud-paks/cp-data/5.4.x",
        max_pages=10,
        sitemap_url=None,
        run_context={"mode": "test"},
    )


def _result(name: str, *, snippet: str = "Official IBM product documentation.") -> WebSearchResult:
    return WebSearchResult(
        title=name,
        url=f"https://www.ibm.com/new/announcements/{name.casefold().replace(' ', '-')}",
        snippet=snippet,
        provider="test",
    )


def test_tavily_excerpt_places_exact_raw_section_before_long_generic_summary():
    generic = "Generic product overview. " * 200
    raw = (
        "# Overview\n\nGeneral security information.\n\n"
        "## Internal TLS certificate lifecycle\n\n"
        "The internal-tls certificates are refreshed one month before expiry."
    )

    excerpt = _select_relevant_content(
        "How are internal TLS certificates rotated before expiry?",
        generic,
        raw,
        max_chars=420,
    )

    assert excerpt.startswith("## Internal TLS certificate lifecycle")
    assert "refreshed one month before expiry" in excerpt


def test_web_query_results_are_interleaved_across_variants():
    class Provider:
        def search(self, query: str, *, max_results: int):
            prefix = "focused" if query == "focused" else "broad"
            return [_result(f"{prefix} {index}") for index in range(max_results)]

    results = _search_web_queries(
        Provider(), ["focused", "broad"], max_results=2
    )

    assert [item.title for item in results] == [
        "focused 0", "broad 0", "focused 1", "broad 1",
    ]


def test_failed_web_query_variant_keeps_other_successful_results():
    class Provider:
        def search(self, query: str, *, max_results: int):
            if query == "broken":
                raise RuntimeError("temporary provider failure")
            return [_result("usable result")]

    results = _search_web_queries(
        Provider(), ["usable", "broken"], max_results=2
    )

    assert [item.title for item in results] == ["usable result"]


def test_short_registry_alias_does_not_match_ordinary_prose():
    target = replace(
        _target(),
        product_id="websphere-application-server",
        product_name="IBM WebSphere Application Server",
        aliases=("was",),
    )
    unrelated = WebSearchResult(
        title="A release was announced",
        url="https://www.ibm.com/new/announcements/unrelated",
        snippet="This was released for another IBM product.",
        provider="test",
    )
    branded = WebSearchResult(
        title="IBM WAS release information",
        url="https://www.ibm.com/support/pages/ibm-was-release",
        snippet="IBM WAS administrators can review this release information.",
        provider="test",
    )

    assert not _result_matches_target(unrelated, target, "Show the release")
    assert _result_matches_target(branded, target, "Show the release")


def test_unresolved_target_requires_explicit_product_identity():
    concert = WebSearchResult(
        title="IBM Concert overview",
        url="https://www.ibm.com/products/concert",
        snippet="IBM Concert provides application management capabilities.",
        provider="test",
    )

    assert _result_matches_target(
        concert, None, "What is IBM Concert?", requested_product="IBM Concert"
    )
    assert not _result_matches_target(
        concert, None, "What is IBM Instana?", requested_product="IBM Instana"
    )


def test_web_version_is_attributed_only_from_source_evidence():
    future_releases = WebSearchResult(
        title="How to change the lifespan for internal-tls?",
        url="https://www.ibm.com/support/pages/how-change-lifespan-internal-tls",
        snippet=(
            "Product: IBM Cloud Pak for Data. Version 4.7.0 and future "
            "releases. Certificates are refreshed before expiry."
        ),
        provider="test",
    )
    older_only = WebSearchResult(
        title="Cloud Pak for Data 4.7 certificate procedure",
        url="https://www.ibm.com/support/pages/old-cpd-procedure",
        snippet="This manual procedure applies to Cloud Pak for Data version 4.7.0.",
        provider="test",
    )

    assert _verified_web_product_version(
        future_releases, _target(), "5.4"
    ) == ("5.4.x", "source-future-releases")
    assert _verified_web_product_version(
        older_only, _target(), "5.4"
    ) == ("4.7.0", "source-version-mismatch")
