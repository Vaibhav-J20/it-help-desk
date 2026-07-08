"""
Metadata Validator — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/metadata.py

Validates document metadata against the controlled taxonomy (config/taxonomy/ocp_sno.yaml).
Rejects any record containing unsupported taxonomy values — never silently passes them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_TAXONOMY_CACHE: dict | None = None
_TAXONOMY_PATH = Path(__file__).parents[2] / "config" / "taxonomy" / "ocp_sno.yaml"


def _load_taxonomy() -> dict:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        with open(_TAXONOMY_PATH, "r") as f:
            _TAXONOMY_CACHE = yaml.safe_load(f)
    return _TAXONOMY_CACHE


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_metadata(record: dict[str, Any]) -> ValidationResult:
    """
    Validate a document metadata record against the taxonomy.

    Args:
        record: Dict with keys matching the corpus manifest entry schema.

    Returns:
        ValidationResult with valid=True and empty errors if all checks pass,
        or valid=False with a list of error messages if any check fails.
    """
    taxonomy = _load_taxonomy()
    errors: list[str] = []

    # Common required fields for every supported domain.
    required = ["domain_id", "product", "document_type", "classification", "title", "source_uri"]
    if record.get("domain_id") == taxonomy["domain_id"]:
        required.extend(["ocp_version", "deployment_type"])

    for key in required:
        if not record.get(key):
            errors.append(f"Missing required field: '{key}'")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    # domain_id
    allowed_domain_ids = taxonomy.get("allowed_domain_ids") or [taxonomy["domain_id"]]
    if record["domain_id"] not in allowed_domain_ids:
        errors.append(
            f"domain_id '{record['domain_id']}' not valid; expected one of {allowed_domain_ids}"
        )

    # product
    if record["product"] not in taxonomy["allowed_products"]:
        errors.append(
            f"product '{record['product']}' not in allowed_products: {taxonomy['allowed_products']}"
        )

    # ocp_version — required for the OpenShift/SNO domain, optional for others.
    if record.get("ocp_version") and str(record["ocp_version"]) not in taxonomy["allowed_ocp_versions"]:
        errors.append(
            f"ocp_version '{record['ocp_version']}' not in allowed_ocp_versions: {taxonomy['allowed_ocp_versions']}"
        )

    # deployment_type — required for OpenShift/SNO, optional for other domains.
    dep_types = record.get("deployment_type", [])
    if record.get("domain_id") == taxonomy["domain_id"] and (not isinstance(dep_types, list) or len(dep_types) == 0):
        errors.append("deployment_type must be a non-empty list")
    elif dep_types:
        if not isinstance(dep_types, list):
            errors.append("deployment_type must be a list")
            dep_types = []
        for dt in dep_types:
            if dt not in taxonomy["allowed_deployment_types"]:
                errors.append(
                    f"deployment_type '{dt}' not in allowed_deployment_types: {taxonomy['allowed_deployment_types']}"
                )

    # document_type
    if record["document_type"] not in taxonomy["allowed_document_types"]:
        errors.append(
            f"document_type '{record['document_type']}' not in allowed_document_types: {taxonomy['allowed_document_types']}"
        )

    # classification
    if record["classification"] not in taxonomy["allowed_classifications"]:
        errors.append(
            f"classification '{record['classification']}' not in allowed_classifications: {taxonomy['allowed_classifications']}"
        )

    # components — optional but if present, every value must be valid
    components = record.get("components", [])
    if components:
        for comp in components:
            if comp not in taxonomy["allowed_components"]:
                errors.append(
                    f"component '{comp}' not in allowed_components: {taxonomy['allowed_components']}"
                )

    valid = len(errors) == 0
    if not valid:
        logger.warning("Metadata validation failed for '%s': %s", record.get("source_uri"), errors)

    return ValidationResult(valid=valid, errors=errors)
