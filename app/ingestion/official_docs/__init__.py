"""Adapters for allowlisted official IBM documentation sources."""

from .registry import (
    OfficialSourceRegistry,
    OfficialSourceTarget,
    get_enabled_source,
    get_enabled_sources,
    load_official_source_registry,
)

__all__ = [
    "OfficialSourceRegistry",
    "OfficialSourceTarget",
    "get_enabled_source",
    "get_enabled_sources",
    "load_official_source_registry",
]
