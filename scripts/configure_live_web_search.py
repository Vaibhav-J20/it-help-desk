#!/usr/bin/env python3
"""Safely configure and verify official-domain live web search."""

from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.retrieval.web_search import (
    OpenAIResponsesWebSearchProvider,
    TavilyWebSearchProvider,
)

DEFAULT_ENV = ROOT / ".env"
DEFAULT_DOMAINS = (
    "www.ibm.com,support.ibm.com,cloud.ibm.com,redbooks.ibm.com,"
    "docs.redhat.com,access.redhat.com,developers.redhat.com"
)
PROVIDER_ENDPOINTS = {
    "tavily": "https://api.tavily.com/search",
    "openai": "https://api.openai.com/v1/responses",
}


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Upsert selected dotenv keys without printing or disturbing other secrets."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in pending and not line.lstrip().startswith("#"):
            output.append(f"{key}={pending.pop(key)}")
        else:
            output.append(line)
    if pending:
        if output and output[-1].strip():
            output.append("")
        output.append("# Official-domain live web search")
        output.extend(f"{key}={value}" for key, value in pending.items())

    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _settings(path: Path) -> Settings:
    return Settings(_env_file=path)


def _key(settings: Settings) -> str:
    key = settings.live_web_search_api_key.strip()
    if settings.live_web_search_provider.strip().lower() == "openai":
        return key or os.getenv("OPENAI_API_KEY", "").strip()
    return key


def _configuration_errors(settings: Settings) -> list[str]:
    errors: list[str] = []
    if not settings.enable_live_web_search:
        errors.append("ENABLE_LIVE_WEB_SEARCH is false")
    if settings.live_web_search_provider.strip().lower() not in {"openai", "tavily"}:
        errors.append("LIVE_WEB_SEARCH_PROVIDER must be openai or tavily")
    if not settings.live_web_search_endpoint.strip():
        errors.append("LIVE_WEB_SEARCH_ENDPOINT is not configured")
    if not _key(settings):
        errors.append(
            "no LIVE_WEB_SEARCH_API_KEY is configured for the selected provider"
        )
    domains = [
        value.strip()
        for value in settings.live_web_search_allowed_domains.split(",")
        if value.strip()
    ]
    if not domains:
        errors.append("LIVE_WEB_SEARCH_ALLOWED_DOMAINS is empty")
    return errors


def _check(path: Path, *, probe: bool) -> int:
    settings = _settings(path)
    errors = _configuration_errors(settings)
    print(f"Provider: {settings.live_web_search_provider}")
    print(f"Model: {settings.live_web_search_model}")
    print(f"Enabled: {settings.enable_live_web_search}")
    print(f"API key configured: {bool(_key(settings))}")
    print(f"Allowed domains: {settings.live_web_search_allowed_domains}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not probe:
        print("Configuration is ready. Restart FastAPI to load it.")
        return 0

    provider_name = settings.live_web_search_provider.strip().lower()
    provider_arguments = {
        "api_key": _key(settings),
        "allowed_domains": tuple(
            value.strip()
            for value in settings.live_web_search_allowed_domains.split(",")
            if value.strip()
        ),
        "timeout_seconds": max(1.0, settings.live_web_search_timeout_seconds),
    }
    if provider_name == "tavily":
        provider = TavilyWebSearchProvider(
            **provider_arguments,
            endpoint=settings.live_web_search_endpoint,
            max_content_chars=max(500, settings.live_web_search_content_chars),
        )
    else:
        provider = OpenAIResponsesWebSearchProvider(
            **provider_arguments,
            model=settings.live_web_search_model,
        )
    results = provider.search(
        "What is IBM Concert? official IBM documentation",
        max_results=3,
    )
    if not results:
        print("ERROR: provider returned no allowlisted IBM sources", file=sys.stderr)
        return 2
    print("Live probe succeeded:")
    for result in results:
        print(f"- {result.title}: {result.url}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--provider", choices=("tavily", "openai"), default="tavily")
    args = parser.parse_args()
    path = args.env_file.expanduser().resolve()

    if args.disable:
        _write_env(path, {"ENABLE_LIVE_WEB_SEARCH": "false"})
        print(f"Live web search disabled in {path}.")
        return 0
    if args.check or args.probe:
        return _check(path, probe=args.probe)

    key = getpass(f"{args.provider.title()} API key (input hidden): ").strip()
    if len(key) < 20 or any(character.isspace() for character in key):
        print("ERROR: API key is empty or malformed", file=sys.stderr)
        return 2
    _write_env(path, {
        "ENABLE_LIVE_WEB_SEARCH": "true",
        "LIVE_WEB_SEARCH_PROVIDER": args.provider,
        "LIVE_WEB_SEARCH_ENDPOINT": PROVIDER_ENDPOINTS[args.provider],
        "LIVE_WEB_SEARCH_API_KEY": key,
        "LIVE_WEB_SEARCH_ALLOWED_DOMAINS": DEFAULT_DOMAINS,
        "LIVE_WEB_SEARCH_TIMEOUT_SECONDS": "30",
        "LIVE_WEB_SEARCH_MAX_RESULTS": "5",
        "LIVE_WEB_SEARCH_CONTENT_CHARS": "6000",
    })
    print(f"Configured official-domain web search in {path}.")
    print("Restart FastAPI, then run this script with --probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
