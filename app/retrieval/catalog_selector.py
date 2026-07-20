"""Deterministic metadata candidate selection for IBM Documentation pages."""

from __future__ import annotations

from dataclasses import replace
import re

from app.ingestion.ibm_docs_crawler.catalog import CatalogPage, MetadataCatalog
from app.ingestion.ibm_docs_crawler.registry import CrawlTarget

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]+", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "do", "does", "for", "how", "i", "in", "is",
    "it", "of", "on", "the", "to", "use", "using", "what", "when", "where",
    "which", "with",
})
_INTENT_TERMS: dict[str, tuple[str, ...]] = {
    "install": ("install", "setup", "getting-started", "prerequisite"),
    "configure": ("config", "setting", "customiz"),
    "troubleshoot": ("troubleshoot", "problem", "error", "diagnos", "recover"),
    "command": ("command", "cli", "shell", "powershell", "reference"),
    "upgrade": ("upgrade", "migrat", "update"),
}
_SPECIALIZED_FACETS: dict[str, tuple[str, ...]] = {
    "extension": ("extension", "vscode", "visual", "studio"),
    "mcp": ("mcp",),
    "developer-edition": ("developer", "edition"),
}
_FEATURE_TERMS = frozenset({
    "adk", "api", "cli", "command", "developer", "extension", "ide", "mcp",
    "powershell", "sdk", "shell", "toolkit", "vscode",
})
_PLATFORM_TERMS = frozenset({"linux", "macos", "openshift", "powershell", "windows"})
_OVERVIEW_FILLER_TERMS = frozenset({
    "about", "brief", "description", "describe", "explain", "give", "introduction",
    "me", "ok", "overview", "platform", "product", "software", "summary", "tell",
})


class CatalogCandidateSelector:
    def __init__(self, catalog: MetadataCatalog) -> None:
        self.catalog = catalog

    def select(
        self,
        query: str,
        target: CrawlTarget,
        *,
        limit: int,
        search_limit: int = 30,
        source_ids: tuple[str, ...] | None = None,
    ) -> list[CatalogPage]:
        ranking_query = _without_product_terms(query, target)
        overview_query = _is_product_overview_query(ranking_query)
        search_query = _catalog_search_query(ranking_query)
        catalog_product_id = target.run_context.get(
            "catalog_product_id", target.product_id
        )
        catalog_version_id = target.run_context.get(
            "catalog_version_id", target.version_id
        )
        pages = self.catalog.search(
            search_query,
            product_id=catalog_product_id,
            version_id=catalog_version_id,
            limit=max(limit, search_limit),
            source_ids=source_ids,
        )
        # Product-summary questions should start from the canonical product
        # landing/overview page even when generic prose ("brief description")
        # happens to match child pages more strongly in FTS. Feature-specific
        # questions retain the normal topic ranking below.
        if overview_query:
            seed = self.catalog.get_page(target.seed_url)
            if seed is not None and (
                not source_ids or seed.source_id in source_ids
            ):
                pages = [seed, *(
                    page for page in pages
                    if page.canonical_url != seed.canonical_url
                )]
        if not pages:
            seed_source = source_ids[0] if source_ids and len(source_ids) == 1 else "ibm-docs"
            self.catalog.ensure_seed(target, source_id=seed_source)
            seed = self.catalog.get_page(target.seed_url)
            pages = [seed] if seed is not None else []
        ranked = [
            replace(page, relevance_score=self.score(ranking_query, page))
            for page in pages
        ]
        if overview_query and ranked:
            ranked = [
                replace(page, relevance_score=page.relevance_score + 20.0)
                if page.canonical_url == target.seed_url else page
                for page in ranked
            ]
        ranked.sort(key=lambda page: (-page.relevance_score, page.canonical_url))
        return ranked[:max(1, limit)]

    @staticmethod
    def score(query: str, page: CatalogPage) -> float:
        lowered = re.sub(r"\busecases?\b", "use cases", query.lower())
        haystack = " ".join((
            page.title,
            page.description,
            page.topic_slug.replace("-", " ").replace("_", " "),
            " ".join(page.breadcrumbs),
            page.canonical_url,
        )).lower()
        tokens = [
            _normalize_token(token)
            for token in dict.fromkeys(_WORD_RE.findall(lowered))
            if token not in _STOP_WORDS
        ]
        haystack_tokens = {_normalize_token(token) for token in _WORD_RE.findall(haystack)}
        matched = sum(1 for token in tokens if _token_matches(token, haystack_tokens))
        score = page.relevance_score + (matched / max(1, len(tokens))) * 8.0
        for intent, route_terms in _INTENT_TERMS.items():
            if intent in tokens and any(
                _token_matches(term, haystack_tokens) for term in route_terms
            ):
                score += 5.0
        if "use" in tokens and "case" in tokens and (
            "use case" in haystack or "use cases" in haystack
        ):
            score += 8.0
        # An installation question asking for commands normally needs the
        # installation procedure itself, even when llms.txt titles that page
        # "Getting started". The URL slug supplies the missing semantic cue.
        install_query = "install" in tokens
        command_query = "command" in tokens or "cli" in tokens
        if install_query and command_query and any(
            _token_matches(term, haystack_tokens)
            for term in _INTENT_TERMS["install"]
        ):
            score += 4.0
        if install_query and any(term in haystack_tokens for term in (
            "administer", "administration", "deployment", "overview",
        )):
            score += 8.0
        # Avoid drifting into a specialized installation path unless the user
        # named that facet (VS Code extension, MCP server, Developer Edition).
        query_words = {_normalize_token(token) for token in _WORD_RE.findall(lowered)}
        for facet, terms in _SPECIALIZED_FACETS.items():
            required = 2 if facet == "developer-edition" else 1
            haystack_matches = sum(
                _token_matches(term, haystack_tokens) for term in terms
            )
            if haystack_matches < required:
                continue
            query_matches = sum(_token_matches(term, query_words) for term in terms)
            if query_matches < required:
                score -= 6.0
        if page.title and page.title.lower() in lowered:
            score += 3.0
        return score


