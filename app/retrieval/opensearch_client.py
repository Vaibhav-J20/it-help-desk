"""
OpenSearch client factory.
Connection parameters come exclusively from settings — never hard-coded.
"""
from functools import lru_cache
from opensearchpy import OpenSearch, RequestsHttpConnection
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def get_opensearch_client() -> OpenSearch:
    """
    Return a cached OpenSearch client built from environment config.
    Validates that required settings are present before connecting.
    """
    settings = get_settings()

    if not settings.opensearch_url:
        raise RuntimeError("OPENSEARCH_URL is not configured.")

    # Parse host and port from the URL
    url = settings.opensearch_url.rstrip("/")
    use_ssl = url.startswith("https://")
    host_part = url.replace("https://", "").replace("http://", "")

    if ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_part
        port = 443 if use_ssl else 9200

    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=(settings.opensearch_username, settings.opensearch_password),
        use_ssl=use_ssl,
        verify_certs=False,          # set True in production with a real cert
        connection_class=RequestsHttpConnection,
        timeout=30,
    )
    logger.info(f"OpenSearch client initialised — {host}:{port}")
    return client


def ping_opensearch() -> bool:
    """Return True if OpenSearch is reachable, False otherwise."""
    try:
        return get_opensearch_client().ping()
    except Exception:
        return False
