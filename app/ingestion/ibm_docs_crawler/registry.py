"""Validated allowlist registry for public IBM Documentation crawl targets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .urls import is_in_target_scope, validate_ibm_docs_url

DEFAULT_REGISTRY_PATH = Path(__file__).parents[3] / "config" / "ibm_docs_registry.yaml"


class RegistryError(ValueError):
    """The crawl registry is invalid or does not enable the requested run."""


class VersionEntry(BaseModel):
    version_id: str = Field(min_length=1, max_length=100)
    product_version: str = Field(min_length=1, max_length=100)
    seed_url: str
    sitemap_url: str | None = None
    crawl_enabled: bool = False

    @field_validator("seed_url")
    @classmethod
    def validate_seed_url(cls, value: str) -> str:
        return validate_ibm_docs_url(value)

    @field_validator("sitemap_url")
    @classmethod
    def validate_version_sitemap(cls, value: str | None) -> str | None:
        return validate_ibm_docs_url(value) if value else None


class ProductEntry(BaseModel):
    product_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    product_name: str = Field(min_length=1, max_length=200)
    domain_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]*$")
    docs_path_prefix: str
    aliases: list[str] = Field(default_factory=list)
    document_type: str = "developer_docs"
    classification: str = "public"
    access_scope: list[str] = Field(
        default_factory=lambda: ["public", "isa_technical"], min_length=1
    )
    max_pages: int = Field(default=250, ge=1, le=100_000)
    versions: list[VersionEntry]

    @field_validator("docs_path_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        prefix = "/" + value.strip("/")
        if not prefix.startswith("/docs/en/"):
            raise ValueError("docs_path_prefix must start with /docs/en/")
        return prefix.rstrip("/")

    @model_validator(mode="after")
    def validate_versions(self) -> "ProductEntry":
        version_ids = [entry.version_id for entry in self.versions]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError(f"duplicate version_id in product {self.product_id}")
        for entry in self.versions:
            if not is_in_target_scope(entry.seed_url, self.docs_path_prefix):
                raise ValueError(
                    f"seed_url for {self.product_id}/{entry.version_id} is outside docs_path_prefix"
                )
        return self


class Registry(BaseModel):
    registry_version: str
    sitemap_url: str = "https://www.ibm.com/docs/en/sitemap.xml"
    products: list[ProductEntry]

    @field_validator("sitemap_url")
    @classmethod
    def validate_sitemap(cls, value: str) -> str:
        return validate_ibm_docs_url(value)

    @model_validator(mode="after")
    def validate_products(self) -> "Registry":
        product_ids = [entry.product_id for entry in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("duplicate product_id in registry")
        return self


@dataclass(frozen=True)
class CrawlTarget:
    product_id: str
    product_name: str
    domain_id: str
    docs_path_prefix: str
    aliases: tuple[str, ...]
    version_id: str
    product_version: str
    seed_url: str
    max_pages: int
    sitemap_url: str
    run_context: dict[str, str]
    document_type: str = "developer_docs"
    classification: str = "public"
    access_scope: tuple[str, ...] = ("public", "isa_technical")


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Registry.model_validate(raw)
    except FileNotFoundError as exc:
        raise RegistryError(f"IBM Docs registry not found: {path}") from exc
    except (ValidationError, yaml.YAMLError) as exc:
        raise RegistryError(f"Invalid IBM Docs registry {path}: {exc}") from exc


def get_enabled_target(
    registry: Registry,
    product_id: str,
    version_id: str,
) -> CrawlTarget:
    return get_target(registry, product_id, version_id, require_enabled=True)


def get_target(
    registry: Registry,
    product_id: str,
    version_id: str,
    *,
    require_enabled: bool,
) -> CrawlTarget:
    product = next((p for p in registry.products if p.product_id == product_id), None)
    if product is None:
        raise RegistryError(f"Unknown IBM Docs product_id: {product_id}")
    version = next((v for v in product.versions if v.version_id == version_id), None)
    if version is None:
        raise RegistryError(f"Unknown version_id: {product_id}/{version_id}")
    if require_enabled and not version.crawl_enabled:
        raise RegistryError(
            f"Crawl blocked: {product_id}/{version_id} is not enabled in the registry"
        )

    return CrawlTarget(
        product_id=product.product_id,
        product_name=product.product_name,
        domain_id=product.domain_id,
        docs_path_prefix=product.docs_path_prefix,
        aliases=tuple(product.aliases),
        version_id=version.version_id,
        product_version=version.product_version,
        seed_url=version.seed_url,
        max_pages=product.max_pages,
        sitemap_url=version.sitemap_url or registry.sitemap_url,
        run_context={
            "mode": "public-ibm-docs",
            "registry_enabled": str(version.crawl_enabled).lower(),
        },
        document_type=product.document_type,
        classification=product.classification,
        access_scope=tuple(product.access_scope),
    )
