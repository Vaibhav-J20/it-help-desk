"""Governed IBM Documentation crawler and staging pipeline."""

from .registry import CrawlTarget, get_enabled_target, load_registry

__all__ = ["CrawlTarget", "get_enabled_target", "load_registry"]
