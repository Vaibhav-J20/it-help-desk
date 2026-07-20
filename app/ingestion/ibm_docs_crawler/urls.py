"""Canonical URL and scope enforcement for www.ibm.com/docs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

IBM_DOCS_HOST = "www.ibm.com"
_ALLOWED_SCHEMES = {"https"}
_SEMANTIC_QUERY_PARAMS = {"topic", "view"}
_TRACKING_QUERY_PARAMS = {
    "cm_mmc", "cm_re", "cm_sp", "lnk", "ref", "source",
    "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term",
}


class URLPolicyError(ValueError):
    """Raised when a URL violates the crawler's origin or scope policy."""


def canonicalize_url(url: str, base_url: str = "https://www.ibm.com") -> str:
    """Return the stable, fragment-free form of an IBM Docs URL."""
    absolute = urljoin(base_url, url.strip())
    parts = urlsplit(absolute)
    host = (parts.hostname or "").lower()
    if host == "ibm.com":
        host = IBM_DOCS_HOST
    if parts.username or parts.password or parts.port:
        raise URLPolicyError("Credentials and explicit ports are not permitted")
    if parts.scheme.lower() not in {"http", "https"} or host != IBM_DOCS_HOST:
        raise URLPolicyError(f"URL is outside the approved IBM Docs origin: {url}")

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in _TRACKING_QUERY_PARAMS:
            continue
        if lowered in _SEMANTIC_QUERY_PARAMS:
            kept.append((lowered, value))
    kept.sort()
    return urlunsplit(("https", host, path, urlencode(kept), ""))


def validate_ibm_docs_url(url: str) -> str:
    canonical = canonicalize_url(url)
    parts = urlsplit(canonical)
    if parts.scheme not in _ALLOWED_SCHEMES or parts.hostname != IBM_DOCS_HOST:
        raise URLPolicyError(f"Only https://{IBM_DOCS_HOST} is allowed")
    if not path_matches_prefix(parts.path, "/docs"):
        raise URLPolicyError("Only /docs URLs are permitted")
    if path_matches_prefix(parts.path.lower(), "/docs/api"):
        raise URLPolicyError("/docs/api is explicitly blocked")
    return canonical


def path_matches_prefix(path: str, prefix: str) -> bool:
    """Match a path segment boundary, avoiding `/foo` matching `/foobar`."""
    clean_path = "/" + path.strip("/")
    clean_prefix = "/" + prefix.strip("/")
    return clean_path == clean_prefix or clean_path.startswith(clean_prefix + "/")


def is_in_target_scope(url: str, docs_path_prefix: str) -> bool:
    try:
        canonical = validate_ibm_docs_url(url)
    except (URLPolicyError, ValueError):
        return False
    return path_matches_prefix(urlsplit(canonical).path, docs_path_prefix)
