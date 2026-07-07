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


def is_question_out_of_scope(question: str) -> bool:
    """
    Deterministic safety check for topics explicitly excluded from this POC.

    The LLM classifier can miss these, so the graph calls this before retrieval
    to avoid grounding an answer on adjacent-but-wrong OpenShift evidence.
    """
    q = question.lower()

    if any(term in q for term in ("servicenow", "jira", "ticketing")):
        return True

    if "ticket" in q and any(term in q for term in ("create", "open", "incident")):
        return True

    if "live cluster" in q or ("access" in q and "cluster" in q):
        return True

    if "latest" in q and any(term in q for term in ("released", "this week", "web")):
        return True

    if any(term in q for term in ("web search", "internet search", "search the web")):
        return True

    if "db2" in q:
        return True

    if any(term in q for term in ("python script", "write me a script", "write code")):
        return True

    if "automate" in q and any(term in q for term in ("deployment", "deployments", "script")):
        return True

    return False
