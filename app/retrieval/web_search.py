"""Modular, allowlisted web-search providers for low-confidence fallback."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    score: float | None = None


class WebSearchProvider(Protocol):
    def search(self, query: str, *, max_results: int) -> list[WebSearchResult]: ...


class DisabledWebSearchProvider:
    def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        return []


class HttpJsonWebSearchProvider:
    """Vendor-neutral adapter for an approved enterprise search gateway.

    Request JSON: ``{"query": str, "max_results": int, "allowed_domains": [...]}``
    Response JSON: ``{"results": [{"title": str, "url": str, "snippet": str}]}``
    """

    def __init__(
        self,
        endpoint: str,
        *,
        api_key: str = "",
        allowed_domains: tuple[str, ...],
        timeout_seconds: float = 12.0,
        provider_name: str = "enterprise-web-search",
        client: httpx.Client | None = None,
    ) -> None:
        endpoint_url = urlsplit(endpoint)
        if endpoint_url.scheme != "https" or not endpoint_url.hostname:
            raise ValueError("live web search endpoint must be an absolute HTTPS URL")
        if not allowed_domains:
            raise ValueError("at least one live web search domain must be allowlisted")
        self.endpoint = endpoint
        self.api_key = api_key
        self.allowed_domains = tuple(domain.lower().strip(".") for domain in allowed_domains)
        self.timeout_seconds = timeout_seconds
        self.provider_name = provider_name
        self._client = client

    def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                self.endpoint,
                headers=headers,
                json={
                    "query": query,
                    "max_results": max(1, max_results),
                    "allowed_domains": list(self.allowed_domains),
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                client.close()
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        output: list[WebSearchResult] = []
        seen: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            title = str(item.get("title") or "").strip()
            if url in seen or len(snippet) < 40 or not _url_is_allowed(url, self.allowed_domains):
                continue
            seen.add(url)
            output.append(WebSearchResult(
                title=title or url,
                url=url,
                snippet=snippet,
                provider=self.provider_name,
            ))
        output.sort(key=lambda result: (_domain_priority(result.url), result.title.lower()))
        return output[:max(1, max_results)]


class TavilyWebSearchProvider:
    """Tavily Search adapter restricted to explicitly allowlisted domains."""

    def __init__(
        self,
        *,
        api_key: str,
        allowed_domains: tuple[str, ...],
        endpoint: str,
        timeout_seconds: float = 30.0,
        max_content_chars: int = 6000,
        search_depth: str = "advanced",
        client: httpx.Client | None = None,
    ) -> None:
        endpoint_url = urlsplit(endpoint)
        if endpoint_url.scheme != "https" or endpoint_url.hostname != "api.tavily.com":
            raise ValueError("Tavily search endpoint must be api.tavily.com over HTTPS")
        if not api_key.strip():
            raise ValueError("Tavily web search requires an API key")
        domains = tuple(
            dict.fromkeys(domain.lower().strip(".") for domain in allowed_domains if domain)
        )
        if not domains or len(domains) > 300:
            raise ValueError("Tavily web search requires 1-300 allowlisted domains")
        self.endpoint = endpoint
        self.api_key = api_key
        self.allowed_domains = domains
        self.timeout_seconds = timeout_seconds
        self.max_content_chars = max(500, min(20_000, max_content_chars))
        normalized_depth = search_depth.strip().lower()
        if normalized_depth not in {"basic", "advanced"}:
            raise ValueError("Tavily search depth must be 'basic' or 'advanced'")
        self.search_depth = normalized_depth
        self._client = client

    def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        limit = max(1, min(20, max_results))
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "query": query,
                    "search_depth": self.search_depth,
                    "max_results": limit,
                    "include_domains": list(self.allowed_domains),
                    "include_answer": False,
                    "include_raw_content": "markdown",
                    "include_images": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                client.close()

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        output: list[WebSearchResult] = []
        seen: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = _select_relevant_content(
                query,
                str(item.get("content") or ""),
                str(item.get("raw_content") or ""),
                max_chars=self.max_content_chars,
            )
            if url in seen or len(snippet) < 40 or not _url_is_allowed(url, self.allowed_domains):
                continue
            seen.add(url)
            output.append(WebSearchResult(
                title=title or url,
                url=url,
                snippet=snippet,
                provider="tavily-web-search",
                score=_optional_score(item.get("score")),
            ))
        # Tavily already returns results in relevance order. Do not force IBM
        # Docs pages above more relevant IBM Newsroom, announcement, or support
        # pages; that previously buried exact event and lifecycle answers.
        return output[:limit]


class OpenAIResponsesWebSearchProvider:
    """Optional OpenAI Responses API adapter using the hosted web_search tool.

    Search is forced, live access stays enabled, and the provider is restricted
    to the same explicit domain allowlist used by the enterprise gateway.
    Returned candidates are source-linked search summaries, not a replacement
    for fetching and caching official documentation pages.
    """

    def __init__(
        self,
        *,
        api_key: str,
        allowed_domains: tuple[str, ...],
        model: str = "gpt-5.5",
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        endpoint_url = urlsplit(endpoint)
        if endpoint_url.scheme != "https" or endpoint_url.hostname != "api.openai.com":
            raise ValueError("OpenAI web search endpoint must be api.openai.com over HTTPS")
        if not api_key.strip():
            raise ValueError("OpenAI web search requires an API key")
        domains = tuple(
            dict.fromkeys(domain.lower().strip(".") for domain in allowed_domains if domain)
        )
        if not domains or len(domains) > 100:
            raise ValueError("OpenAI web search requires 1-100 allowlisted domains")
        self.endpoint = endpoint
        self.api_key = api_key
        self.allowed_domains = domains
        self.model = model.strip() or "gpt-5.5"
        self.timeout_seconds = timeout_seconds
        self._client = client

    def search(self, query: str, *, max_results: int) -> list[WebSearchResult]:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": self.model,
                    "tools": [{
                        "type": "web_search",
                        "external_web_access": True,
                        "search_context_size": "low",
                        "filters": {"allowed_domains": list(self.allowed_domains)},
                    }],
                    "tool_choice": "required",
                    "include": ["web_search_call.action.sources"],
                    "input": (
                        "Search the allowed official documentation domains for this "
                        "technical question. Summarize only what the sources support "
                        "and retain exact commands when present.\n\n" + query
                    ),
                },
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if owns_client:
                client.close()
        return _parse_openai_web_results(
            payload,
            allowed_domains=self.allowed_domains,
            max_results=max_results,
        )


def _parse_openai_web_results(
    payload: object,
    *,
    allowed_domains: tuple[str, ...],
    max_results: int,
) -> list[WebSearchResult]:
    if not isinstance(payload, dict):
        return []
    output_items = payload.get("output")
    if not isinstance(output_items, list):
        return []
    response_texts: list[str] = []
    source_records: list[tuple[str, str]] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        action = item.get("action")
        if isinstance(action, dict):
            sources = action.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if isinstance(source, dict):
                        source_records.append((
                            str(source.get("url") or "").strip(),
                            str(source.get("title") or "").strip(),
                        ))
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if text:
                response_texts.append(text)
            annotations = part.get("annotations")
            if isinstance(annotations, list):
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        continue
                    if annotation.get("type") != "url_citation":
                        continue
                    source_records.append((
                        str(annotation.get("url") or "").strip(),
                        str(annotation.get("title") or "").strip(),
                    ))
    snippet = "\n\n".join(response_texts).strip()[:4000]
    if len(snippet) < 40:
        return []
    results: list[WebSearchResult] = []
    seen: set[str] = set()
    for url, title in source_records:
        if url in seen or not _url_is_allowed(url, allowed_domains):
            continue
        seen.add(url)
        results.append(WebSearchResult(
            title=title or url,
            url=url,
            snippet=snippet,
            provider="openai-responses-web-search",
        ))
    return results[:max(1, max_results)]


def _optional_score(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _url_is_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.lower().strip(".")
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


def _domain_priority(url: str) -> int:
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()
    if host in {"ibm.com", "www.ibm.com"} and path.startswith("/docs/"):
        return 0
    if host == "support.ibm.com" or host.endswith(".support.ibm.com"):
        return 1
    if host == "cloud.ibm.com" or host.endswith(".cloud.ibm.com"):
        return 2
    if host.endswith(".ibm.com") or host == "ibm.com":
        return 3
    if host == "docs.redhat.com" or host.endswith(".docs.redhat.com"):
        return 4
    if host == "access.redhat.com" or host.endswith(".access.redhat.com"):
        return 5
    if host == "developers.redhat.com" or host.endswith(".developers.redhat.com"):
        return 6
    return 10


_SEARCH_STOP_WORDS = frozenset({
    "about", "and", "are", "does", "for", "from", "how", "ibm", "into",
    "official", "the", "this", "what", "when", "where", "which", "with",
})


def _select_relevant_content(
    query: str,
    content: str,
    raw_content: str,
    *,
    max_chars: int,
) -> str:
    """Build a bounded, query-focused excerpt from Tavily's extracted page."""
    fallback = content.strip()
    raw = raw_content.strip()
    if not raw:
        return fallback[:max_chars]

    terms = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9_.-]+", query.casefold())
        if token not in _SEARCH_STOP_WORDS and len(token) > 2
    }
    blocks = [
        block.strip()
        for block in re.split(r"\n{2,}|(?=^#{1,6}\s)", raw, flags=re.MULTILINE)
        if block.strip()
    ]
    scored: list[tuple[int, int]] = []
    for index, block in enumerate(blocks):
        lowered = block.casefold()
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((score, index))
    selected_indices: set[int] = set()
    for _score, index in sorted(scored, key=lambda item: (-item[0], item[1]))[:8]:
        selected_indices.add(index)
        if index + 1 < len(blocks):
            selected_indices.add(index + 1)

    # Put query-matched raw page sections first. Tavily's short ``content``
    # summary is useful as a fallback, but it is often generic; placing it first
    # allowed a long overview to consume the character budget before the exact
    # command, lifecycle statement, or announcement from ``raw_content``.
    selected = [
        blocks[index]
        for index in sorted(selected_indices)
        if blocks[index]
    ]
    if fallback and fallback not in selected:
        selected.append(fallback)
    if not selected:
        selected = blocks[:4]

    output: list[str] = []
    used = 0
    for block in selected:
        remaining = max_chars - used
        if remaining <= 0:
            break
        value = block[:remaining].strip()
        if not value:
            continue
        output.append(value)
        used += len(value) + 2
    return "\n\n".join(output).strip()
