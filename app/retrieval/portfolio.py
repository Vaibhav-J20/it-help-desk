"""Deterministic routing targets for broad IBM product-portfolio questions."""

from __future__ import annotations

import re
from typing import Literal

from app.ingestion.official_docs.registry import OfficialSourceTarget

PortfolioFamily = Literal["ibm", "watsonx"]

_WATSONX_PORTFOLIO_PATTERNS = (
    re.compile(
        r"\b(?:what|which)\s+(?:are\s+)?(?:all\s+)?(?:the\s+)?"
        r"(?:ibm\s+)?watsonx\s+(?:products|offerings|portfolio)\b"
    ),
    re.compile(
        r"\b(?:list|show|name)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?"
        r"(?:ibm\s+)?watsonx\s+(?:products|offerings)\b"
    ),
    re.compile(
        r"\b(?:products|offerings)\s+(?:that\s+)?(?:ibm\s+)?watsonx\s+"
        r"(?:has|offers|provides)\b"
    ),
    re.compile(r"\bwatsonx\s+(?:product|offering|portfolio)\s+(?:list|catalog)\b"),
)

_IBM_PORTFOLIO_PATTERNS = (
    re.compile(
        r"\b(?:what|which)\s+(?:are\s+)?(?:all\s+)?(?:the\s+)?"
        r"ibm\s+(?:products|offerings|portfolio)\b"
    ),
    re.compile(
        r"\b(?:list|show|name)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?"
        r"(?:products|offerings)\s+(?:that\s+)?ibm\s+(?:has|offers|provides)?\b"
    ),
    re.compile(r"\bwhat\s+(?:products|offerings)\s+does\s+ibm\s+(?:have|offer|provide)\b"),
    re.compile(r"\bibm\s+(?:product|offering|portfolio)\s+(?:list|catalog)\b"),
)


def detect_portfolio_family(question: str) -> PortfolioFamily | None:
    """Return a portfolio family only for explicit cross-product list requests."""
    normalized = " ".join(question.casefold().split())
    if re.search(
        r"\b(?:products|offerings)\s+(?:that\s+)?"
        r"(?:integrate|work|connect|support|run|install|configure)\b",
        normalized,
    ):
        return None
    if any(pattern.search(normalized) for pattern in _WATSONX_PORTFOLIO_PATTERNS):
        return "watsonx"
    if any(pattern.search(normalized) for pattern in _IBM_PORTFOLIO_PATTERNS):
        return "ibm"
    return None


def portfolio_target(family: PortfolioFamily) -> OfficialSourceTarget:
    """Build one exact-host, exact-path live target for an official IBM catalog page."""
    if family == "watsonx":
        source_id = "ibm-watsonx-portfolio"
        product_id = "ibm-watsonx-portfolio"
        product_name = "IBM watsonx portfolio"
        path_prefix = "/products/watsonx"
        seed_url = "https://www.ibm.com/products/watsonx"
        aliases = ("IBM watsonx", "watsonx products", "watsonx portfolio")
    else:
        source_id = "ibm-products-portfolio"
        product_id = "ibm-products-portfolio"
        product_name = "IBM product catalog"
        path_prefix = "/products"
        seed_url = "https://www.ibm.com/products"
        aliases = ("IBM products", "IBM offerings", "IBM product portfolio")

    return OfficialSourceTarget(
        source_id=source_id,
        product_id=product_id,
        product_name=product_name,
        domain_id="ibm_products",
        aliases=aliases,
        version_id="current",
        product_version="current",
        source_version="live",
        origin="https://www.ibm.com",
        allowed_host="www.ibm.com",
        docs_path_prefix=path_prefix,
        index_url="https://www.ibm.com/sitemap.xml",
        seed_url=seed_url,
        max_pages=1,
        sitemap_url="https://www.ibm.com/sitemap.xml",
        run_context={
            "mode": "official-portfolio-live",
            "source_id": source_id,
            "portfolio_family": family,
        },
        index_format="sitemap",
        content_format="html",
        document_type="product_catalog",
        classification="public",
        access_scope=("public", "isa_technical"),
    )


def is_portfolio_target(target: object) -> bool:
    return str(getattr(target, "source_id", "")) in {
        "ibm-products-portfolio",
        "ibm-watsonx-portfolio",
    }
