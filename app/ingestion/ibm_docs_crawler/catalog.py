"""Searchable metadata catalog and lightweight documentation knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterable
from urllib.parse import parse_qsl, urlsplit

from .models import ExtractedDocument, SitemapEntry
from .registry import CrawlTarget

_SEARCH_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.-]+", re.IGNORECASE)
_STOP_WORDS = frozenset({
    "a", "about", "an", "and", "are", "brief", "current", "description",
    "do", "docs", "documentation", "does", "explain", "for", "give", "help",
    "how", "i", "ibm", "in", "info", "information", "is", "it", "latest",
    "list", "me", "of", "on", "product", "products", "released", "tell", "the",
    "this", "to", "version", "week", "what", "when", "where", "which", "with",
})

_GENERIC_PRODUCT_WORDS = frozenset({
    "analytics", "cloud", "consulting", "data", "management", "manager",
    "observability", "pak", "platform", "security", "service", "services",
    "software", "solution", "solutions", "storage", "system", "systems",
    "watsonx",
})


@dataclass(frozen=True)
class CatalogPage:
    canonical_url: str
    source_id: str
    product_id: str
    product_name: str
    product_family: str
    domain_id: str
    version_id: str
    product_version: str
    title: str
    description: str
    breadcrumbs: tuple[str, ...]
    route_type: str
    topic_slug: str
    parent_url: str | None
    last_modified: str | None
    sitemap_url: str | None
    content_hash: str | None
    relevance_score: float = 0.0


@dataclass(frozen=True)
class CatalogTarget:
    """One globally discovered IBM Docs product/version documentation set."""

    content_key: str
    product_id: str
    product_key: str
    product_name: str
    product_family: str
    product_url_key: str
    version_id: str
    product_version: str
    docs_path_prefix: str
    seed_url: str
    sitemap_url: str
    aliases: tuple[str, ...]
    last_modified: str | None
    is_latest: bool
    relevance_score: float = 0.0

    def to_crawl_target(self) -> CrawlTarget:
        return CrawlTarget(
            product_id=self.product_id,
            product_name=self.product_name,
            domain_id="ibm_products",
            docs_path_prefix=self.docs_path_prefix,
            aliases=self.aliases,
            version_id=self.version_id,
            product_version=self.product_version,
            seed_url=self.seed_url,
            max_pages=100_000,
            sitemap_url=self.sitemap_url,
            run_context={
                "mode": "global-public-ibm-docs",
                "content_key": self.content_key,
                "registry_enabled": "global-catalog",
            },
        )


@dataclass(frozen=True)
class TocTopic:
    canonical_url: str
    title: str
    topic_id: str
    breadcrumbs: tuple[str, ...]
    parent_url: str | None
    ordinal: int


@dataclass(frozen=True)
class ProductNode:
    product_key: str
    product_name: str
    product_url_key: str
    aliases: tuple[str, ...] = ()


class MetadataCatalog:
    """SQLite catalog with FTS5 when available and a deterministic fallback."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.db_path = data_dir / "state" / "crawl.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS catalog_pages (
                    canonical_url TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL DEFAULT 'ibm-docs',
                    product_id TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    product_family TEXT NOT NULL,
                    domain_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    product_version TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    breadcrumbs_json TEXT NOT NULL DEFAULT '[]',
                    route_type TEXT NOT NULL,
                    topic_slug TEXT NOT NULL,
                    parent_url TEXT,
                    last_modified TEXT,
                    sitemap_url TEXT,
                    content_hash TEXT,
                    discovered_at TEXT NOT NULL,
                    enriched_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_product_version
                    ON catalog_pages(product_id, version_id);
                CREATE TABLE IF NOT EXISTS catalog_edges (
                    source_url TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    PRIMARY KEY (source_url, target_url, edge_type)
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_edges_source
                    ON catalog_edges(source_url, edge_type);
                CREATE TABLE IF NOT EXISTS catalog_targets (
                    content_key TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL,
                    product_key TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    product_family TEXT NOT NULL,
                    product_url_key TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    product_version TEXT NOT NULL,
                    docs_path_prefix TEXT NOT NULL,
                    seed_url TEXT NOT NULL,
                    sitemap_url TEXT NOT NULL,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    last_modified TEXT,
                    is_latest INTEGER NOT NULL DEFAULT 0,
                    discovered_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_targets_product
                    ON catalog_targets(product_id, product_version);
                CREATE INDEX IF NOT EXISTS idx_catalog_targets_key
                    ON catalog_targets(product_key, version_id);
                CREATE TABLE IF NOT EXISTS catalog_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    canonical_url TEXT,
                    label TEXT NOT NULL DEFAULT '',
                    product_id TEXT,
                    version_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    discovered_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_nodes_type
                    ON catalog_nodes(node_type, product_id, version_id);
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(catalog_pages)").fetchall()
            }
            if "source_id" not in columns:
                connection.execute(
                    "ALTER TABLE catalog_pages ADD COLUMN source_id TEXT NOT NULL "
                    "DEFAULT 'ibm-docs'"
                )
            if "description" not in columns:
                connection.execute(
                    "ALTER TABLE catalog_pages ADD COLUMN description TEXT NOT NULL DEFAULT ''"
                )
            if "toc_enriched_at" not in columns:
                connection.execute(
                    "ALTER TABLE catalog_pages ADD COLUMN toc_enriched_at TEXT"
                )
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS catalog_pages_fts USING fts5(
                        canonical_url UNINDEXED,
                        title,
                        breadcrumbs,
                        topic_slug,
                        route_type,
                        searchable_text,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
                self._fts_available = True
            except sqlite3.OperationalError:
                self._fts_available = False
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS catalog_targets_fts USING fts5(
                        content_key UNINDEXED,
                        product_name,
                        product_family,
                        product_url_key,
                        product_version,
                        aliases,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
            except sqlite3.OperationalError:
                pass

    def upsert_target(self, target: CatalogTarget) -> None:
        """Store one product/version target and its structural graph nodes."""
        now = _now()
        product_node = f"ibmdocs://product/{target.product_key}"
        version_node = f"ibmdocs://version/{target.content_key}"
        sitemap_node = target.sitemap_url
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_targets (
                    content_key, product_id, product_key, product_name,
                    product_family, product_url_key, version_id, product_version,
                    docs_path_prefix, seed_url, sitemap_url, aliases_json,
                    last_modified, is_latest, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_key) DO UPDATE SET
                    product_id=excluded.product_id,
                    product_key=excluded.product_key,
                    product_name=excluded.product_name,
                    product_family=excluded.product_family,
                    product_url_key=excluded.product_url_key,
                    version_id=excluded.version_id,
                    product_version=excluded.product_version,
                    docs_path_prefix=excluded.docs_path_prefix,
                    seed_url=excluded.seed_url,
                    sitemap_url=excluded.sitemap_url,
                    aliases_json=excluded.aliases_json,
                    last_modified=excluded.last_modified,
                    is_latest=excluded.is_latest,
                    discovered_at=excluded.discovered_at
                """,
                (
                    target.content_key, target.product_id, target.product_key,
                    target.product_name, target.product_family,
                    target.product_url_key, target.version_id,
                    target.product_version, target.docs_path_prefix,
                    target.seed_url, target.sitemap_url,
                    json.dumps(target.aliases), target.last_modified,
                    int(target.is_latest), now,
                ),
            )
            self._upsert_node(
                connection,
                node_id=product_node,
                node_type="product",
                canonical_url=f"https://www.ibm.com/docs/en/{target.product_url_key}",
                label=target.product_name,
                product_id=target.product_id,
                version_id=None,
                metadata={
                    "product_key": target.product_key,
                    "aliases": list(target.aliases),
                    "product_family": target.product_family,
                },
                discovered_at=now,
            )
            self._upsert_node(
                connection,
                node_id=version_node,
                node_type="version",
                canonical_url=target.seed_url,
                label=f"{target.product_name} {target.product_version}",
                product_id=target.product_id,
                version_id=target.version_id,
                metadata={"content_key": target.content_key},
                discovered_at=now,
            )
            self._upsert_node(
                connection,
                node_id=sitemap_node,
                node_type="sitemap",
                canonical_url=target.sitemap_url,
                label=target.content_key,
                product_id=target.product_id,
                version_id=target.version_id,
                metadata={"last_modified": target.last_modified},
                discovered_at=now,
            )
            _upsert_edge(connection, product_node, version_node, "has_version", now)
            _upsert_edge(connection, version_node, sitemap_node, "has_sitemap", now)
            self._refresh_target_fts(connection, target.content_key)

    def upsert_product_node(self, product: ProductNode) -> None:
        """Store a product even before any version sitemap has been processed."""
        now = _now()
        product_id = _global_product_id(product.product_key)
        with self._connect() as connection:
            self._upsert_node(
                connection,
                node_id=f"ibmdocs://product/{product.product_key}",
                node_type="product",
                canonical_url=f"https://www.ibm.com/docs/en/{product.product_url_key}",
                label=product.product_name,
                product_id=product_id,
                version_id=None,
                metadata={
                    "product_key": product.product_key,
                    "product_url_key": product.product_url_key,
                    "aliases": list(product.aliases),
                },
                discovered_at=now,
            )

    def connect_product_family(
        self,
        parent_product_key: str,
        child_product_key: str,
    ) -> None:
        now = _now()
        with self._connect() as connection:
            _upsert_edge(
                connection,
                f"ibmdocs://product/{parent_product_key}",
                f"ibmdocs://product/{child_product_key}",
                "contains_product",
                now,
            )

    def connect_discovered_product_hierarchy(self) -> None:
        """Connect products using the nested canonical IBM Docs URL paths."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT product_key, product_url_key
                FROM catalog_targets
                GROUP BY product_key, product_url_key
                ORDER BY LENGTH(product_url_key) DESC
                """
            ).fetchall()
        pairs = [
            (str(row["product_key"]), str(row["product_url_key"]).strip("/"))
            for row in rows
        ]
        for child_key, child_path in pairs:
            parent = next((
                (parent_key, parent_path)
                for parent_key, parent_path in pairs
                if parent_key != child_key
                and child_path.startswith(parent_path + "/")
            ), None)
            if parent is not None:
                self.connect_product_family(parent[0], child_key)

    def normalize_global_product_identities(self) -> None:
        """Unify versions, hardware models, and renamed product paths.

        Two documentation sets represent one product when they share a
        canonical product path or a versioned IBM content-key family. This
        union handles both model-specific content keys under one product path
        and product renames that retain one content family.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM catalog_targets ORDER BY content_key"
            ).fetchall()
        targets = [_target_from_row(row) for row in rows]
        if not targets:
            return

        parents = list(range(len(targets)))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        by_path: dict[str, int] = {}
        by_family: dict[str, int] = {}
        for index, target in enumerate(targets):
            path = target.product_url_key.casefold().strip("/")
            if path in by_path:
                union(index, by_path[path])
            else:
                by_path[path] = index
            family = _content_family_key(target.content_key)
            if family != target.content_key:
                if family in by_family:
                    union(index, by_family[family])
                else:
                    by_family[family] = index

        components: dict[int, list[CatalogTarget]] = {}
        for index, target in enumerate(targets):
            components.setdefault(find(index), []).append(target)

        now = _now()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM catalog_edges WHERE edge_type IN "
                "('has_version', 'contains_product')"
            )
            connection.execute("DELETE FROM catalog_nodes WHERE node_type = 'product'")
            self._upsert_node(
                connection,
                node_id="https://www.ibm.com/docs/en",
                node_type="root",
                canonical_url="https://www.ibm.com/docs/en",
                label="IBM Documentation",
                product_id=None,
                version_id=None,
                metadata={},
                discovered_at=now,
            )
            for component in components.values():
                latest = max(component, key=_catalog_target_latest_sort_key)
                families = sorted({
                    _content_family_key(target.content_key)
                    for target in component
                    if _content_family_key(target.content_key) != target.content_key
                })
                if families:
                    product_key = "FAMILY_" + families[0]
                else:
                    product_key = _path_product_key(latest.product_url_key)
                product_id = global_product_id(product_key)
                product_node = f"ibmdocs://product/{product_key}"
                connection.executemany(
                    """
                    UPDATE catalog_targets
                    SET product_key = ?, product_id = ?
                    WHERE content_key = ?
                    """,
                    [
                        (product_key, product_id, target.content_key)
                        for target in component
                    ],
                )
                self._upsert_node(
                    connection,
                    node_id=product_node,
                    node_type="product",
                    canonical_url=(
                        f"https://www.ibm.com/docs/en/{latest.product_url_key}"
                    ),
                    label=latest.product_name,
                    product_id=product_id,
                    version_id=None,
                    metadata={
                        "product_key": product_key,
                        "known_paths": sorted({
                            target.product_url_key for target in component
                        }),
                        "aliases": sorted({
                            alias
                            for target in component
                            for alias in target.aliases
                        }),
                    },
                    discovered_at=now,
                )
                _upsert_edge(
                    connection,
                    "https://www.ibm.com/docs/en",
                    product_node,
                    "contains_product",
                    now,
                )
                for target in component:
                    _upsert_edge(
                        connection,
                        product_node,
                        f"ibmdocs://version/{target.content_key}",
                        "has_version",
                        now,
                    )

            connection.execute(
                """
                UPDATE catalog_pages
                SET product_id = (
                        SELECT t.product_id FROM catalog_targets AS t
                        WHERE t.content_key = catalog_pages.version_id
                    ),
                    product_name = (
                        SELECT t.product_name FROM catalog_targets AS t
                        WHERE t.content_key = catalog_pages.version_id
                    ),
                    product_family = (
                        SELECT t.product_family FROM catalog_targets AS t
                        WHERE t.content_key = catalog_pages.version_id
                    )
                WHERE EXISTS (
                    SELECT 1 FROM catalog_targets AS t
                    WHERE t.content_key = catalog_pages.version_id
                )
                """
            )
            connection.execute(
                """
                UPDATE catalog_nodes
                SET product_id = (
                    SELECT t.product_id FROM catalog_targets AS t
                    WHERE t.content_key = catalog_nodes.version_id
                )
                WHERE version_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM catalog_targets AS t
                    WHERE t.content_key = catalog_nodes.version_id
                  )
                """
            )

    def connect_root_product(self, product_key: str) -> None:
        now = _now()
        with self._connect() as connection:
            self._upsert_node(
                connection,
                node_id="https://www.ibm.com/docs/en",
                node_type="root",
                canonical_url="https://www.ibm.com/docs/en",
                label="IBM Documentation",
                product_id=None,
                version_id=None,
                metadata={},
                discovered_at=now,
            )
            _upsert_edge(
                connection,
                "https://www.ibm.com/docs/en",
                f"ibmdocs://product/{product_key}",
                "contains_product",
                now,
            )

    def mark_latest_targets(self) -> None:
        """Mark the newest discovered documentation set for each product."""
        with self._connect() as connection:
            connection.execute("UPDATE catalog_targets SET is_latest = 0")
            product_rows = connection.execute(
                "SELECT DISTINCT product_id FROM catalog_targets"
            ).fetchall()
            for product_row in product_rows:
                rows = connection.execute(
                    "SELECT * FROM catalog_targets WHERE product_id = ?",
                    (product_row["product_id"],),
                ).fetchall()
                if not rows:
                    continue
                latest = max(rows, key=_target_latest_sort_key)
                connection.execute(
                    "UPDATE catalog_targets SET is_latest = 1 WHERE content_key = ?",
                    (latest["content_key"],),
                )
                self._refresh_target_fts(connection, str(latest["content_key"]))

    def connect_sitemap_pages(
        self,
        target: CatalogTarget,
        entries: Iterable[SitemapEntry],
    ) -> int:
        """Add sitemap->page edges and page nodes without fetching page bodies."""
        now = _now()
        count = 0
        with self._connect() as connection:
            for entry in entries:
                self._upsert_node(
                    connection,
                    node_id=entry.canonical_url,
                    node_type="topic",
                    canonical_url=entry.canonical_url,
                    label=entry.title or _route_metadata(entry.canonical_url)[1],
                    product_id=target.product_id,
                    version_id=target.version_id,
                    metadata={"last_modified": entry.last_modified},
                    discovered_at=now,
                )
                _upsert_edge(
                    connection,
                    target.sitemap_url,
                    entry.canonical_url,
                    "lists_topic",
                    now,
                )
                count += 1
        return count

    def upsert_global_discovered(
        self,
        target: CatalogTarget,
        entries: Iterable[SitemapEntry],
    ) -> int:
        """Atomically store sitemap pages, nodes, and edges for a global target.

        Page FTS is rebuilt once after the portfolio crawl. Avoiding a pair of
        FTS writes for every URL makes the metadata-only global import much
        faster while preserving the same final searchable catalog.
        """
        now = _now()
        count = 0
        crawl_target = target.to_crawl_target()
        with self._connect() as connection:
            for entry in entries:
                route_type, topic_slug = _route_metadata(entry.canonical_url)
                connection.execute(
                    """
                    INSERT INTO catalog_pages (
                        canonical_url, source_id, product_id, product_name,
                        product_family, domain_id, version_id, product_version,
                        route_type, topic_slug, title, description,
                        last_modified, sitemap_url, discovered_at
                    ) VALUES (?, 'ibm-docs', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_url) DO UPDATE SET
                        source_id='ibm-docs',
                        product_id=excluded.product_id,
                        product_name=excluded.product_name,
                        product_family=excluded.product_family,
                        domain_id=excluded.domain_id,
                        version_id=excluded.version_id,
                        product_version=excluded.product_version,
                        route_type=excluded.route_type,
                        topic_slug=excluded.topic_slug,
                        title=CASE WHEN excluded.title != ''
                            THEN excluded.title ELSE catalog_pages.title END,
                        description=CASE WHEN excluded.description != ''
                            THEN excluded.description ELSE catalog_pages.description END,
                        last_modified=COALESCE(
                            excluded.last_modified, catalog_pages.last_modified
                        ),
                        sitemap_url=excluded.sitemap_url,
                        discovered_at=excluded.discovered_at
                    """,
                    (
                        entry.canonical_url, crawl_target.product_id,
                        crawl_target.product_name, target.product_family,
                        crawl_target.domain_id, crawl_target.version_id,
                        crawl_target.product_version, route_type, topic_slug,
                        entry.title, entry.description, entry.last_modified,
                        entry.sitemap_url, now,
                    ),
                )
                self._upsert_node(
                    connection,
                    node_id=entry.canonical_url,
                    node_type="topic",
                    canonical_url=entry.canonical_url,
                    label=entry.title or topic_slug,
                    product_id=target.product_id,
                    version_id=target.version_id,
                    metadata={"last_modified": entry.last_modified},
                    discovered_at=now,
                )
                _upsert_edge(
                    connection,
                    target.sitemap_url,
                    entry.canonical_url,
                    "lists_topic",
                    now,
                )
                count += 1
        return count

    def finalize_global_structure(self) -> None:
        """Remove superseded structural nodes and rebuild page search once."""
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM catalog_edges
                WHERE edge_type = 'has_version'
                  AND NOT EXISTS (
                    SELECT 1 FROM catalog_targets AS t
                    WHERE catalog_edges.source_url =
                              'ibmdocs://product/' || t.product_key
                      AND catalog_edges.target_url =
                              'ibmdocs://version/' || t.content_key
                  )
                """
            )
            connection.execute(
                """
                DELETE FROM catalog_edges
                WHERE source_url = 'https://www.ibm.com/docs/en'
                  AND edge_type = 'contains_product'
                  AND NOT EXISTS (
                    SELECT 1 FROM catalog_targets AS t
                    WHERE catalog_edges.target_url =
                              'ibmdocs://product/' || t.product_key
                  )
                """
            )
            connection.execute(
                """
                DELETE FROM catalog_nodes
                WHERE node_type = 'product'
                  AND NOT EXISTS (
                    SELECT 1 FROM catalog_targets AS t
                    WHERE catalog_nodes.node_id =
                              'ibmdocs://product/' || t.product_key
                  )
                """
            )
            if self._fts_available:
                connection.execute("DELETE FROM catalog_pages_fts")
                connection.execute(
                    """
                    INSERT INTO catalog_pages_fts (
                        canonical_url, title, breadcrumbs, topic_slug,
                        route_type, searchable_text
                    )
                    SELECT canonical_url, title, breadcrumbs_json, topic_slug,
                           route_type, description
                    FROM catalog_pages
                    """
                )

    def upsert_toc_topics(
        self,
        target: CatalogTarget,
        topics: Iterable[TocTopic],
    ) -> int:
        """Apply TOC titles, breadcrumbs and exact parent/child graph edges."""
        now = _now()
        version_node = f"ibmdocs://version/{target.content_key}"
        count = 0
        with self._connect() as connection:
            for topic in topics:
                route_type, topic_slug = _route_metadata(topic.canonical_url)
                connection.execute(
                    """
                    INSERT INTO catalog_pages (
                        canonical_url, source_id, product_id, product_name,
                        product_family, domain_id, version_id, product_version,
                        title, breadcrumbs_json, route_type, topic_slug,
                        parent_url, sitemap_url, discovered_at, toc_enriched_at
                    ) VALUES (?, 'ibm-docs', ?, ?, ?, 'ibm_products', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_url) DO UPDATE SET
                        product_id=excluded.product_id,
                        product_name=excluded.product_name,
                        product_family=excluded.product_family,
                        domain_id=excluded.domain_id,
                        version_id=excluded.version_id,
                        product_version=excluded.product_version,
                        title=excluded.title,
                        breadcrumbs_json=excluded.breadcrumbs_json,
                        parent_url=excluded.parent_url,
                        sitemap_url=excluded.sitemap_url,
                        toc_enriched_at=excluded.toc_enriched_at
                    """,
                    (
                        topic.canonical_url, target.product_id, target.product_name,
                        target.product_family, target.version_id,
                        target.product_version, topic.title,
                        json.dumps(topic.breadcrumbs), route_type, topic_slug,
                        topic.parent_url, target.sitemap_url, now, now,
                    ),
                )
                self._upsert_node(
                    connection,
                    node_id=topic.canonical_url,
                    node_type="topic",
                    canonical_url=topic.canonical_url,
                    label=topic.title,
                    product_id=target.product_id,
                    version_id=target.version_id,
                    metadata={
                        "topic_id": topic.topic_id,
                        "breadcrumbs": list(topic.breadcrumbs),
                        "ordinal": topic.ordinal,
                    },
                    discovered_at=now,
                )
                parent = topic.parent_url or version_node
                _upsert_edge(connection, parent, topic.canonical_url, "child", now)
                _upsert_edge(connection, topic.canonical_url, parent, "parent", now)
                self._refresh_fts(connection, topic.canonical_url)
                count += 1
        return count

    def upsert_discovered(
        self,
        target: CrawlTarget,
        entries: Iterable[SitemapEntry],
        *,
        source_id: str = "ibm-docs",
    ) -> int:
        """Insert sitemap metadata without requesting any document bodies."""
        now = _now()
        count = 0
        catalog_product_id = target.run_context.get(
            "catalog_product_id", target.product_id
        )
        catalog_product_name = target.run_context.get(
            "catalog_product_name", target.product_name
        )
        catalog_version_id = target.run_context.get(
            "catalog_version_id", target.version_id
        )
        with self._connect() as connection:
            for entry in entries:
                route_type, topic_slug = _route_metadata(entry.canonical_url)
                connection.execute(
                    """
                    INSERT INTO catalog_pages (
                        canonical_url, source_id, product_id, product_name, product_family,
                        domain_id, version_id, product_version, route_type,
                        topic_slug, title, description, last_modified, sitemap_url, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_url) DO UPDATE SET
                        source_id=excluded.source_id,
                        product_id=excluded.product_id,
                        product_name=excluded.product_name,
                        product_family=excluded.product_family,
                        domain_id=excluded.domain_id,
                        version_id=excluded.version_id,
                        product_version=excluded.product_version,
                        route_type=excluded.route_type,
                        topic_slug=excluded.topic_slug,
                        title=CASE WHEN excluded.title != ''
                            THEN excluded.title ELSE catalog_pages.title END,
                        description=CASE WHEN excluded.description != ''
                            THEN excluded.description ELSE catalog_pages.description END,
                        last_modified=COALESCE(excluded.last_modified, catalog_pages.last_modified),
                        sitemap_url=excluded.sitemap_url,
                        discovered_at=excluded.discovered_at
                    """,
                    (
                        entry.canonical_url, source_id, catalog_product_id,
                        catalog_product_name, catalog_product_name, target.domain_id,
                        catalog_version_id,
                        target.product_version, route_type, topic_slug,
                        entry.title, entry.description, entry.last_modified,
                        entry.sitemap_url, now,
                    ),
                )
                self._refresh_fts(connection, entry.canonical_url)
                count += 1
        return count

    def ensure_seed(self, target: CrawlTarget, *, source_id: str = "ibm-docs") -> None:
        self.upsert_discovered(target, [SitemapEntry(
            canonical_url=target.seed_url,
            last_modified=None,
            sitemap_url=target.sitemap_url,
        )], source_id=source_id)

    def enrich_document(
        self,
        target: CrawlTarget,
        document: ExtractedDocument,
        *,
        source_id: str = "ibm-docs",
    ) -> None:
        """Add content-derived metadata and graph edges after a bounded live fetch."""
        self.ensure_seed(target, source_id=source_id)
        if document.links:
            self.upsert_discovered(target, [
                SitemapEntry(
                    canonical_url=url,
                    last_modified=None,
                    sitemap_url=target.sitemap_url,
                )
                for url in document.links
            ], source_id=source_id)
        breadcrumbs = tuple(str(value) for value in document.metadata.get("breadcrumbs", []))
        parent_url = document.metadata.get("parent_url") or None
        route_type, topic_slug = _route_metadata(document.canonical_url)
        now = _now()
        catalog_product_id = target.run_context.get(
            "catalog_product_id", target.product_id
        )
        catalog_product_name = target.run_context.get(
            "catalog_product_name", target.product_name
        )
        catalog_version_id = target.run_context.get(
            "catalog_version_id", target.version_id
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO catalog_pages (
                    canonical_url, source_id, product_id, product_name, product_family,
                    domain_id, version_id, product_version, title,
                    description, breadcrumbs_json, route_type, topic_slug, parent_url,
                    content_hash, discovered_at, enriched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    source_id=excluded.source_id,
                    title=excluded.title,
                    description=excluded.description,
                    breadcrumbs_json=excluded.breadcrumbs_json,
                    parent_url=excluded.parent_url,
                    content_hash=excluded.content_hash,
                    enriched_at=excluded.enriched_at
                """,
                (
                    document.canonical_url, source_id, catalog_product_id,
                    catalog_product_name, catalog_product_name, target.domain_id,
                    catalog_version_id,
                    target.product_version, document.title,
                    str(document.metadata.get("description") or ""), json.dumps(breadcrumbs),
                    route_type, topic_slug, parent_url, document.content_hash, now, now,
                ),
            )
            self._refresh_fts(connection, document.canonical_url)
            for related_url in document.links:
                _upsert_edge(connection, document.canonical_url, related_url, "related", now)
            for ibm_url in document.metadata.get("outgoing_ibm_links", []):
                _upsert_edge(connection, document.canonical_url, str(ibm_url), "outgoing_ibm", now)
            for external_url in document.metadata.get("external_links", []):
                _upsert_edge(connection, document.canonical_url, str(external_url), "external", now)
            if parent_url:
                _upsert_edge(connection, document.canonical_url, str(parent_url), "parent", now)
                _upsert_edge(connection, str(parent_url), document.canonical_url, "child", now)

    def search(
        self,
        query: str,
        *,
        product_id: str,
        version_id: str,
        limit: int = 30,
        source_ids: tuple[str, ...] | None = None,
    ) -> list[CatalogPage]:
        tokens = _search_tokens(query)
        rows: list[sqlite3.Row] = []
        source_clause, source_params = _source_filter("p", source_ids)
        if self._fts_available and tokens:
            expression = " OR ".join(f'"{token}"*' for token in tokens)
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        f"""
                        SELECT p.*, bm25(catalog_pages_fts, 0.0, 10.0, 5.0, 6.0, 2.0, 1.0)
                            AS text_rank
                        FROM catalog_pages_fts
                        JOIN catalog_pages AS p
                          ON p.canonical_url = catalog_pages_fts.canonical_url
                        WHERE catalog_pages_fts MATCH ?
                          AND p.product_id = ? AND p.version_id = ?
                          {source_clause}
                        ORDER BY text_rank ASC
                        LIMIT ?
                        """,
                        (expression, product_id, version_id, *source_params, max(1, limit)),
                    ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            rows = self._fallback_search(
                tokens, product_id=product_id, version_id=version_id, limit=limit,
                source_ids=source_ids,
            )
        pages = [_page_from_row(row) for row in rows]
        return [replace(page, relevance_score=_score_page(page, tokens)) for page in pages]

    def neighbors(
        self,
        canonical_url: str,
        *,
        edge_types: tuple[str, ...] = ("related", "parent", "child"),
        limit: int = 20,
    ) -> list[str]:
        if not edge_types:
            return []
        placeholders = ",".join("?" for _ in edge_types)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT target_url FROM catalog_edges
                WHERE source_url = ? AND edge_type IN ({placeholders})
                ORDER BY edge_type, target_url LIMIT ?
                """,
                (canonical_url, *edge_types, max(1, limit)),
            ).fetchall()
        return [str(row["target_url"]) for row in rows]

    def get_page(self, canonical_url: str) -> CatalogPage | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_pages WHERE canonical_url = ?",
                (canonical_url,),
            ).fetchone()
        return _page_from_row(row) if row is not None else None

    def get_target(self, content_key: str) -> CatalogTarget | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_targets WHERE content_key = ?",
                (content_key,),
            ).fetchone()
        return _target_from_row(row) if row is not None else None

    def sitemap_is_cataloged(
        self,
        content_key: str,
        sitemap_url: str,
        last_modified: str | None,
    ) -> bool:
        """Return true only for a completed, current global sitemap target."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM catalog_targets WHERE content_key = ?",
                (content_key,),
            ).fetchone()
            if row is None:
                return False
            if not str(row["product_key"]).upper().startswith("PATH_"):
                return False
            if str(row["sitemap_url"]) != sitemap_url:
                return False
            if last_modified and str(row["last_modified"] or "") != last_modified:
                return False
            page = connection.execute(
                "SELECT 1 FROM catalog_pages WHERE version_id = ? LIMIT 1",
                (content_key,),
            ).fetchone()
        return page is not None

    def resolve_targets(
        self,
        query: str,
        *,
        product_version: str | None = None,
        limit: int = 10,
    ) -> list[CatalogTarget]:
        """Resolve a free-form IBM product question across the global catalog."""
        tokens = _search_tokens(query)
        version = (product_version or "").strip().casefold()
        rows: list[sqlite3.Row] = []
        if self._fts_available and tokens:
            expression = " OR ".join(f'"{token}"*' for token in tokens)
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT t.*, bm25(
                            catalog_targets_fts, 0.0, 10.0, 4.0, 5.0, 7.0, 6.0
                        ) AS text_rank
                        FROM catalog_targets_fts
                        JOIN catalog_targets AS t
                          ON t.content_key = catalog_targets_fts.content_key
                        WHERE catalog_targets_fts MATCH ?
                        ORDER BY text_rank ASC, t.is_latest DESC,
                                 t.last_modified DESC, t.content_key
                        LIMIT ?
                        """,
                        (expression, max(20, limit * 8)),
                    ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            clauses: list[str] = []
            params: list[object] = []
            for token in tokens[:10]:
                pattern = f"%{token}%"
                clauses.append(
                    "(LOWER(product_name) LIKE ? OR LOWER(product_family) LIKE ? "
                    "OR LOWER(product_url_key) LIKE ? OR LOWER(product_version) LIKE ? "
                    "OR LOWER(aliases_json) LIKE ?)"
                )
                params.extend([pattern] * 5)
            where = " WHERE " + " OR ".join(clauses) if clauses else ""
            params.append(max(20, limit * 8))
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT *, 0.0 AS text_rank FROM catalog_targets"
                    + where
                    + " ORDER BY is_latest DESC, last_modified DESC, content_key LIMIT ?",
                    params,
                ).fetchall()
        ranked_by_key: dict[str, CatalogTarget] = {}
        for row in rows:
            target = _target_from_row(row)
            if version and not _versions_compatible(version, target.product_version):
                continue
            score = _score_target(target, tokens, version)
            if score > 0:
                ranked_by_key[target.content_key] = replace(
                    target, relevance_score=score
                )

        # Product names are sometimes abbreviated in IBM Docs paths (for
        # example, ``watsonx/wdi``). Topic slugs in the sitemap often contain
        # the missing vocabulary, so use matching topic URLs as an additional
        # target-resolution signal. This remains metadata-only: no page body is
        # requested here.
        if not ranked_by_key:
            for target, page_score in self._targets_from_topic_metadata(
                tokens,
                requested_version=version,
                limit=max(20, limit * 8),
            ):
                target_score = _score_target(target, tokens, version)
                # Topic words such as "install" occur across the portfolio and
                # cannot identify a product by themselves. Require the target
                # metadata to match at least one product term.
                if target_score <= 0:
                    continue
                ranked_by_key[target.content_key] = replace(
                    target, relevance_score=target_score + page_score
                )

        ranked = list(ranked_by_key.values())
        ranked.sort(key=lambda item: (
            -item.relevance_score,
            -int(item.is_latest),
            item.product_name.casefold(),
            item.content_key,
        ))
        return ranked[:max(1, limit)]

    def _targets_from_topic_metadata(
        self,
        tokens: list[str],
        *,
        requested_version: str,
        limit: int,
    ) -> list[tuple[CatalogTarget, float]]:
        """Resolve documentation sets from sitemap URL/topic metadata."""
        if not tokens:
            return []
        rows: list[sqlite3.Row] = []
        if self._fts_available:
            expression = " OR ".join(f'"{token}"*' for token in tokens[:12])
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        """
                        SELECT p.*
                        FROM catalog_pages_fts
                        JOIN catalog_pages AS p
                          ON p.canonical_url = catalog_pages_fts.canonical_url
                        WHERE catalog_pages_fts MATCH ?
                        ORDER BY bm25(catalog_pages_fts) ASC
                        LIMIT ?
                        """,
                        (expression, max(20, limit * 4)),
                    ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            conditions: list[str] = []
            params: list[object] = []
            for token in tokens[:8]:
                pattern = f"%{token}%"
                conditions.append(
                    "(LOWER(p.topic_slug) LIKE ? OR LOWER(p.canonical_url) LIKE ? "
                    "OR LOWER(p.title) LIKE ? OR LOWER(p.breadcrumbs_json) LIKE ?)"
                )
                params.extend((pattern, pattern, pattern, pattern))
            params.append(max(20, limit * 4))
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT p.* FROM catalog_pages AS p WHERE "
                    + " OR ".join(conditions)
                    + " ORDER BY p.enriched_at DESC, p.canonical_url LIMIT ?",
                    params,
                ).fetchall()

        best_by_key: dict[str, tuple[CatalogTarget, float]] = {}
        with self._connect() as connection:
            for row in rows:
                page = _page_from_row(row)
                target_row = connection.execute(
                    "SELECT * FROM catalog_targets WHERE content_key = ?",
                    (page.version_id,),
                ).fetchone()
                if target_row is None:
                    continue
                target = _target_from_row(target_row)
                if requested_version and not _versions_compatible(
                    requested_version, target.product_version
                ):
                    continue
                product_score = _score_target(target, tokens, requested_version)
                topic_score = _score_page(page, tokens) * 2.0
                if product_score <= 0 and topic_score <= 0:
                    continue
                combined = product_score + topic_score
                existing = best_by_key.get(target.content_key)
                if existing is None or combined > existing[1]:
                    best_by_key[target.content_key] = (target, combined)
        return sorted(
            best_by_key.values(),
            key=lambda item: (-item[1], -int(item[0].is_latest), item[0].content_key),
        )[:max(1, limit)]

    def versions_for_product(self, product_id: str) -> list[CatalogTarget]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM catalog_targets WHERE product_id = ?
                ORDER BY is_latest DESC, last_modified DESC, product_version, content_key
                """,
                (product_id,),
            ).fetchall()
        return [_target_from_row(row) for row in rows]

    def metadata_candidates(
        self,
        query: str,
        target: CatalogTarget,
    ) -> list[dict]:
        """Return graph evidence only for questions the metadata itself answers."""
        lowered = query.casefold()
        version_question = any(phrase in lowered for phrase in (
            "versions available", "available versions", "what versions",
            "which versions", "list versions", "documentation versions",
        ))
        if not version_question:
            return []
        versions = self.versions_for_product(target.product_id)
        if not versions:
            return []
        unique_versions = list(dict.fromkeys(
            item.product_version for item in versions if item.product_version
        ))
        source = f"https://www.ibm.com/docs/en/{target.product_url_key}"
        display_name = _deduplicate_adjacent_words(target.product_name)
        return [{
            "chunk_id": f"ibm_products:catalog:{target.product_id}:versions",
            "document_id": f"catalog:{target.product_id}",
            "title": f"Available documentation versions for {display_name}",
            "domain_id": "ibm_products",
            "product": display_name,
            "product_version": None,
            "ocp_version": None,
            "source_uri": source,
            "source_type": "ibm_docs_catalog",
            "document_type": "documentation_catalog",
            "classification": "public",
            "access_scope": ["public", "isa_technical"],
            "section_path": "Product versions",
            "page_start": None,
            "page_end": None,
            "chunk_text": (
                f"IBM Documentation lists these documentation versions for "
                f"{display_name}: " + ", ".join(unique_versions) + "."
            ),
            "retrieval_origin": "global_metadata_catalog",
            "_live_score": 100.0,
        }]

    def stats(self, *, product_id: str | None = None) -> dict:
        where = " WHERE product_id = ?" if product_id else ""
        params = (product_id,) if product_id else ()
        with self._connect() as connection:
            page_count = connection.execute(
                f"SELECT COUNT(*) AS count FROM catalog_pages{where}", params
            ).fetchone()["count"]
            edge_count = connection.execute(
                "SELECT COUNT(*) AS count FROM catalog_edges"
            ).fetchone()["count"]
            enriched_count = connection.execute(
                f"SELECT COUNT(*) AS count FROM catalog_pages{where}"
                + (" AND enriched_at IS NOT NULL" if where else " WHERE enriched_at IS NOT NULL"),
                params,
            ).fetchone()["count"]
            target_count = connection.execute(
                "SELECT COUNT(*) AS count FROM catalog_targets"
            ).fetchone()["count"]
            product_count = connection.execute(
                "SELECT COUNT(DISTINCT product_id) AS count FROM catalog_targets"
            ).fetchone()["count"]
            node_count = connection.execute(
                "SELECT COUNT(*) AS count FROM catalog_nodes"
            ).fetchone()["count"]
        return {
            "pages": int(page_count),
            "enriched_pages": int(enriched_count),
            "edges": int(edge_count),
            "products": int(product_count),
            "targets": int(target_count),
            "nodes": int(node_count),
            "fts_enabled": self._fts_available,
            "database": str(self.db_path),
        }

    def _fallback_search(
        self,
        tokens: list[str],
        *,
        product_id: str,
        version_id: str,
        limit: int,
        source_ids: tuple[str, ...] | None,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list[object] = [product_id, version_id]
        source_clause, source_params = _source_filter("catalog_pages", source_ids)
        params.extend(source_params)
        for token in tokens[:8]:
            conditions.append(
                "(LOWER(title) LIKE ? OR LOWER(topic_slug) LIKE ? "
                "OR LOWER(canonical_url) LIKE ? OR LOWER(breadcrumbs_json) LIKE ? "
                "OR LOWER(description) LIKE ?)"
            )
            pattern = f"%{token}%"
            params.extend([pattern, pattern, pattern, pattern, pattern])
        token_filter = " AND (" + " OR ".join(conditions) + ")" if conditions else ""
        params.append(max(1, limit))
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT *, 0.0 AS text_rank FROM catalog_pages
                WHERE product_id = ? AND version_id = ?
                """ + source_clause + token_filter
                + " ORDER BY enriched_at DESC, canonical_url LIMIT ?",
                params,
            ).fetchall()

    def _refresh_fts(self, connection: sqlite3.Connection, canonical_url: str) -> None:
        if not self._fts_available:
            return
        row = connection.execute(
            "SELECT * FROM catalog_pages WHERE canonical_url = ?", (canonical_url,)
        ).fetchone()
        if row is None:
            return
        connection.execute(
            "DELETE FROM catalog_pages_fts WHERE canonical_url = ?", (canonical_url,)
        )
        breadcrumbs = " ".join(json.loads(row["breadcrumbs_json"] or "[]"))
        # Product and version are exact SQL filters, not relevance signals.
        # Including them here makes every page match a query that names the
        # product and drowns out topic/title terms.
        searchable = str(row["description"] or "")
        connection.execute(
            """
            INSERT INTO catalog_pages_fts (
                canonical_url, title, breadcrumbs, topic_slug, route_type, searchable_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_url, row["title"], breadcrumbs, row["topic_slug"],
                row["route_type"], searchable,
            ),
        )

    def _refresh_target_fts(
        self,
        connection: sqlite3.Connection,
        content_key: str,
    ) -> None:
        try:
            row = connection.execute(
                "SELECT * FROM catalog_targets WHERE content_key = ?", (content_key,)
            ).fetchone()
            if row is None:
                return
            connection.execute(
                "DELETE FROM catalog_targets_fts WHERE content_key = ?", (content_key,)
            )
            connection.execute(
                """
                INSERT INTO catalog_targets_fts (
                    content_key, product_name, product_family, product_url_key,
                    product_version, aliases
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    content_key, row["product_name"], row["product_family"],
                    row["product_url_key"], row["product_version"],
                    " ".join(json.loads(row["aliases_json"] or "[]")),
                ),
            )
        except sqlite3.OperationalError:
            return

    @staticmethod
    def _upsert_node(
        connection: sqlite3.Connection,
        *,
        node_id: str,
        node_type: str,
        canonical_url: str | None,
        label: str,
        product_id: str | None,
        version_id: str | None,
        metadata: dict,
        discovered_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO catalog_nodes (
                node_id, node_type, canonical_url, label, product_id,
                version_id, metadata_json, discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                node_type=excluded.node_type,
                canonical_url=COALESCE(excluded.canonical_url, catalog_nodes.canonical_url),
                label=CASE WHEN excluded.label != ''
                    THEN excluded.label ELSE catalog_nodes.label END,
                product_id=COALESCE(excluded.product_id, catalog_nodes.product_id),
                version_id=COALESCE(excluded.version_id, catalog_nodes.version_id),
                metadata_json=excluded.metadata_json,
                discovered_at=excluded.discovered_at
            """,
            (
                node_id, node_type, canonical_url, label, product_id,
                version_id, json.dumps(metadata, sort_keys=True), discovered_at,
            ),
        )


