"""Bounded live IBM Docs retrieval with persistent cache reuse."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, fields
import hashlib
import logging
import re
from typing import Callable, Mapping
from urllib.parse import urlsplit

import httpx

from app.ingestion.chunker import ChunkRecord, chunk_pages
from app.ingestion.ibm_docs_crawler.catalog import MetadataCatalog
from app.ingestion.ibm_docs_crawler.crawler import (
    _is_nonfatal_extraction_error,
    _topic_redirect_was_lost,
)
from app.ingestion.ibm_docs_crawler.extractor import (
    ExtractionError,
    extract_document,
    to_parse_result,
)
from app.ingestion.ibm_docs_crawler.fetcher import (
    FetchSettings,
    PoliteFetcher,
    RequestRateLimiter,
)
from app.ingestion.ibm_docs_crawler.models import (
    ContentBlock,
    ExtractedDocument,
    FetchResult,
)
from app.ingestion.ibm_docs_crawler.registry import CrawlTarget
from app.ingestion.ibm_docs_crawler.robots import load_robots_policy
from app.ingestion.ibm_docs_crawler.storage import CachedArtifacts, CrawlStorage
from app.ingestion.ibm_docs_crawler.urls import canonicalize_url, is_in_target_scope
from app.retrieval.catalog_selector import CatalogCandidateSelector
from app.retrieval.section_ranker import rank_artifact_chunks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveDocsSettings:
    user_agent: str
    delay_seconds: float = 1.5
    timeout_seconds: float = 30.0
    max_retries: int = 4
    max_response_bytes: int = 20_000_000
    validate_public_dns: bool = True
    initial_pages: int = 3
    max_pages: int = 5
    related_depth: int = 1
    concurrency: int = 3
    cache_ttl_seconds: int = 86_400
    catalog_candidates: int = 30
    evidence_chunks: int = 10
    max_chunks_per_document: int = 250

    def __post_init__(self) -> None:
        if not 1 <= self.initial_pages <= self.max_pages <= 5:
            raise ValueError("live retrieval requires 1 <= initial_pages <= max_pages <= 5")
        if self.related_depth not in {0, 1}:
            raise ValueError("live related-link depth must be 0 or 1")
        if not 1 <= self.concurrency <= 8:
            raise ValueError("live retrieval concurrency must be between 1 and 8")


@dataclass(frozen=True)
class FetchRequest:
    url: str
    conditional_headers: Mapping[str, str]
    target: CrawlTarget


@dataclass(frozen=True)
class LiveDocumentArtifact:
    document: ExtractedDocument
    chunks: list[ChunkRecord]
    origin: str


@dataclass(frozen=True)
class LiveRetrievalResult:
    candidates: list[dict]
    artifacts: list[LiveDocumentArtifact]
    trace: dict


FetchBatch = Callable[[list[FetchRequest]], dict[str, FetchResult]]


class LiveDocsRetriever:
    def __init__(
        self,
        target: CrawlTarget,
        catalog: MetadataCatalog,
        storage: CrawlStorage,
        settings: LiveDocsSettings,
        *,
        fetch_batch: FetchBatch | None = None,
        source_id: str = "ibm-docs",
    ) -> None:
        self.target = target
        self.catalog = catalog
        self.storage = storage
        self.settings = settings
        self.selector = CatalogCandidateSelector(catalog)
        self._fetch_batch_override = fetch_batch
        self.source_id = source_id

    def retrieve_cached(self, query: str) -> list[dict]:
        """Search normalized disk cache before spending an embedding/network call."""
        artifacts = self.retrieve_cached_artifacts(query)
        return rank_artifact_chunks(
            query,
            [
                (artifact.document, artifact.chunks, artifact.origin)
                for artifact in artifacts
            ],
            self.target,
            limit=self.settings.evidence_chunks,
        )

    def retrieve_cached_artifacts(self, query: str) -> list[LiveDocumentArtifact]:
        """Load the selected normalized artifacts for warm-answer indexing/retry."""
        pages = self.selector.select(
            query,
            self.target,
            limit=self.settings.max_pages,
            search_limit=self.settings.catalog_candidates,
            source_ids=(self.source_id,),
        )
        artifacts: list[LiveDocumentArtifact] = []
        for page in pages:
            cached = self.storage.load_cached_artifacts(page.canonical_url)
            if cached is None:
                continue
            artifact = _artifact_from_cache(cached, "persistent_cache")
            artifacts.append(artifact)
        return artifacts

    def retrieve(self, query: str) -> LiveRetrievalResult:
        """Fetch at most five selected pages, with at most one related-link hop."""
        self.catalog.ensure_seed(self.target, source_id=self.source_id)
        initial_pages = self.selector.select(
            query,
            self.target,
            limit=self.settings.initial_pages,
            search_limit=self.settings.catalog_candidates,
            source_ids=(self.source_id,),
        )
        selected_urls = [page.canonical_url for page in initial_pages]
        run_id = self.storage.start_run(self.target)
        artifacts: list[LiveDocumentArtifact] = []
        trace = {
            "run_id": run_id,
            "selected_urls": list(selected_urls),
            "cache_hits": 0,
            "network_fetches": 0,
            "failed_pages": 0,
            "related_hops": 0,
        }
        try:
            first, first_stats = self._resolve_urls(selected_urls, run_id)
            artifacts.extend(first)
            _merge_counts(trace, first_stats)

            if self.settings.related_depth == 1 and len(selected_urls) < self.settings.max_pages:
                related_urls = self._select_related_urls(
                    query,
                    artifacts,
                    excluded=set(selected_urls),
                    limit=self.settings.max_pages - len(selected_urls),
                )
                if related_urls:
                    trace["related_hops"] = 1
                    trace["selected_urls"].extend(related_urls)
                    related, related_stats = self._resolve_urls(related_urls, run_id)
                    artifacts.extend(related)
                    _merge_counts(trace, related_stats)

            status = "STAGED"
            if trace["failed_pages"]:
                status = "PARTIAL" if artifacts else "FAILED"
            elif not artifacts:
                status = "FAILED"
            report = {
                "run_id": run_id,
                "status": status,
                "mode": "bounded-live-retrieval",
                "product_id": self.target.product_id,
                "version_id": self.target.version_id,
                "selected_pages": len(trace["selected_urls"]),
                "cache_hits": trace["cache_hits"],
                "network_fetches": trace["network_fetches"],
                "failed_pages": trace["failed_pages"],
            }
            self.storage.finish_run(run_id, status, report)
        except Exception as exc:
            self.storage.finish_run(run_id, "FAILED", {
                "run_id": run_id,
                "status": "FAILED",
                "mode": "bounded-live-retrieval",
                "fatal_error": f"{type(exc).__name__}: {exc}",
            })
            raise

        ranked_input = [
            (artifact.document, artifact.chunks, artifact.origin)
            for artifact in artifacts
        ]
        candidates = rank_artifact_chunks(
            query,
            ranked_input,
            self.target,
            limit=self.settings.evidence_chunks,
        )
        trace["candidate_count"] = len(candidates)
        return LiveRetrievalResult(candidates=candidates, artifacts=artifacts, trace=trace)

    def _resolve_urls(
        self,
        urls: list[str],
        run_id: str,
    ) -> tuple[list[LiveDocumentArtifact], dict[str, int]]:
        artifacts: list[LiveDocumentArtifact] = []
        requests: list[FetchRequest] = []
        cached_by_url: dict[str, CachedArtifacts | None] = {}
        stats = {"cache_hits": 0, "network_fetches": 0, "failed_pages": 0}
        for raw_url in dict.fromkeys(urls):
            url = self._canonicalize(raw_url)
            request_target = self._target_for_url(url)
            if request_target is None:
                stats["failed_pages"] += 1
                continue
            self.storage.record_discovered(run_id, url)
            cached = self.storage.load_cached_artifacts(
                url, max_age_seconds=self.settings.cache_ttl_seconds
            )
            cached_by_url[url] = cached
            if cached is not None and cached.fresh:
                artifact = _artifact_from_cache(cached, "persistent_cache")
                artifacts.append(artifact)
                self.catalog.enrich_document(
                    request_target, artifact.document, source_id=self.source_id
                )
                self.storage.mark_unchanged(run_id, url, http_status=200)
                stats["cache_hits"] += 1
            else:
                requests.append(FetchRequest(
                    url=url,
                    conditional_headers=self.storage.cache_headers(url),
                    target=request_target,
                ))

        if not requests:
            return artifacts, stats

        results = (
            self._fetch_batch_override(requests)
            if self._fetch_batch_override is not None
            else self._default_fetch_batch(requests)
        )
        stats["network_fetches"] += len(requests)
        for request in requests:
            url = request.url
            request_target = request.target
            result = results.get(url)
            cached = cached_by_url.get(url)
            if result is None:
                stats["failed_pages"] += 1
                self.storage.mark_failed(run_id, url, "fetch worker returned no result")
                continue
            if result.not_modified:
                if cached is None:
                    stats["failed_pages"] += 1
                    self.storage.mark_failed(
                        run_id, url, "HTTP 304 received without cached normalized artifacts",
                        http_status=304,
                    )
                    continue
                artifact = _artifact_from_cache(cached, "persistent_cache_revalidated")
                artifacts.append(artifact)
                self.catalog.enrich_document(
                    request_target, artifact.document, source_id=self.source_id
                )
                self.storage.mark_unchanged(run_id, url)
                stats["cache_hits"] += 1
                continue
            if result.error or result.status_code != 200:
                stats["failed_pages"] += 1
                self.storage.mark_failed(
                    run_id,
                    url,
                    result.error or f"unexpected HTTP status {result.status_code}",
                    http_status=result.status_code,
                )
                continue
            if self._redirect_was_lost(url, result.final_url):
                stats["failed_pages"] += 1
                self.storage.mark_skipped(
                    run_id,
                    url,
                    "redirect dropped or changed the requested topic",
                    http_status=result.status_code,
                )
                continue
            content_type = result.headers.get("content-type", "").lower()
            if not self._content_type_supported(content_type):
                stats["failed_pages"] += 1
                self.storage.mark_failed(
                    run_id,
                    url,
                    f"unsupported Content-Type: {content_type}",
                    http_status=result.status_code,
                )
                continue
            raw_document_id = "doc-" + hashlib.sha256(
                result.final_url.encode("utf-8")
            ).hexdigest()[:16]
            raw_path = self.storage.save_raw(
                run_id,
                raw_document_id,
                result.content,
                extension=self._raw_extension(),
            )
            try:
                document = self._extract_result(
                    result, requested_url=url, target=request_target
                )
                chunks = chunk_pages(to_parse_result(document).pages)
                if not chunks:
                    raise ValueError("no chunks were produced")
                if len(chunks) > self.settings.max_chunks_per_document:
                    raise ValueError(
                        f"document produced {len(chunks)} chunks; limit is "
                        f"{self.settings.max_chunks_per_document}"
                    )
                self.storage.stage_document(
                    run_id, document, chunks, result.headers, raw_path
                )
                self.catalog.enrich_document(
                    request_target, document, source_id=self.source_id
                )
                artifacts.append(LiveDocumentArtifact(document, chunks, self._origin()))
            except ExtractionError as exc:
                stats["failed_pages"] += 1
                if _is_nonfatal_extraction_error(exc):
                    self.storage.mark_skipped(
                        run_id, url, f"{type(exc).__name__}: {exc}",
                        http_status=result.status_code, raw_path=raw_path,
                    )
                else:
                    self.storage.mark_failed(
                        run_id, url, f"{type(exc).__name__}: {exc}",
                        http_status=result.status_code, raw_path=raw_path,
                    )
            except Exception as exc:
                stats["failed_pages"] += 1
                self.storage.mark_failed(
                    run_id, url, f"{type(exc).__name__}: {exc}",
                    http_status=result.status_code, raw_path=raw_path,
                )
        return artifacts, stats

    def _select_related_urls(
        self,
        query: str,
        artifacts: list[LiveDocumentArtifact],
        *,
        excluded: set[str],
        limit: int,
    ) -> list[str]:
        candidates: set[str] = set()
        for artifact in artifacts:
            candidates.update(artifact.document.links)
            candidates.update(self.catalog.neighbors(
                artifact.document.canonical_url,
                edge_types=("related", "parent", "child", "outgoing_ibm"),
            ))
        candidates = {
            url for url in candidates
            if url not in excluded and self._target_for_url(url) is not None
        }
        query_tokens = set(query.lower().replace("-", " ").split())
        ranked = sorted(
            candidates,
            key=lambda url: (
                -sum(token in url.lower().replace("-", " ") for token in query_tokens),
                url,
            ),
        )
        return ranked[:max(0, limit)]

    def _canonicalize(self, url: str) -> str:
        return canonicalize_url(url)

    def _is_in_scope(self, url: str) -> bool:
        return self._target_for_url(url) is not None

    def _target_for_url(self, url: str) -> CrawlTarget | None:
        """Resolve a bounded related link to its catalog-backed docs target.

        IBM Docs frequently links between product families using content-key
        URLs such as ``/docs/SSNFH6_5.4.x/...``. Those links redirect to the
        public ``/docs/en/<product>/<version>`` route. Treat the catalog as the
        allowlist for that one-hop traversal so an official cross-product edge
        can be followed without opening live retrieval to arbitrary paths.
        """
        if is_in_target_scope(url, self.target.docs_path_prefix):
            return self.target

        page = self.catalog.get_page(url)
        if page is not None:
            catalog_target = self.catalog.get_target(page.version_id)
            if catalog_target is not None:
                return catalog_target.to_crawl_target()

        path = urlsplit(url).path
        match = re.match(r"^/docs/([^/]+)/", path, re.IGNORECASE)
        if match and match.group(1).lower() != "en":
            catalog_target = self.catalog.get_target(match.group(1))
            if catalog_target is not None:
                return catalog_target.to_crawl_target()
        return None

    @staticmethod
    def _content_type_supported(content_type: str) -> bool:
        return not content_type or "html" in content_type

    @staticmethod
    def _redirect_was_lost(requested_url: str, final_url: str) -> bool:
        return _topic_redirect_was_lost(requested_url, final_url)

    def _extract_result(
        self,
        result: FetchResult,
        *,
        requested_url: str,
        target: CrawlTarget,
    ) -> ExtractedDocument:
        return extract_document(
            result.content,
            requested_url=requested_url,
            final_url=result.final_url,
            http_status=result.status_code,
            target=target,
        )

    @staticmethod
    def _origin() -> str:
        return "live_ibm_docs"

    @staticmethod
    def _raw_extension() -> str:
        return "html"

    def _default_fetch_batch(
        self,
        requests: list[FetchRequest],
    ) -> dict[str, FetchResult]:
        if not self.settings.user_agent.strip():
            raise ValueError(
                "IBM_DOCS_USER_AGENT is required before live network retrieval"
            )
        policy = load_robots_policy(
            self.settings.user_agent,
            timeout_seconds=self.settings.timeout_seconds,
        )
        fetch_settings = FetchSettings(
            user_agent=self.settings.user_agent,
            delay_seconds=self.settings.delay_seconds,
            timeout_seconds=self.settings.timeout_seconds,
            max_retries=self.settings.max_retries,
            max_response_bytes=self.settings.max_response_bytes,
            validate_public_dns=self.settings.validate_public_dns,
        )
        limiter = RequestRateLimiter()
        output: dict[str, FetchResult] = {}
        with httpx.Client(
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
        ) as client:
            fetcher = PoliteFetcher(
                policy,
                fetch_settings,
                client=client,
                rate_limiter=limiter,
            )
            with ThreadPoolExecutor(
                max_workers=min(self.settings.concurrency, len(requests)),
                thread_name_prefix="ibm-docs-live",
            ) as executor:
                future_to_request = {
                    executor.submit(
                        fetcher.fetch,
                        request.url,
                        conditional_headers=request.conditional_headers,
                        scope_prefix=(
                            request.target.docs_path_prefix
                            if is_in_target_scope(
                                request.url, request.target.docs_path_prefix
                            )
                            else "/docs"
                        ),
                    ): request
                    for request in requests
                }
                for future in as_completed(future_to_request):
                    request = future_to_request[future]
                    try:
                        output[request.url] = future.result()
                    except Exception as exc:
                        output[request.url] = FetchResult(
                            requested_url=request.url,
                            final_url=request.url,
                            status_code=0,
                            headers={},
                            content=b"",
                            error=f"{type(exc).__name__}: {exc}",
                        )
        return output


def _artifact_from_cache(cached: CachedArtifacts, origin: str) -> LiveDocumentArtifact:
    document = _document_from_dict(cached.document)
    chunks = [_chunk_from_dict(record) for record in cached.chunks]
    return LiveDocumentArtifact(document=document, chunks=chunks, origin=origin)


def _document_from_dict(record: dict) -> ExtractedDocument:
    allowed = {item.name for item in fields(ExtractedDocument)}
    values = {key: value for key, value in record.items() if key in allowed}
    values["blocks"] = [ContentBlock(**block) for block in values.get("blocks", [])]
    return ExtractedDocument(**values)


def _chunk_from_dict(record: dict) -> ChunkRecord:
    allowed = {item.name for item in fields(ChunkRecord)}
    return ChunkRecord(**{key: value for key, value in record.items() if key in allowed})


def _merge_counts(trace: dict, stats: dict[str, int]) -> None:
    for key, value in stats.items():
        trace[key] = int(trace.get(key, 0)) + int(value)
