"""Fail-closed robots.txt policy for the IBM Docs crawler."""

from __future__ import annotations

from dataclasses import dataclass
from urllib import robotparser

import httpx

from .urls import canonicalize_url, validate_ibm_docs_url

ROBOTS_URL = "https://www.ibm.com/robots.txt"


class RobotsPolicyError(RuntimeError):
    """robots.txt could not be loaded or denies a requested URL."""


@dataclass(frozen=True)
class RobotsPolicy:
    user_agent: str
    raw_text: str
    parser: robotparser.RobotFileParser

    def allowed(self, url: str) -> bool:
        try:
            canonical = validate_ibm_docs_url(url)
        except ValueError:
            return False
        return self.parser.can_fetch(self.user_agent, canonical)

    def require_allowed(self, url: str) -> None:
        if not self.allowed(url):
            raise RobotsPolicyError(f"robots.txt or URL policy disallows: {url}")


def policy_from_text(text: str, user_agent: str) -> RobotsPolicy:
    parser = robotparser.RobotFileParser()
    parser.set_url(ROBOTS_URL)
    parser.parse(text.splitlines())
    return RobotsPolicy(user_agent=user_agent, raw_text=text, parser=parser)


def load_robots_policy(
    user_agent: str,
    *,
    timeout_seconds: float = 30.0,
    max_bytes: int = 1_000_000,
    client: httpx.Client | None = None,
) -> RobotsPolicy:
    """Load bounded robots.txt; redirects must canonicalize back to ROBOTS_URL."""
    owns_client = client is None
    client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
    try:
        current = ROBOTS_URL
        for _ in range(6):
            with client.stream(
                "GET",
                current,
                headers={"User-Agent": user_agent, "Accept": "text/plain,*/*;q=0.1"},
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise RobotsPolicyError("robots.txt redirect had no Location header")
                    redirected = canonicalize_url(location, current)
                    if redirected != ROBOTS_URL:
                        raise RobotsPolicyError("robots.txt redirected outside its canonical URL")
                    current = redirected
                    continue
                response.raise_for_status()
                content = bytearray()
                for part in response.iter_bytes():
                    content.extend(part)
                    if len(content) > max_bytes:
                        raise RobotsPolicyError("robots.txt exceeded the response-size limit")
                text = bytes(content).decode("utf-8", errors="replace")
                if not text.strip():
                    raise RobotsPolicyError("robots.txt was empty")
                return policy_from_text(text, user_agent)
        raise RobotsPolicyError("too many robots.txt redirects")
    except httpx.HTTPError as exc:
        raise RobotsPolicyError(f"cannot load robots.txt: {exc}") from exc
    finally:
        if owns_client:
            client.close()
