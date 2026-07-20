"""Global test isolation for opt-in network and background-write features."""

from __future__ import annotations

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def isolate_live_feature_flags(monkeypatch):
    """Local .env rollout flags must never turn unit tests into live operations."""
    monkeypatch.setenv("ENABLE_ADAPTIVE_RETRIEVAL", "false")
    monkeypatch.setenv("ENABLE_LIVE_IBM_DOCS", "false")
    monkeypatch.setenv("ENABLE_LIVE_OFFICIAL_SOURCES", "false")
    monkeypatch.setenv("ENABLE_LIVE_DOCS_INDEXING", "false")
    monkeypatch.setenv("ENABLE_LIVE_WEB_SEARCH", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
