"""Bounded live retrieval for allowlisted official Markdown documentation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from app.ingestion.ibm_docs_crawler.fetcher import FetchSettings, RequestRateLimiter
from app.ingestion.ibm_docs_crawler.models import ExtractedDocument, FetchResult
from app.ingestion.official_docs.extractor import (
    extract_html_document,
    extract_markdown_document,
)
from app.ingestion.official_docs.fetcher import (
    OfficialSourceFetcher,
    load_official_robots_policy,
)
from app.ingestion.official_docs.registry import OfficialSourceTarget
from app.ingestion.official_docs.urls import (
    canonicalize_source_url,
    is_source_page_url,
)
from app.retrieval.live_docs import FetchRequest, LiveDocsRetriever


class OfficialDocsRetriever(LiveDocsRetriever):
    """Reuse the cache/chunk/rank pipeline with a source-specific URL and parser policy."""

    def __init__(self, target: OfficialSourceTarget, *args, **kwargs) -> None:
        super().__init__(target, *args, source_id=target.source_id, **kwargs)

    def _canonicalize(self, url: str) -> str:
        return canonicalize_source_url(
            url,
            allowed_host=self.target.allowed_host,
            path_prefix=self.target.docs_path_prefix,
        )

    def _is_in_scope(self, url: str) -> bool:
        return is_source_page_url(
            url,
            allowed_host=self.target.allowed_host,
            path_prefix=self.target.docs_path_prefix,
            content_format=self.target.content_format,
        )

    def _target_for_url(self, url: str) -> OfficialSourceTarget | None:
        """Keep official-source URLs on their independently allowlisted target."""
        return self.target if self._is_in_scope(url) else None

    def _content_type_supported(self, content_type: str) -> bool:
        if self.target.content_format == "html":
            return not content_type or any(
                allowed in content_type for allowed in ("text/html", "application/xhtml+xml")
            )
        return not content_type or any(
            allowed in content_type
            for allowed in ("text/markdown", "text/plain", "application/octet-stream")
        )

    @staticmethod
    def _redirect_was_lost(_requested_url: str, _final_url: str) -> bool:
        return False

    def _extract_result(
        self,
        result: FetchResult,
        *,
        requested_url: str,
        target: OfficialSourceTarget,
    ) -> ExtractedDocument:
        page = self.catalog.get_page(requested_url)
        if target.content_format == "html":
            return extract_html_document(
                result.content,
                requested_url=requested_url,
                final_url=result.final_url,
                http_status=result.status_code,
                target=target,
            )
        return extract_markdown_document(
            result.content,
            requested_url=requested_url,
            final_url=result.final_url,
            http_status=result.status_code,
            target=target,
            fallback_title=page.title if page else "",
        )

    @staticmethod
    def _origin() -> str:
        return "official_live_docs"

    def _raw_extension(self) -> str:
        return "html" if self.target.content_format == "html" else "md"

    def _default_fetch_batch(
        self,
        requests: list[FetchRequest],
    ) -> dict[str, FetchResult]:
        if not self.settings.user_agent.strip():
            raise ValueError("IBM_DOCS_USER_AGENT is required before live network retrieval")
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
            policy = load_official_robots_policy(
                self.target,
                self.settings.user_agent,
                timeout_seconds=self.settings.timeout_seconds,
                client=client,
            )
            fetcher = OfficialSourceFetcher(
                self.target,
                policy,
                fetch_settings,
                client=client,
                rate_limiter=limiter,
            )
            with ThreadPoolExecutor(
                max_workers=min(self.settings.concurrency, len(requests)),
                thread_name_prefix="official-docs-live",
            ) as executor:
                future_to_request = {
                    executor.submit(
                        fetcher.fetch,
                        request.url,
                        conditional_headers=dict(request.conditional_headers),
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
