"""
COS Source Abstraction — OpenShift & SNO Support Copilot
Owner: Developer B
Module: app/ingestion/cos_source.py

Provides a unified interface for reading PDFs from either:
  - IBM Cloud Object Storage (production): cos://bucket/path/file.pdf
  - Local filesystem (dev): local://docs/file.pdf

Falls back to local automatically when COS env vars are not set.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCAL_DOCS_DIR = Path(__file__).parents[2] / "docs"


def _is_cos_uri(uri: str) -> bool:
    return uri.startswith("cos://")


def _is_local_uri(uri: str) -> bool:
    return uri.startswith("local://")


def _cos_available() -> bool:
    return bool(
        os.getenv("COS_ENDPOINT")
        and os.getenv("COS_BUCKET")
        and os.getenv("COS_API_KEY")
    )


def get_document(source_uri: str) -> bytes:
    """
    Retrieve raw PDF bytes for a given source_uri.

    Supports:
        cos://bucket-name/path/to/file.pdf   → IBM COS (requires COS_* env vars)
        local://docs/file.pdf                → local docs/ folder (dev mode)

    Args:
        source_uri: The URI from the corpus manifest entry.

    Returns:
        Raw PDF bytes.

    Raises:
        FileNotFoundError: If the document cannot be found.
        EnvironmentError: If COS URI used but COS env vars not set.
    """
    if _is_local_uri(source_uri):
        return _read_local(source_uri)
    elif _is_cos_uri(source_uri):
        if not _cos_available():
            logger.warning(
                "COS env vars not set — falling back to local for %s", source_uri
            )
            return _read_local(_cos_to_local_uri(source_uri))
        return _read_cos(source_uri)
    else:
        raise ValueError(f"Unknown URI scheme in source_uri: '{source_uri}'")


def list_documents(manifest_sources: list[dict]) -> list[dict]:
    """
    Filter manifest sources to only those that are accessible right now.
    Returns the same list with an added 'accessible' bool per entry.
    Useful for pre-flight checks before starting a long ingestion run.
    """
    results = []
    for source in manifest_sources:
        uri = source.get("source_uri", "")
        accessible = _check_accessible(uri)
        if not accessible:
            logger.warning("Source not accessible (will skip): %s", uri)
        results.append({**source, "accessible": accessible})
    return results


def _check_accessible(uri: str) -> bool:
    try:
        if _is_local_uri(uri):
            path = _local_path_from_uri(uri)
            return path.exists() and path.is_file()
        elif _is_cos_uri(uri):
            return _cos_available()
        return False
    except Exception:
        return False


def _read_local(uri: str) -> bytes:
    path = _local_path_from_uri(uri)
    if not path.exists():
        raise FileNotFoundError(f"Local document not found: {path} (uri={uri})")
    logger.debug("Reading local document: %s", path)
    return path.read_bytes()


def _local_path_from_uri(uri: str) -> Path:
    # local://docs/file.pdf  →  <repo_root>/docs/file.pdf
    relative = uri.removeprefix("local://")
    return _LOCAL_DOCS_DIR.parent / relative


def _cos_to_local_uri(cos_uri: str) -> str:
    # cos://bucket/ocp-sno/file.pdf → local://docs/file.pdf
    filename = cos_uri.split("/")[-1]
    return f"local://docs/{filename}"


def _read_cos(cos_uri: str) -> bytes:
    """Read a document from IBM Cloud Object Storage."""
    import ibm_boto3
    from ibm_botocore.client import Config

    cos_endpoint = os.environ["COS_ENDPOINT"]
    cos_api_key = os.environ["COS_API_KEY"]
    cos_bucket = os.environ["COS_BUCKET"]

    # Parse cos://bucket/path from URI
    without_scheme = cos_uri.removeprefix("cos://")
    parts = without_scheme.split("/", 1)
    bucket = parts[0] if len(parts) > 0 else cos_bucket
    key = parts[1] if len(parts) > 1 else without_scheme

    logger.debug("Reading from COS: bucket=%s key=%s", bucket, key)

    cos_client = ibm_boto3.client(
        "s3",
        ibm_api_key_id=cos_api_key,
        ibm_service_instance_id=os.getenv("COS_INSTANCE_ID", ""),
        config=Config(signature_version="oauth"),
        endpoint_url=cos_endpoint,
    )
    response = cos_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()
