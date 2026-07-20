"""OpenSearch -> cache/metadata -> live docs -> web-search fallback router."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import hashlib
import logging
import os
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urlsplit

from app.core.config import Settings, get_settings
from app.ingestion.ibm_docs_crawler.catalog import (
    CatalogTarget,
    MetadataCatalog,
    is_confident_target_match,
)
from app.ingestion.ibm_docs_crawler.registry import (
    CrawlTarget,
    Registry,
    get_enabled_target,
    load_registry,
)
from app.ingestion.ibm_docs_crawler.storage import CrawlStorage
from app.ingestion.ibm_docs_crawler.urls import is_in_target_scope
from app.ingestion.official_docs.registry import (
    OfficialSourceRegistry,
    OfficialSourceTarget,
    get_enabled_sources,
    load_official_source_registry,
)
from app.retrieval.catalog_selector import CatalogCandidateSelector
from app.retrieval.constraints import constrain_candidates
from app.retrieval.live_docs import LiveDocsRetriever, LiveDocsSettings
from app.retrieval.live_index import schedule_live_indexing
from app.retrieval.official_docs import OfficialDocsRetriever
from app.retrieval.portfolio import is_portfolio_target, portfolio_target
from app.retrieval.section_ranker import candidate_set_is_confident
from app.retrieval.web_search import (
    HttpJsonWebSearchProvider,
    OpenAIResponsesWebSearchProvider,
    TavilyWebSearchProvider,
    WebSearchProvider,
    WebSearchResult,
)

logger = logging.getLogger(__name__)
DocumentationTarget = CrawlTarget | OfficialSourceTarget


@dataclass(frozen=True)
class AdaptiveRetrievalResult:
    candidates: list[dict]
    trace: dict


class AdaptiveRetrievalRouter:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        catalog: MetadataCatalog | None = None,
        storage: CrawlStorage | None = None,
        web_search_provider: WebSearchProvider | None = None,
        registry: Registry | None = None,
        live_retriever_factory: Callable[..., LiveDocsRetriever] = LiveDocsRetriever,
        official_source_registry: OfficialSourceRegistry | None = None,
        official_retriever_factory: Callable[..., OfficialDocsRetriever] = OfficialDocsRetriever,
    ) -> None:
        self.settings = settings or get_settings()
        data_dir = Path(os.path.expandvars(
            self.settings.ibm_docs_data_dir
        )).expanduser()
        self.catalog = catalog or MetadataCatalog(data_dir)
        self.storage = storage or CrawlStorage(data_dir)
        self.registry = registry
        self.live_retriever_factory = live_retriever_factory
        self.official_source_registry = official_source_registry
        self.official_retriever_factory = official_retriever_factory
        self.web_search_provider = web_search_provider

    def retrieve(
        self,
        state: dict,
        *,
        indexed_retrieve: Callable[[], list[dict]],
        opensearch_client,
        embedding_fn,
    ) -> AdaptiveRetrievalResult:
        query = str(state.get("retrieval_query") or state.get("user_question") or "")
        state_trace = state.get("trace") or {}
        force_fallback = bool(state_trace.get("adaptive_retry_requested"))
        freshness_required = _query_requires_fresh_sources(query)
        target = self._target_for_state(state)
        trace: dict = {
            "mode": "adaptive",
            "target": (
                f"{target.product_id}/{target.version_id}" if target else None
            ),
            "stages": [],
            "force_fallback": force_fallback,
            "freshness_required": freshness_required,
        }
        live_settings = self._live_settings()
        metadata_candidates = self._metadata_candidates(query, state)
        cached_candidates: list[dict] = []
        cached_by_source: dict[str, list[dict]] = {}
        cached_retrievers: dict[
            str, tuple[LiveDocsRetriever, DocumentationTarget]
        ] = {}
        selected_cache_source: str | None = None
        selected_cache_candidates: list[dict] = []
        retriever: LiveDocsRetriever | None = None
        official_retrievers: list[tuple[OfficialSourceTarget, OfficialDocsRetriever]] = []

        if target is not None:
            source_targets: list[OfficialSourceTarget] = []
            if isinstance(target, CrawlTarget):
                retriever = self.live_retriever_factory(
                    target,
                    self.catalog,
                    self.storage,
                    live_settings,
                )
                try:
                    cached_candidates = retriever.retrieve_cached(query)
                except Exception as exc:
                    logger.warning("Persistent live-doc cache search failed: %s", exc)
                    trace["cache_error"] = f"{type(exc).__name__}: {exc}"
                cached_by_source["ibm-docs"] = cached_candidates
                cached_retrievers["ibm-docs"] = (retriever, target)
                trace["stages"].append({
                    "stage": "persistent_cache",
                    "candidate_count": len(cached_candidates),
                })
                source_targets = self._official_targets(target)
            else:
                source_targets = [target]
            if self.settings.enable_live_official_sources:
                for source_target in source_targets:
                    source_live_settings = (
                        replace(
                            live_settings,
                            initial_pages=1,
                            max_pages=1,
                            related_depth=0,
                        )
                        if is_portfolio_target(source_target)
                        else live_settings
                    )
                    source_retriever = self.official_retriever_factory(
                        source_target,
                        self.catalog,
                        self.storage,
                        source_live_settings,
                    )
                    official_retrievers.append((source_target, source_retriever))
                    try:
                        source_cached = source_retriever.retrieve_cached(query)
                    except Exception as exc:
                        logger.warning(
                            "Official-source cache search failed for %s: %s",
                            source_target.source_id,
                            exc,
                        )
                        trace.setdefault("official_cache_errors", {})[
                            source_target.source_id
                        ] = f"{type(exc).__name__}: {exc}"
                        source_cached = []
                    cached_candidates = _merge_candidates(
                        cached_candidates, source_cached
                    )
                    cached_by_source[source_target.source_id] = source_cached
                    cached_retrievers[source_target.source_id] = (
                        source_retriever,
                        source_target,
                    )
                    trace["stages"].append({
                        "stage": "official_persistent_cache",
                        "source_id": source_target.source_id,
                        "candidate_count": len(source_cached),
                    })
            cached_candidates = _rank_live_candidates(cached_candidates)
            cached_candidates = constrain_candidates(query, cached_candidates)
            selected_cache_source = self._select_source_id(
                query, target, tuple(cached_by_source)
            )
            selected_cache_candidates = _rank_live_candidates(
                cached_by_source.get(selected_cache_source or "", [])
            )
            selected_cache_candidates = constrain_candidates(
                query, selected_cache_candidates
            )

        if freshness_required:
            # A dated/current announcement cannot be established by a snapshot
            # in the local corpus. Skipping the remote query-embedding call here
            # avoids substantial latency and prevents stale material from being
            # presented as current evidence.
            indexed_candidates = []
            trace["stages"].append({
                "stage": "opensearch_skipped",
                "reason": "freshness_required",
                "candidate_count": 0,
            })
        else:
            try:
                indexed_candidates = indexed_retrieve()
            except Exception as exc:
                logger.exception(
                    "Indexed retrieval failed; adaptive fallbacks remain available"
                )
                indexed_candidates = []
                trace["opensearch_error"] = f"{type(exc).__name__}: {exc}"
            indexed_candidates = constrain_candidates(query, indexed_candidates)
            trace["stages"].append({
                "stage": "opensearch",
                "candidate_count": len(indexed_candidates),
            })
        if (
            not force_fallback
            and not freshness_required
            and candidate_set_is_confident(query, indexed_candidates)
        ):
            trace["selected_stage"] = "opensearch"
            return AdaptiveRetrievalResult(indexed_candidates, trace)

        if metadata_candidates:
            trace["stages"].append({
                "stage": "global_metadata_catalog",
                "candidate_count": len(metadata_candidates),
            })
        combined = _merge_candidates(
            selected_cache_candidates,
            indexed_candidates,
            cached_candidates,
            metadata_candidates,
        )
        if (
            not force_fallback
            and not freshness_required
            and candidate_set_is_confident(query, selected_cache_candidates)
        ):
            trace["selected_stage"] = "persistent_cache"
            trace["selected_cache_source"] = selected_cache_source
            self._schedule_cached_indexing(
                query,
                selected_cache_source,
                cached_retrievers,
                trace,
                opensearch_client=opensearch_client,
                embedding_fn=embedding_fn,
            )
            return AdaptiveRetrievalResult(combined, trace)
        if (
            not force_fallback
            and not freshness_required
            and metadata_candidates
            and candidate_set_is_confident(query, metadata_candidates)
        ):
            trace["selected_stage"] = "global_metadata_catalog"
            return AdaptiveRetrievalResult(combined, trace)

        live_options: list[tuple[str, str, LiveDocsRetriever, object]] = []
        if self.settings.enable_live_ibm_docs and retriever is not None:
            live_options.append(("ibm-docs", "live_ibm_docs", retriever, target))
        if self.settings.enable_live_official_sources:
            live_options.extend(
                (
                    source_target.source_id,
                    (
                        "official_live_web"
                        if is_portfolio_target(source_target)
                        else "official_live_docs"
                    ),
                    source_retriever,
                    source_target,
                )
                for source_target, source_retriever in official_retrievers
            )

        # A dated announcement/current-news question cannot be established by
        # a product manual snapshot. Go straight to the allowlisted official
        # web-search stage instead of spending a bounded crawl timeout first.
        selected_live = (
            None
            if freshness_required
            else self._select_live_option(query, target, live_options)
        )
        if selected_live is not None:
            source_id, stage_name, selected_retriever, selected_target = selected_live
            if not live_settings.user_agent.strip():
                trace["live_docs_error"] = "IBM_DOCS_USER_AGENT is not configured"
            else:
                try:
                    live_result = selected_retriever.retrieve(query)
                    live_candidates = list(live_result.candidates)
                    if is_portfolio_target(selected_target):
                        live_candidates = [
                            {
                                **candidate,
                                "source_type": "official_live_web",
                                "retrieval_origin": "official_live_web",
                                "web_search_provider": "ibm-official-portfolio",
                            }
                            for candidate in live_candidates
                        ]
                    trace["stages"].append({
                        "stage": stage_name,
                        "source_id": source_id,
                        **live_result.trace,
                    })
                    combined = _merge_candidates(
                        constrain_candidates(query, live_candidates),
                        combined,
                    )
                    if self.settings.enable_live_docs_indexing:
                        chunks_index = self.settings.live_docs_chunks_index.strip()
                        docs_index = self.settings.live_docs_docs_index.strip()
                        if not chunks_index or not docs_index:
                            trace["background_index_error"] = (
                                "LIVE_DOCS_CHUNKS_INDEX and LIVE_DOCS_DOCS_INDEX "
                                "must be configured explicitly"
                            )
                        else:
                            future = schedule_live_indexing(
                                live_result.artifacts,
                                selected_target,
                                opensearch_client=opensearch_client,
                                embedding_fn=embedding_fn,
                                chunks_index=chunks_index,
                                docs_index=docs_index,
                            )
                            trace["background_index_scheduled"] = future is not None
                    constrained_live = constrain_candidates(
                        query, live_candidates
                    )
                    if candidate_set_is_confident(query, constrained_live):
                        individually_supporting = [
                            candidate
                            for candidate in constrained_live
                            if candidate_set_is_confident(query, [candidate])
                        ]
                        # Single-answer questions should not carry unrelated
                        # earlier-stage chunks into the evidence window. A
                        # comparison/listing may need a coherent multi-page set,
                        # so retain that set when no one page is sufficient.
                        if individually_supporting:
                            combined = individually_supporting
                        trace["selected_stage"] = stage_name
                        return AdaptiveRetrievalResult(combined, trace)
                except Exception as exc:
                    logger.exception("Bounded official documentation retrieval failed")
                    trace["live_docs_error"] = f"{type(exc).__name__}: {exc}"

        if self.settings.enable_live_web_search:
            trace["web_search_performed"] = True
            trace["web_search_provider"] = (
                self.settings.live_web_search_provider.strip().lower()
            )
            try:
                provider = self._web_provider()
                result_limit = max(
                    1, min(10, self.settings.live_web_search_max_results)
                )
                search_queries = _web_queries(
                    query,
                    target,
                    max_variants=max(
                        1,
                        min(3, self.settings.live_web_search_query_variants),
                    ),
                )
                web_results = _search_web_queries(
                    provider,
                    search_queries,
                    max_results=result_limit,
                )
                requested_product = str(
                    (state.get("extracted_scope") or {}).get("product") or ""
                )
                web_candidates = [
                    _web_candidate(result, target, state)
                    for result in web_results
                    if _result_matches_target(
                        result,
                        target,
                        query,
                        requested_product=requested_product,
                    )
                ]
                web_candidates = constrain_candidates(query, web_candidates)
                trace["stages"].append({
                    "stage": "official_live_web",
                    "candidate_count": len(web_candidates),
                    "provider": trace["web_search_provider"],
                    "query_count": len(search_queries),
                    "raw_result_count": len(web_results),
                })
                # The fallback stage must lead the final evidence set. Keeping
                # stale indexed candidates first can otherwise exhaust
                # EVIDENCE_TOP_K before any current web evidence reaches the
                # answer model.
                if candidate_set_is_confident(query, web_candidates):
                    individually_supporting = [
                        candidate
                        for candidate in web_candidates
                        if candidate_set_is_confident(query, [candidate])
                    ]
                    # Earlier stages reached web search precisely because their
                    # evidence was weak or stale. Once web evidence is sufficient,
                    # do not reintroduce those unrelated chunks into the answer
                    # model's small evidence window.
                    answer_candidate_limit = max(
                        1,
                        min(
                            self.settings.evidence_top_k,
                            self.settings.live_web_search_answer_candidates,
                        ),
                    )
                    combined = (individually_supporting or web_candidates)[
                        :answer_candidate_limit
                    ]
                    trace["stages"][-1]["supporting_candidate_count"] = len(
                        combined
                    )
                    trace["selected_stage"] = "official_live_web"
                else:
                    combined = _merge_candidates(web_candidates, combined)
            except Exception as exc:
                logger.exception("Official live web search failed")
                trace["web_search_error"] = f"{type(exc).__name__}: {exc}"

        trace.setdefault("selected_stage", "best_available")
        return AdaptiveRetrievalResult(combined, trace)

    def _schedule_cached_indexing(
        self,
        query: str,
        source_id: str | None,
        retrievers: dict[str, tuple[LiveDocsRetriever, DocumentationTarget]],
        trace: dict,
        *,
        opensearch_client,
        embedding_fn,
    ) -> None:
        """Optionally promote validated cached pages into explicit staging indices."""
        if not self.settings.enable_live_docs_indexing or not source_id:
            return
        cached_source = retrievers.get(source_id)
        chunks_index = self.settings.live_docs_chunks_index.strip()
        docs_index = self.settings.live_docs_docs_index.strip()
        if not chunks_index or not docs_index:
            trace["background_index_error"] = (
                "LIVE_DOCS_CHUNKS_INDEX and LIVE_DOCS_DOCS_INDEX must be "
                "configured explicitly"
            )
            return
        if cached_source is None:
            return
        try:
            cached_retriever, cached_target = cached_source
            future = schedule_live_indexing(
                cached_retriever.retrieve_cached_artifacts(query),
                cached_target,
                opensearch_client=opensearch_client,
                embedding_fn=embedding_fn,
                chunks_index=chunks_index,
                docs_index=docs_index,
            )
            trace["background_index_scheduled"] = future is not None
            trace["background_index_origin"] = "persistent_cache"
        except Exception as exc:
            logger.exception("Cached live-document indexing retry failed")
            trace["background_index_error"] = f"{type(exc).__name__}: {exc}"

    def _target_for_state(self, state: dict) -> DocumentationTarget | None:
        scope = state.get("extracted_scope") or {}
        portfolio_family = str(scope.get("portfolio_family") or "")
        if portfolio_family in {"ibm", "watsonx"}:
            return portfolio_target(portfolio_family)  # type: ignore[arg-type]

        try:
            registry = self.registry or load_registry()
        except Exception as exc:
            logger.warning("IBM Docs registry unavailable to adaptive router: %s", exc)
            registry = None
        catalog_content_key = str(scope.get("catalog_content_key") or "").strip()
        catalog_target = (
            self.catalog.get_target(catalog_content_key)
            if catalog_content_key else None
        )
        product_name = str(scope.get("product") or "").strip().casefold()
        product_version = str(scope.get("product_version") or "").strip().casefold()
        domain_id = str(scope.get("domain_id") or "")
        matches: list[CrawlTarget] = []
        for product in registry.products if registry is not None else ():
            names = {
                product.product_name.casefold(),
                product.product_id.replace("-", " ").casefold(),
                *(alias.casefold() for alias in product.aliases),
            }
            if product_name and product_name not in names:
                continue
            if not product_name and product.domain_id != domain_id:
                continue
            for version in product.versions:
                if not version.crawl_enabled:
                    continue
                if product_version and not _version_matches(
                    product_version,
                    version.version_id,
                    version.product_version,
                ):
                    continue
                matches.append(get_enabled_target(registry, product.product_id, version.version_id))
        if len(matches) == 1:
            runtime_target = matches[0]
            catalog_target = catalog_target or self._catalog_target_for_runtime(
                runtime_target
            )
            return (
                _attach_catalog_identity(runtime_target, catalog_target)
                if catalog_target is not None else runtime_target
            )

        # Products such as IBM Bob publish their official docs outside
        # www.ibm.com/docs. They still need a deterministic target before the
        # adaptive router can search their metadata and cache.
        try:
            source_registry = (
                self.official_source_registry or load_official_source_registry()
            )
        except Exception as exc:
            logger.warning("Official source registry unavailable to router: %s", exc)
            source_registry = None
        source_matches: list[OfficialSourceTarget] = []
        for source in source_registry.sources if source_registry is not None else ():
            if not source.enabled:
                continue
            names = {
                source.product_name.casefold(),
                source.product_id.replace("-", " ").casefold(),
                *(alias.casefold() for alias in source.aliases),
            }
            if product_name and product_name not in names:
                continue
            if not product_name and source.domain_id != domain_id:
                continue
            if product_version and not _version_matches(
                product_version,
                source.version_id,
                source.product_version,
                source.source_version,
            ):
                continue
            source_matches.extend(get_enabled_sources(
                source_registry,
                product_id=source.product_id,
                version_id=source.version_id,
            ))
        unique = {target.source_id: target for target in source_matches}
        if len(unique) == 1:
            return next(iter(unique.values()))

        if catalog_target is not None:
            return catalog_target.to_crawl_target()

        # Dedicated domains (OpenShift/SNO, Orchestrate, and Bob) have their
        # own indexed/official-source boundaries. Never let an unresolved
        # dedicated target fall through to the portfolio-wide IBM Docs graph;
        # broad lexical overlap can otherwise select an unrelated product.
        if domain_id != "ibm_products":
            return None

        # Registry entries are an operational override, not the global product
        # boundary. Resolve any other IBM Docs product/version from the catalog.
        query = str(state.get("retrieval_query") or state.get("user_question") or "")
        global_matches = self.catalog.resolve_targets(
            query,
            product_version=(product_version or None),
            limit=5,
        )
        top_match = next((
            match for match in global_matches
            if is_confident_target_match(match, query)
        ), None)
        return (
            top_match.to_crawl_target()
            if top_match is not None
            else None
        )

    def _catalog_target_for_runtime(
        self,
        runtime_target: CrawlTarget,
    ) -> CatalogTarget | None:
        matches = self.catalog.resolve_targets(
            runtime_target.product_name,
            product_version=runtime_target.product_version,
            limit=10,
        )
        if not matches:
            return None
        exact_path = next((
            target for target in matches
            if target.docs_path_prefix.rstrip("/")
            == runtime_target.docs_path_prefix.rstrip("/")
        ), None)
        return exact_path or matches[0]

    def _metadata_candidates(self, query: str, state: dict) -> list[dict]:
        scope = state.get("extracted_scope") or {}
        content_key = str(scope.get("catalog_content_key") or "").strip()
        target = self.catalog.get_target(content_key) if content_key else None
        if target is None and str(scope.get("domain_id") or "") != "ibm_products":
            return []
        if target is None:
            matches = self.catalog.resolve_targets(
                query,
                product_version=(
                    str(scope.get("product_version") or "").strip() or None
                ),
                limit=1,
            )
            target = next((
                match for match in matches
                if is_confident_target_match(match, query)
            ), None)
        return self.catalog.metadata_candidates(query, target) if target else []

    def _live_settings(self) -> LiveDocsSettings:
        maximum = min(5, max(1, self.settings.live_docs_max_pages))
        initial = min(maximum, max(1, self.settings.live_docs_initial_pages))
        return LiveDocsSettings(
            user_agent=self.settings.ibm_docs_user_agent.strip(),
            delay_seconds=max(1.0, self.settings.ibm_docs_delay_seconds),
            timeout_seconds=max(5.0, self.settings.ibm_docs_timeout_seconds),
            max_retries=max(1, self.settings.ibm_docs_max_retries),
            max_response_bytes=max(
                100_000, self.settings.ibm_docs_max_response_bytes
            ),
            validate_public_dns=self.settings.ibm_docs_validate_public_dns,
            initial_pages=initial,
            max_pages=maximum,
            related_depth=1 if self.settings.live_docs_related_depth else 0,
            concurrency=min(8, max(1, self.settings.live_docs_concurrency)),
            cache_ttl_seconds=max(0, self.settings.live_docs_cache_ttl_seconds),
            catalog_candidates=max(5, self.settings.live_docs_catalog_candidates),
            evidence_chunks=max(1, self.settings.live_docs_evidence_chunks),
            max_chunks_per_document=max(
                1, self.settings.ibm_docs_max_chunks_per_document
            ),
        )

    def _official_targets(self, target: DocumentationTarget) -> list[OfficialSourceTarget]:
        try:
            registry = self.official_source_registry or load_official_source_registry()
            return get_enabled_sources(
                registry,
                product_id=target.product_id,
                version_id=target.version_id,
            )
        except Exception as exc:
            logger.warning("Official documentation source registry unavailable: %s", exc)
            return []

    def _select_live_option(
        self,
        query: str,
        target: DocumentationTarget | None,
        options: list[tuple[str, str, LiveDocsRetriever, object]],
    ) -> tuple[str, str, LiveDocsRetriever, object] | None:
        if not options:
            return None
        if len(options) == 1 or target is None:
            return options[0]
        by_source = {option[0]: option for option in options}
        selected_source = self._select_source_id(query, target, tuple(by_source))
        if selected_source in by_source:
            return by_source[selected_source]
        return options[0]

    def _select_source_id(
        self,
        query: str,
        target: DocumentationTarget | None,
        source_ids: tuple[str, ...],
    ) -> str | None:
        if not source_ids:
            return None
        if len(source_ids) == 1 or target is None:
            return source_ids[0]
        pages = CatalogCandidateSelector(self.catalog).select(
            query,
            target,
            limit=1,
            search_limit=max(5, self.settings.live_docs_catalog_candidates),
            source_ids=source_ids,
        )
        if pages and pages[0].source_id in source_ids:
            return pages[0].source_id
        return source_ids[0]

    def _web_provider(self) -> WebSearchProvider:
        if self.web_search_provider is not None:
            return self.web_search_provider
        endpoint = self.settings.live_web_search_endpoint.strip()
        domains = tuple(
            value.strip()
            for value in self.settings.live_web_search_allowed_domains.split(",")
            if value.strip()
        )
        provider_name = self.settings.live_web_search_provider.strip().lower()
        if provider_name == "tavily":
            if not endpoint:
                raise ValueError(
                    "LIVE_WEB_SEARCH_ENDPOINT is required for the Tavily provider"
                )
            return TavilyWebSearchProvider(
                api_key=self.settings.live_web_search_api_key.strip(),
                allowed_domains=domains,
                endpoint=endpoint,
                timeout_seconds=max(1.0, self.settings.live_web_search_timeout_seconds),
                max_content_chars=max(500, self.settings.live_web_search_content_chars),
                search_depth=self.settings.live_web_search_depth,
            )
        if provider_name == "openai":
            return OpenAIResponsesWebSearchProvider(
                api_key=(
                    self.settings.live_web_search_api_key.strip()
                    or os.getenv("OPENAI_API_KEY", "").strip()
                ),
                allowed_domains=domains,
                model=self.settings.live_web_search_model,
                timeout_seconds=max(1.0, self.settings.live_web_search_timeout_seconds),
            )
        if provider_name != "http_json":
            raise ValueError(f"unsupported live web search provider: {provider_name}")
        if not endpoint:
            raise ValueError(
                "LIVE_WEB_SEARCH_ENDPOINT is required when the http_json "
                "live web search provider is enabled"
            )
        return HttpJsonWebSearchProvider(
            endpoint,
            api_key=self.settings.live_web_search_api_key,
            allowed_domains=domains,
            timeout_seconds=max(1.0, self.settings.live_web_search_timeout_seconds),
        )


def _merge_candidates(*groups: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            key = str(candidate.get("chunk_id") or "")
            if not key:
                key = hashlib.sha256(
                    (str(candidate.get("source_uri")) + str(candidate.get("chunk_text"))).encode()
                ).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            output.append(candidate)
    return output


def _attach_catalog_identity(
    runtime_target: CrawlTarget,
    catalog_target: CatalogTarget,
) -> CrawlTarget:
    """Use global catalog keys for discovery while retaining canonical labels."""
    return replace(
        runtime_target,
        docs_path_prefix=catalog_target.docs_path_prefix,
        # The curated runtime registry owns the canonical live-retrieval seed.
        # A global catalog target may use an arbitrary landing topic (for
        # example, Instana's release notes) as its structural entry point. Do
        # not let that structural URL replace the curated product overview.
        run_context={
            **runtime_target.run_context,
            "content_key": catalog_target.content_key,
            "catalog_product_id": catalog_target.product_id,
            "catalog_product_name": catalog_target.product_name,
            "catalog_version_id": catalog_target.version_id,
            "registry_enabled": "registry-with-global-catalog",
        },
    )


def _rank_live_candidates(candidates: list[dict]) -> list[dict]:
    """Order comparable cached/live lexical scores across official sources."""
    return sorted(
        candidates,
        key=lambda candidate: -_numeric_score(candidate.get("_live_score")),
    )


def _numeric_score(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _web_queries(
    query: str,
    target: DocumentationTarget | None,
    *,
    max_variants: int,
) -> list[str]:
    """Build a few focused searches instead of one duplicated broad query."""
    normalized = " ".join(query.split())
    product = str(getattr(target, "product_name", "") or "").strip()
    version = str(getattr(target, "product_version", "") or "").strip()
    context_parts = []
    if product and product.casefold() not in normalized.casefold():
        context_parts.append(product)
    if (
        version
        and version.casefold() not in {"current", "latest"}
        and version.casefold() not in normalized.casefold()
    ):
        context_parts.append(version)
    context = " ".join(context_parts)
    base = " ".join(
        part for part in (normalized, context, "official IBM") if part
    )

    focused: list[str] = []
    event = re.search(r"\bthink\s+(20\d{2})\b", normalized, re.IGNORECASE)
    if event:
        subject = product or _query_subject(normalized)
        focused.append(
            " ".join(
                part for part in (
                    "IBM Think", event.group(1), subject, "announcement"
                ) if part
            )
        )

    lowered = normalized.casefold()
    if (
        any(term in lowered for term in ("certificate", "tls", "ssl"))
        and any(term in lowered for term in (
            "rotate", "rotating", "rotated", "rotation", "renew", "refresh",
            "expire", "lifespan"
        ))
    ):
        subject = product or _query_subject(normalized)
        object_terms = _certificate_object_terms(normalized, product)
        branded_subject = (
            subject if subject.casefold().startswith("ibm ") else f"IBM {subject}"
        )
        lifecycle_terms = (
            f"{object_terms} lifespan"
            if object_terms == "internal-tls certificate"
            else f"{object_terms} lifespan renewal rotation"
        )
        focused.append(
            " ".join(
                part for part in (
                    "site:support.ibm.com",
                    branded_subject,
                    lifecycle_terms,
                ) if part
            )
        )

    focused.append(base)
    return list(dict.fromkeys(focused))[:max_variants]


def _search_web_queries(
    provider: WebSearchProvider,
    queries: list[str],
    *,
    max_results: int,
) -> list[WebSearchResult]:
    """Search bounded variants and interleave each query's best results.

    A focused query (for example the IBM Support certificate-lifecycle query)
    and the broader user wording are both useful.  Appending a whole result
    page at a time lets weak results from the first query consume the evidence
    window before the second query's exact hit is considered.  Round-robin
    merging preserves provider relevance *within* each query while giving every
    bounded variant a fair first-page slot.
    """
    output: list[WebSearchResult] = []
    seen: set[str] = set()
    batches: list[list[WebSearchResult]] = []
    # Variants are independent HTTP searches. Run the small bounded set in
    # parallel while consuming their results in the original query order so
    # ranking remains deterministic.
    with ThreadPoolExecutor(max_workers=min(3, max(1, len(queries)))) as executor:
        futures = [
            executor.submit(provider.search, query, max_results=max_results)
            for query in queries
        ]
        for future in futures:
            try:
                batches.append(future.result())
            except Exception as exc:
                # One optional query variant must not discard successful
                # results returned by the other variants.
                logger.warning("Live web-search variant failed: %s", exc)

    for index in range(max((len(batch) for batch in batches), default=0)):
        for batch in batches:
            if index >= len(batch):
                continue
            result = batch[index]
            if result.url in seen:
                continue
            seen.add(result.url)
            output.append(result)
    # Keep the bounded results from every variant until local product/event
    # validation runs. Truncating here meant five weak hits from the first query
    # could hide an exact result from the second query.
    return output[: max_results * max(1, len(queries))]


def _query_subject(query: str) -> str:
    stop_words = {
        "about", "according", "and", "answer", "are", "at", "current",
        "documentation", "give", "ibm", "in", "official", "provide", "the",
        "to", "urls", "use", "what", "with",
    }
    tokens = [
        token for token in re.findall(r"[a-z0-9][a-z0-9_.-]+", query.casefold())
        if token not in stop_words and not re.fullmatch(r"20\d{2}", token)
    ]
    return " ".join(tokens[:8])


def _certificate_object_terms(query: str, product: str) -> str:
    ignored = {
        "according", "and", "are", "commands", "data", "documented",
        "documentation", "for", "ibm", "pak", "steps", "the",
        "to", "what",
    }
    product_tokens = set(re.findall(r"[a-z0-9]+", product.casefold()))
    words = set(re.findall(r"[a-z0-9]+", query.casefold()))
    if {"internal", "tls"}.issubset(words):
        # IBM source titles commonly spell this Kubernetes secret/topic as
        # ``internal-tls`` even when users write "internal TLS".
        return "internal-tls certificate"
    terms = [
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_.-]+", query.casefold())
        if token not in ignored
        and token not in product_tokens
        and not re.fullmatch(r"\d+(?:\.\d+)*(?:\.x)?", token)
    ]
    return " ".join(dict.fromkeys(terms))


def _query_requires_fresh_sources(query: str) -> bool:
    """Return True when indexed evidence alone cannot establish freshness.

    These signals describe time-sensitive requests, not ordinary documentation
    versions. They bypass an apparently relevant local hit so the router can
    validate the answer against a live official page or the configured search
    provider.
    """
    normalized = " ".join(query.casefold().split())
    freshness_phrases = (
        "current overview",
        "currently",
        "latest announcement",
        "latest news",
        "most recent",
        "right now",
        "released today",
        "announced at",
        "what did ibm announce",
        "this week",
        "this month",
        "this year",
    )
    if any(phrase in normalized for phrase in freshness_phrases):
        return True
    return bool(
        re.search(r"\b(?:today|currently|recently|newest)\b", normalized)
        or re.search(r"\bthink\s+20\d{2}\b", normalized)
    )


def _result_matches_target(
    result: WebSearchResult,
    target: DocumentationTarget | None,
    query: str,
    *,
    requested_product: str = "",
) -> bool:
    parsed = urlsplit(result.url)
    if (
        target is not None
        and parsed.hostname in {"ibm.com", "www.ibm.com"}
        and parsed.path.startswith("/docs/")
    ):
        if not is_in_target_scope(result.url, target.docs_path_prefix):
            return False

    haystack = _normalized_identity_text(
        " ".join((result.title, result.snippet, result.url))
    )
    event = re.search(r"\bthink\s+(20\d{2})\b", query, re.IGNORECASE)
    if event and f"think {event.group(1)}" not in haystack:
        return False

    if target is None or is_portfolio_target(target):
        # An unresolved product must not turn the fallback into an unrestricted
        # allowlist search.  Require the explicit product phrase when one was
        # supplied by the request/classifier.  Portfolio questions intentionally
        # omit a single product and remain broad.
        requested_identity = _normalized_identity_text(requested_product)
        required_identity = (
            f"ibm {requested_identity}"
            if _ambiguous_short_identity(requested_identity)
            else requested_identity
        )
        if required_identity and not _identity_matches(required_identity, haystack):
            return False
        return True

    if _result_has_obsolete_version_boundary(result, target):
        return False

    canonical_identities = {
        _normalized_identity_text(value)
        for value in (
            target.product_name,
            target.product_id,
        )
        if value
    }
    canonical_identities.discard("")
    aliases = {
        _normalized_identity_text(value)
        for value in getattr(target, "aliases", ())
        if value
    }
    aliases.discard("")
    canonical_match = any(
        _identity_matches(identity, haystack)
        for identity in canonical_identities
        if not _ambiguous_short_identity(identity)
    )
    alias_match = any(
        (
            _identity_matches(f"ibm {identity}", haystack)
            if _ambiguous_short_identity(identity)
            else _identity_matches(identity, haystack)
        )
        for identity in aliases
    )
    if not (canonical_match or alias_match):
        return False
    return True


def _normalized_identity_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _identity_matches(identity: str, haystack: str) -> bool:
    """Match normalized product identities as complete token phrases.

    Registry aliases such as ``was``, ``ace``, and ``mq`` are useful, but plain
    substring checks make them match unrelated words.  Both inputs contain only
    lowercase alphanumeric tokens separated by spaces, so padded phrase matching
    is deterministic and boundary safe.
    """
    return bool(identity) and f" {identity} " in f" {haystack} "


def _ambiguous_short_identity(identity: str) -> bool:
    """Return True for one-token aliases that collide with ordinary prose."""
    return " " not in identity and len(identity) <= 3


def _result_has_obsolete_version_boundary(
    result: WebSearchResult,
    target: DocumentationTarget,
) -> bool:
    """Reject procedures explicitly limited to releases older than the target."""
    requested = _numeric_version_tuple(str(target.product_version or ""))
    if requested is None:
        return False
    evidence = " ".join((result.title, result.snippet)).casefold()
    for match in re.finditer(
        r"versions?\s+(?:strictly\s+)?lower\s+than\s+(\d+(?:\.\d+)+)",
        evidence,
    ):
        ceiling = _numeric_version_tuple(match.group(1))
        if ceiling is not None and requested >= ceiling:
            return True
    return False


def _numeric_version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+)+", value)
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def _version_matches(requested: str, *available_values: str) -> bool:
    """Match user shorthand such as 5.4 to a documented 5.4.x family."""
    requested_value = requested.strip().casefold()
    for raw_value in available_values:
        available = raw_value.strip().casefold()
        if requested_value == available:
            return True
        if available in {"latest", "current"}:
            continue
        if _version_family_contains(available, requested_value):
            return True
        if _version_family_contains(requested_value, available):
            return True
    return False


def _version_family_contains(family: str, candidate: str) -> bool:
    if not family.endswith(".x"):
        return False
    prefix = family[:-2]
    return candidate == prefix or candidate.startswith(prefix + ".")


def _web_candidate(
    result: WebSearchResult,
    target: DocumentationTarget | None,
    state: dict,
) -> dict:
    digest = hashlib.sha256(result.url.encode()).hexdigest()[:20]
    scope = state.get("extracted_scope") or {}
    product_version, version_basis = _verified_web_product_version(
        result,
        target,
        str(scope.get("product_version") or ""),
    )
    return {
        "chunk_id": f"official_live_web:{digest}",
        "document_id": f"web-{digest}",
        "title": result.title,
        "domain_id": target.domain_id if target else scope.get("domain_id", "ibm_products"),
        "product": target.product_name if target else scope.get("product", "IBM"),
        # Never stamp the requested version onto arbitrary search text.  A
        # version is attached only when the source URL/text establishes it or
        # explicitly declares applicability to future releases.
        "product_version": product_version,
        "product_version_basis": version_basis,
        "ocp_version": scope.get("ocp_version"),
        "source_uri": result.url,
        "source_type": "official_live_web",
        "section_path": "Search result excerpt",
        "page_start": None,
        "page_end": None,
        "chunk_text": result.snippet,
        "retrieval_origin": "official_live_web",
        "web_search_provider": result.provider,
    }


def _verified_web_product_version(
    result: WebSearchResult,
    target: DocumentationTarget | None,
    requested_scope_version: str,
) -> tuple[str | None, str]:
    """Return source-supported version attribution for a live search result."""
    if target is None:
        return (requested_scope_version or None, "request-only" if requested_scope_version else "")

    requested = str(target.product_version or requested_scope_version or "").strip()
    if not requested:
        return None, ""
    if requested.casefold() in {"current", "latest"}:
        return requested, "current-target"

    parsed = urlsplit(result.url)
    if (
        parsed.hostname in {"ibm.com", "www.ibm.com"}
        and parsed.path.startswith("/docs/")
        and is_in_target_scope(result.url, target.docs_path_prefix)
    ):
        return requested, "versioned-docs-path"

    evidence = " ".join((result.title, result.snippet, result.url))
    normalized = evidence.casefold()
    requested_numeric = _numeric_version_tuple(requested)
    explicit_versions = [
        match.group(0)
        for match in re.finditer(
            r"(?<![\d.])\d+\.\d+(?:\.\d+)?(?:\.x)?(?!\d|\.\d)",
            normalized,
        )
    ]
    if any(_version_matches(requested, version) for version in explicit_versions):
        return requested, "source-version"

    if requested_numeric is not None and re.search(
        r"\b(?:and\s+)?future\s+releases?\b", normalized
    ):
        for version in explicit_versions:
            source_numeric = _numeric_version_tuple(version)
            if source_numeric is not None and source_numeric <= requested_numeric:
                return requested, "source-future-releases"

    if explicit_versions:
        most_specific = max(
            explicit_versions,
            key=lambda value: (value.count("."), len(value)),
        )
        return most_specific, "source-version-mismatch"
    return None, "unverified"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
