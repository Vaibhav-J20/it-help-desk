"""Strict URL policy for allowlisted official documentation hosts."""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


def canonicalize_source_url(
    url: str,
    *,
    allowed_host: str,
    path_prefix: str = "/",
    base_url: str | None = None,
) -> str:
    raw = urljoin(base_url, url) if base_url else url
    if any(ord(character) < 32 for character in raw):
        raise ValueError("URL contains control characters")
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https":
        raise ValueError("official documentation URLs must use HTTPS")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("official documentation URLs cannot contain credentials or ports")
    host = (parsed.hostname or "").lower().rstrip(".")
    expected = allowed_host.lower().rstrip(".")
    if host != expected:
        raise ValueError(f"URL host is not allowlisted: {host or '<missing>'}")

    decoded_path = unquote(parsed.path or "/")
    if "\\" in decoded_path or "\x00" in decoded_path:
        raise ValueError("URL path contains unsafe characters")
    normalized_path = posixpath.normpath(decoded_path)
    if not normalized_path.startswith("/"):
        normalized_path = "/" + normalized_path
    if decoded_path.endswith("/") and normalized_path != "/":
        normalized_path += "/"
    normalized_prefix = "/" + path_prefix.strip("/") if path_prefix != "/" else "/"
    if normalized_prefix != "/" and not (
        normalized_path == normalized_prefix
        or normalized_path.startswith(normalized_prefix.rstrip("/") + "/")
    ):
        raise ValueError(f"URL escaped the allowlisted path: {normalized_prefix}")
    if normalized_path.startswith("/cdn-cgi/"):
        raise ValueError("URL path is explicitly excluded")
    return urlunsplit(("https", expected, normalized_path, parsed.query, ""))


def is_source_page_url(
    url: str,
    *,
    allowed_host: str,
    path_prefix: str,
    content_format: str = "markdown",
) -> bool:
    try:
        canonical = canonicalize_source_url(
            url, allowed_host=allowed_host, path_prefix=path_prefix
        )
    except ValueError:
        return False
    path = urlsplit(canonical).path.lower()
    if content_format == "markdown":
        return path.endswith(".md")
    if content_format == "html":
        # Friendly documentation routes often have no extension. Explicitly
        # reject common static assets and metadata endpoints.
        return not path.endswith((
            ".css", ".js", ".json", ".xml", ".xml.gz", ".txt", ".png",
            ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf",
            ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf", ".map",
        ))
    return False
