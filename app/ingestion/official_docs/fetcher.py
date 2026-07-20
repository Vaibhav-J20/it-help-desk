"""Bounded, robots-aware fetching for one exact official documentation host."""

from __future__ import annotations

from dataclasses import dataclass
import time
from urllib import robotparser

import httpx

from app.ingestion.ibm_docs_crawler.fetcher import (
    FetchSettings,
    RequestRateLimiter,
    _backoff_seconds,
    _require_public_dns,
    _retry_after_seconds,
)
from app.ingestion.ibm_docs_crawler.models import FetchResult

from .registry import OfficialSourceTarget
from .urls import canonicalize_source_url


class OfficialRobotsError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfficialRobotsPolicy:
    target: OfficialSourceTarget
    user_agent: str
    parser: robotparser.RobotFileParser

    def require_allowed(self, url: str, *, path_prefix: str | None = None) -> None:
        canonical = canonicalize_source_url(
            url, allowed_host=self.target.allowed_host,
            path_prefix=path_prefix or self.target.docs_path_prefix,
        )
        if not self.parser.can_fetch(self.user_agent, canonical):
            raise OfficialRobotsError(f"robots.txt disallows: {canonical}")


def load_official_robots_policy(
    target: OfficialSourceTarget,
    user_agent: str,
    *,
    timeout_seconds: float = 30.0,
    max_bytes: int = 1_000_000,
    client: httpx.Client | None = None,
) -> OfficialRobotsPolicy:
    robots_url = f"{target.origin}/robots.txt"
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
    try:
        with client.stream(
            "GET",
            robots_url,
            headers={"User-Agent": user_agent, "Accept": "text/plain,*/*;q=0.1"},
        ) as response:
            if response.is_redirect:
                raise OfficialRobotsError("robots.txt redirects are not accepted")
            response.raise_for_status()
            canonical = canonicalize_source_url(
                str(response.url), allowed_host=target.allowed_host, path_prefix="/"
            )
            if canonical != robots_url:
                raise OfficialRobotsError("robots.txt resolved outside its canonical URL")
            content = bytearray()
            for part in response.iter_bytes():
                content.extend(part)
                if len(content) > max_bytes:
                    raise OfficialRobotsError("robots.txt exceeded the response-size limit")
        text = bytes(content).decode("utf-8", errors="replace")
        if not text.strip():
            raise OfficialRobotsError("robots.txt was empty")
        parser = robotparser.RobotFileParser(robots_url)
        parser.parse(text.splitlines())
        return OfficialRobotsPolicy(target, user_agent, parser)
    except httpx.HTTPError as exc:
        raise OfficialRobotsError(f"cannot load robots.txt: {exc}") from exc
    finally:
        if owns_client:
            client.close()


class OfficialSourceFetcher:
    def __init__(
        self,
        target: OfficialSourceTarget,
        policy: OfficialRobotsPolicy,
        settings: FetchSettings,
        *,
        client: httpx.Client,
        rate_limiter: RequestRateLimiter,
    ) -> None:
        self.target = target
        self.policy = policy
        self.settings = settings
        self.client = client
        self.rate_limiter = rate_limiter

    def fetch(
        self,
        url: str,
        *,
        conditional_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        requested = canonicalize_source_url(
            url,
            allowed_host=self.target.allowed_host,
            path_prefix=self.target.docs_path_prefix,
        )
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": (
                "text/markdown,text/plain;q=0.9,*/*;q=0.1"
                if self.target.content_format == "markdown"
                else "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"
            ),
            "Accept-Language": "en,en-US;q=0.8",
            **dict(conditional_headers or {}),
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries):
            try:
                result = self._request_with_redirects(requested, headers)
                if result.status_code not in {429, 500, 502, 503, 504}:
                    return result
                retry_after = _retry_after_seconds(result.headers.get("retry-after"))
                self._sleep(retry_after or _backoff_seconds(attempt))
            except (httpx.HTTPError, OSError, ValueError, OfficialRobotsError) as exc:
                last_error = exc
                if attempt + 1 < self.settings.max_retries:
                    self._sleep(_backoff_seconds(attempt))
        return FetchResult(
            requested_url=requested,
            final_url=requested,
            status_code=0,
            headers={},
            content=b"",
            error=f"{type(last_error).__name__}: {last_error}" if last_error else "retry limit exceeded",
        )

    def _request_with_redirects(
        self,
        requested: str,
        headers: dict[str, str],
    ) -> FetchResult:
        current = requested
        for _ in range(self.settings.max_redirects + 1):
            current = canonicalize_source_url(
                current,
                allowed_host=self.target.allowed_host,
                path_prefix=self.target.docs_path_prefix,
            )
            self.policy.require_allowed(current)
            if self.settings.validate_public_dns:
                _require_public_dns(current)
            self.rate_limiter.wait(self.settings.delay_seconds, time.sleep)
            with self.client.stream("GET", current, headers=headers) as response:
                response_headers = {
                    key.lower(): value for key, value in response.headers.items()
                }
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response had no Location header")
                    current = canonicalize_source_url(
                        location,
                        allowed_host=self.target.allowed_host,
                        path_prefix=self.target.docs_path_prefix,
                        base_url=current,
                    )
                    continue
                content = bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content) > self.settings.max_response_bytes:
                        raise ValueError(
                            f"response exceeded {self.settings.max_response_bytes} bytes"
                        )
                return FetchResult(
                    requested_url=requested,
                    final_url=current,
                    status_code=response.status_code,
                    headers=response_headers,
                    content=bytes(content),
                )
        raise ValueError("redirect limit exceeded")

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)