def _without_product_terms(query: str, target: CrawlTarget) -> str:
    product_terms = {
        token.lower()
        # Product aliases often contain the exact user-facing product name
        # ("IBM Verify Identity Access"). Removing those terms prevents them
        # from crowding the FTS shortlist. Preserve explicit feature terms so
        # aliases such as "orchestrate adk" do not erase the requested ADK.
        for value in (target.product_name, target.product_id, *target.aliases)
        for token in _TOKEN_RE.findall(value)
        if token.lower() not in _FEATURE_TERMS
    }
    retained = [
        _normalize_token(token)
        for token in _TOKEN_RE.findall(query)
        if token.lower() not in product_terms
    ]
    return " ".join(retained) or query


def _catalog_search_query(ranking_query: str) -> str:
    """Keep generic prose words from dominating the metadata FTS shortlist."""
    tokens = [_normalize_token(token) for token in _TOKEN_RE.findall(ranking_query)]
    if "install" not in tokens:
        return ranking_query
    focused = ["install"]
    focused.extend(
        token for token in tokens
        if token in (_FEATURE_TERMS | _PLATFORM_TERMS) and token not in focused
    )
    return " ".join(focused)


def _is_product_overview_query(ranking_query: str) -> bool:
    """Return true only for broad product-description requests.

    Product names have already been removed from ``ranking_query``. Therefore
    an empty set of meaningful terms represents questions such as "What is
    IBM Instana?", while a term such as ``agent`` or ``install`` keeps the
    query on normal topic-level ranking.
    """
    tokens = {
        _normalize_token(token)
        for token in _WORD_RE.findall(ranking_query)
        if token.lower() not in _STOP_WORDS
    }
    return not tokens or tokens.issubset(_OVERVIEW_FILLER_TERMS)


def is_product_overview_query(query: str, target: CrawlTarget) -> bool:
    """Public overview-intent predicate shared by page and chunk ranking."""
    return _is_product_overview_query(_without_product_terms(query, target))


def _normalize_token(token: str) -> str:
    lowered = token.lower()
    if len(lowered) > 6 and lowered.endswith("ing"):
        return lowered[:-3]
    if len(lowered) > 5 and lowered.endswith("ies"):
        return lowered[:-3] + "y"
    if len(lowered) > 4 and lowered.endswith("s") and not lowered.endswith("ss"):
        return lowered[:-1]
    return lowered


def _token_matches(token: str, words: set[str]) -> bool:
    normalized = _normalize_token(token)
    if len(normalized) <= 3:
        return normalized in words
    return any(word == normalized or word.startswith(normalized) for word in words)