def _route_metadata(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    topic = query.get("topic", "").strip()
    if topic:
        return "topic", topic.replace("_", "-")
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return "landing", slug


def _search_tokens(query: str) -> list[str]:
    output: list[str] = []
    for raw in _SEARCH_TOKEN_RE.findall(query.lower()):
        raw = raw.strip(".-_")
        variants = [raw]
        parts = [part for part in re.split(r"[._-]+", raw) if part]
        if len(parts) > 1:
            variants.extend(parts)
            variants.append("".join(parts))
        compact = re.sub(r"[^a-z0-9]", "", raw)
        if compact in {"usecase", "usecases"}:
            variants.extend(("use", "case"))
        for token in variants:
            if len(token) < 2 or token in _STOP_WORDS or token in output:
                continue
            output.append(token)
    return output[:30]


def _score_page(page: CatalogPage, tokens: list[str]) -> float:
    if not tokens:
        return 0.1
    title = page.title.lower()
    slug = page.topic_slug.lower().replace("-", " ").replace("_", " ")
    breadcrumbs = " ".join(page.breadcrumbs).lower()
    score = 0.0
    for token in tokens:
        if token in title:
            score += 6.0
        if token in slug:
            score += 4.0
        if token in breadcrumbs:
            score += 2.0
    return score / max(1, len(tokens))


def _page_from_row(row: sqlite3.Row) -> CatalogPage:
    return CatalogPage(
        canonical_url=str(row["canonical_url"]),
        source_id=str(row["source_id"]),
        product_id=str(row["product_id"]),
        product_name=str(row["product_name"]),
        product_family=str(row["product_family"]),
        domain_id=str(row["domain_id"]),
        version_id=str(row["version_id"]),
        product_version=str(row["product_version"]),
        title=str(row["title"] or ""),
        description=str(row["description"] or ""),
        breadcrumbs=tuple(json.loads(row["breadcrumbs_json"] or "[]")),
        route_type=str(row["route_type"]),
        topic_slug=str(row["topic_slug"]),
        parent_url=str(row["parent_url"]) if row["parent_url"] else None,
        last_modified=str(row["last_modified"]) if row["last_modified"] else None,
        sitemap_url=str(row["sitemap_url"]) if row["sitemap_url"] else None,
        content_hash=str(row["content_hash"]) if row["content_hash"] else None,
    )


def _target_from_row(row: sqlite3.Row) -> CatalogTarget:
    return CatalogTarget(
        content_key=str(row["content_key"]),
        product_id=str(row["product_id"]),
        product_key=str(row["product_key"]),
        product_name=str(row["product_name"]),
        product_family=str(row["product_family"]),
        product_url_key=str(row["product_url_key"]),
        version_id=str(row["version_id"]),
        product_version=str(row["product_version"]),
        docs_path_prefix=str(row["docs_path_prefix"]),
        seed_url=str(row["seed_url"]),
        sitemap_url=str(row["sitemap_url"]),
        aliases=tuple(json.loads(row["aliases_json"] or "[]")),
        last_modified=str(row["last_modified"]) if row["last_modified"] else None,
        is_latest=bool(row["is_latest"]),
    )


def _score_target(
    target: CatalogTarget,
    tokens: list[str],
    requested_version: str,
) -> float:
    product_words = set(_SEARCH_TOKEN_RE.findall(" ".join((
        target.product_name,
        target.product_family,
        target.product_url_key.replace("/", " ").replace("-", " "),
        " ".join(target.aliases),
    )).casefold()))
    version_words = set(_SEARCH_TOKEN_RE.findall(target.product_version.casefold()))
    matched_product = sum(
        1 for token in tokens
        if token in product_words or any(
            len(token) > 3 and word.startswith(token) for word in product_words
        )
    )
    if matched_product == 0:
        return 0.0
    score = matched_product * 6.0
    score += (matched_product / max(1, len(tokens))) * 8.0
    if requested_version and _versions_compatible(
        requested_version, target.product_version
    ):
        score += 20.0
    elif any(token in version_words for token in tokens):
        score += 8.0
    if target.is_latest:
        score += 1.0
    lowered_query = " ".join(tokens)
    if target.product_name.casefold() in lowered_query:
        score += 12.0
    return score


def is_confident_target_match(
    target: CatalogTarget | None,
    query: str,
) -> bool:
    """Require an identifiable product phrase, not an incidental family word."""
    if target is None or target.relevance_score <= 0:
        return False
    query_tokens = set(_search_tokens(query))
    identities = (
        target.product_name,
        *target.aliases,
        target.product_url_key.replace("/", " ").replace("-", " "),
    )
    for identity in identities:
        identity_tokens = set(_search_tokens(identity))
        if not identity_tokens:
            continue
        # A complete multi-word identity such as "Security Verify" or
        # "Cloud Pak Data" is a strong product signal even when its words are
        # individually common across the portfolio.
        if len(identity_tokens) > 1 and identity_tokens.issubset(query_tokens):
            return True
        # A distinctive root such as Instana, Concert, Guardium, or Verify is
        # also sufficient when the rest of the query describes user intent.
        if any(
            token in query_tokens
            and len(token) >= 5
            and token not in _GENERIC_PRODUCT_WORDS
            for token in identity_tokens
        ):
            return True
    return False


def _versions_compatible(requested: str, available: str) -> bool:
    requested = requested.casefold().strip().lstrip("v")
    available = available.casefold().strip().lstrip("v")
    if requested == available:
        return True
    if available.endswith(".x"):
        family = available[:-2]
        return requested == family or requested.startswith(family + ".")
    if requested.endswith(".x"):
        family = requested[:-2]
        return available == family or available.startswith(family + ".")
    return False


def global_product_id(product_key: str) -> str:
    """Return one stable product ID shared by every version of an IBM content key."""
    base = product_key if product_key.upper().startswith(("PATH_", "FAMILY_")) else re.sub(
        r"_(?:family|solution|ref|serv|beta|tssc|\d.*)$",
        "",
        product_key,
        flags=re.IGNORECASE,
    )
    slug = re.sub(r"[^a-z0-9]+", "-", base.casefold()).strip("-")
    return f"ibmdocs-{slug or 'unknown'}"


def _global_product_id(product_key: str) -> str:
    return global_product_id(product_key)


def _target_latest_sort_key(row: sqlite3.Row) -> tuple:
    version = str(row["product_version"] or "").casefold()
    numeric = tuple(
        int(value) if value.isdigit() else -1
        for value in re.findall(r"\d+", version)[:4]
    )
    channel = 2 if version in {"current", "saas", "latest"} else 1
    return (
        channel,
        numeric,
        str(row["last_modified"] or ""),
        str(row["content_key"]),
    )


def _catalog_target_latest_sort_key(target: CatalogTarget) -> tuple:
    version = target.product_version.casefold()
    numeric = tuple(
        int(value) if value.isdigit() else -1
        for value in re.findall(r"\d+", version)[:4]
    )
    channel = 2 if version in {"current", "saas", "latest"} else 1
    return channel, numeric, target.last_modified or "", target.content_key


def _content_family_key(content_key: str) -> str:
    return re.sub(
        r"_(?:v?\d[0-9a-z.-]*|base|current|latest|saas|beta)$",
        "",
        content_key,
        flags=re.IGNORECASE,
    ) or content_key


def _path_product_key(product_url_key: str) -> str:
    normalized = re.sub(
        r"[^A-Z0-9]+", "_", product_url_key.upper()
    ).strip("_")
    return f"PATH_{normalized or 'UNKNOWN'}"


def _upsert_edge(
    connection: sqlite3.Connection,
    source_url: str,
    target_url: str,
    edge_type: str,
    discovered_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_edges (source_url, target_url, edge_type, discovered_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source_url, target_url, edge_type) DO UPDATE SET
            discovered_at=excluded.discovered_at
        """,
        (source_url, target_url, edge_type, discovered_at),
    )


def _deduplicate_adjacent_words(value: str) -> str:
    """Clean repeated catalog labels such as ``IBM watsonx watsonx ...``."""
    words = value.split()
    output: list[str] = []
    for word in words:
        if output and output[-1].casefold() == word.casefold():
            continue
        output.append(word)
    return " ".join(output)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_filter(
    table_alias: str,
    source_ids: tuple[str, ...] | None,
) -> tuple[str, list[str]]:
    if not source_ids:
        return "", []
    placeholders = ",".join("?" for _ in source_ids)
    return f" AND {table_alias}.source_id IN ({placeholders})", list(source_ids)
