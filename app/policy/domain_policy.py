"""
Domain policy — loads domain registry and checks request scope.
"""
from pathlib import Path
import yaml
from app.observability.logging import get_logger

logger = get_logger(__name__)
_DOMAINS_FILE = Path(__file__).parent.parent.parent / "config" / "domains.yaml"


def load_domains() -> dict:
    """Load the domain registry from config/domains.yaml."""
    if not _DOMAINS_FILE.exists():
        logger.info(f"domains.yaml not found at {_DOMAINS_FILE} — using empty registry")
        return {}
    with open(_DOMAINS_FILE) as f:
        return yaml.safe_load(f) or {}


def is_in_scope(domain_id: str) -> bool:
    """Return True if the given domain_id is registered and active."""
    domains = load_domains()
    entry = domains.get("domains", {}).get(domain_id, {})
    return entry.get("active", False)
