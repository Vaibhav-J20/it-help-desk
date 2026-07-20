"""Validated registry for non-ibm.com official product-documentation sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from .urls import canonicalize_source_url, is_source_page_url

DEFAULT_OFFICIAL_SOURCE_REGISTRY = (
    Path(__file__).parents[3] / "config" / "official_doc_sources.yaml"
)


class OfficialSourceRegistryError(ValueError):
    """The official-source registry is missing or invalid."""


class OfficialSourceEntry(BaseModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    product_name: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    aliases: list[str] = Field(default_factory=list)
    version_id: str = Field(min_length=1, max_length=100)
    product_version: str = Field(min_length=1, max_length=100)
    source_version: str = Field(min_length=1, max_length=100)
    origin: str
    path_prefix: str = "/"
    index_url: str
    seed_url: str
    index_format: str = Field(default="llms", pattern=r"^(llms|sitemap)$")
    content_format: str = Field(default="markdown", pattern=r"^(markdown|html)$")
    enabled: bool = False
    document_type: str = "developer_docs"
    classification: str = "public"
    access_scope: list[str] = Field(
        default_factory=lambda: ["public", "isa_technical"], min_length=1
    )

    @model_validator(mode="after")
    def validate_source_boundary(self) -> "OfficialSourceEntry":
        origin = urlsplit(self.origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.port is not None
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise ValueError("origin must be a bare HTTPS origin without credentials or port")
        host = origin.hostname.lower().rstrip(".")
        # The metadata index can live at the host root while product pages are
        # constrained to a narrower path (for example bob.ibm.com/sitemap.xml
        # catalogs only /docs/ide pages for the registered Bob source).
        canonical_index = canonicalize_source_url(
            self.index_url, allowed_host=host, path_prefix="/"
        )
        canonical_seed = canonicalize_source_url(
            self.seed_url, allowed_host=host, path_prefix=self.path_prefix
        )
        if self.index_format == "llms" and not canonical_index.endswith("/llms.txt"):
            raise ValueError("llms index_url must identify an llms.txt document catalog")
        if self.index_format == "sitemap" and not urlsplit(canonical_index).path.lower().endswith(
            (".xml", ".xml.gz")
        ):
            raise ValueError("sitemap index_url must identify an XML sitemap")
        if not is_source_page_url(
            canonical_seed,
            allowed_host=host,
            path_prefix=self.path_prefix,
            content_format=self.content_format,
        ):
            raise ValueError("seed_url must identify an allowlisted documentation page")
        self.origin = f"https://{host}"
        self.path_prefix = "/" + self.path_prefix.strip("/") if self.path_prefix != "/" else "/"
        self.index_url = canonical_index
        self.seed_url = canonical_seed
        return self


class OfficialSourceRegistry(BaseModel):
    registry_version: str
    sources: list[OfficialSourceEntry]

    @model_validator(mode="after")
    def validate_unique_sources(self) -> "OfficialSourceRegistry":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source_id in official documentation registry")
        return self


@dataclass(frozen=True)
class OfficialSourceTarget:
    source_id: str
    product_id: str
    product_name: str
    domain_id: str
    aliases: tuple[str, ...]
    version_id: str
    product_version: str
    source_version: str
    origin: str
    allowed_host: str
    docs_path_prefix: str
    index_url: str
    seed_url: str
    max_pages: int
    sitemap_url: str
    run_context: dict[str, str]
    index_format: str = "llms"
    content_format: str = "markdown"
    document_type: str = "developer_docs"
    classification: str = "public"
    access_scope: tuple[str, ...] = ("public", "isa_technical")


def load_official_source_registry(
    path: Path = DEFAULT_OFFICIAL_SOURCE_REGISTRY,
) -> OfficialSourceRegistry:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return OfficialSourceRegistry.model_validate(raw)
    except FileNotFoundError as exc:
        raise OfficialSourceRegistryError(
            f"Official documentation source registry not found: {path}"
        ) from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise OfficialSourceRegistryError(
            f"Invalid official documentation registry {path}: {exc}"
        ) from exc


def get_enabled_sources(
    registry: OfficialSourceRegistry,
    *,
    product_id: str,
    version_id: str | None = None,
) -> list[OfficialSourceTarget]:
    output: list[OfficialSourceTarget] = []
    for source in registry.sources:
        if not source.enabled or source.product_id != product_id:
            continue
        if version_id and source.version_id != version_id:
            continue
        host = urlsplit(source.origin).hostname or ""
        output.append(OfficialSourceTarget(
            source_id=source.source_id,
            product_id=source.product_id,
            product_name=source.product_name,
            domain_id=source.domain_id,
            aliases=tuple(source.aliases),
            version_id=source.version_id,
            product_version=source.product_version,
            source_version=source.source_version,
            origin=source.origin,
            allowed_host=host,
            docs_path_prefix=source.path_prefix,
            index_url=source.index_url,
            seed_url=source.seed_url,
            max_pages=100_000,
            sitemap_url=source.index_url,
            run_context={
                "mode": "official-docs-live",
                "source_id": source.source_id,
                "registry_enabled": "true",
            },
            index_format=source.index_format,
            content_format=source.content_format,
            document_type=source.document_type,
            classification=source.classification,
            access_scope=tuple(source.access_scope),
        ))
    return output


def get_enabled_source(
    registry: OfficialSourceRegistry,
    source_id: str,
) -> OfficialSourceTarget:
    entry = next((source for source in registry.sources if source.source_id == source_id), None)
    if entry is None:
        raise OfficialSourceRegistryError(f"Unknown official source_id: {source_id}")
    if not entry.enabled:
        raise OfficialSourceRegistryError(f"Official source is disabled: {source_id}")
    targets = get_enabled_sources(
        registry,
        product_id=entry.product_id,
        version_id=entry.version_id,
    )
    return next(target for target in targets if target.source_id == source_id)
