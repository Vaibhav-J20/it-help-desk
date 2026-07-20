"""Bounded, rate-limited HTTP fetching with redirect validation."""

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import ipaddress
import random
import socket
import threading
import time
from typing import Callable, Mapping

import httpx

from .models import FetchResult
from .robots import RobotsPolicy
from .urls import is_in_target_scope, validate_ibm_docs_url


@dataclass(frozen=True)
class FetchSettings:
    user_agent: str
    delay_seconds: float = 1.5
    timeout_seconds: float = 30.0
    max_retries: int = 4
    max_response_bytes: int = 20_000_000
    max_redirects: int = 5
    validate_public_dns: bool = True


class RequestRateLimiter:
    """Thread-safe request-start limiter shared by concurrent fetch workers."""

    def __init__(self) -> None:
        self._last_request_at = 0.0
        self._lock = threading.Lock()

    def wait(self, delay_seconds: float, sleep: Callable[[float], None]) -> None:
        delay = max(delay_seconds, 1.0)
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if self._last_request_at and elapsed < delay:
                sleep(delay - elapsed)
            self._last_request_at = time.monotonic()


class PoliteFetcher:
    """Policy-checked fetcher; a shared limiter makes concurrent use polite."""

    def __init__(
        self,
        policy: RobotsPolicy,
        settings: FetchSettings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rate_limiter: RequestRateLimiter | None = None,
    ) -> None:
        self.policy = policy
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=settings.timeout_seconds,
            follow_redirects=False,
        )
        self.sleep = sleep
        self._rate_limiter = rate_limiter or RequestRateLimiter()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "PoliteFetcher":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        *,
        conditional_headers: Mapping[str, str] | None = None,
        accept: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        scope_prefix: str = "/docs",
    ) -> FetchResult:
        requested = validate_ibm_docs_url(url)
        headers = {
            "User-Agent": self.settings.user_agent,
            "Accept": accept,
            "Accept-Language": "en,en-US;q=0.8",
        }
        headers.update(dict(conditional_headers or {}))

        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries):
            try:
                result = self._request_with_redirects(requested, headers, scope_prefix)
                if result.status_code not in {429, 500, 502, 503, 504}:
                    return result
                retry_after = _retry_after_seconds(result.headers.get("retry-after"))
                self.sleep(retry_after or _backoff_seconds(attempt))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.settings.max_retries:
                    self.sleep(_backoff_seconds(attempt))

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
        headers: Mapping[str, str],
        scope_prefix: str,
    ) -> FetchResult:
        current = requested
        for _ in range(self.settings.max_redirects + 1):
            current = validate_ibm_docs_url(current)
            if not is_in_target_scope(current, scope_prefix):
                raise ValueError(f"URL escaped the approved path scope: {scope_prefix}")
            self.policy.require_allowed(current)
            if self.settings.validate_public_dns:
                _require_public_dns(current)
            self._rate_limit()

            with self.client.stream("GET", current, headers=dict(headers)) as response:
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect response had no Location header")
                    current = validate_ibm_docs_url(str(httpx.URL(current).join(location)))
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

    def _rate_limit(self) -> None:
        self._rate_limiter.wait(self.settings.delay_seconds, self.sleep)


def _require_public_dns(url: str) -> None:
    host = httpx.URL(url).host
    if not host:
        raise ValueError("URL has no host")
    for answer in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(answer[4][0])
        if not address.is_global:
            raise ValueError(f"host resolved to a non-public address: {address}")


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return min(float(value), 60.0)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
            return max(0.0, min(seconds, 60.0))
        except (TypeError, ValueError, OverflowError):
            return None


def _backoff_seconds(attempt: int) -> float:
    return min(30.0, (2 ** attempt) + random.uniform(0.0, 0.25))
