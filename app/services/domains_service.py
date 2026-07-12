"""
Domains service — queries OpenSearch for per-domain chunk counts.
Does not call watsonx.ai. Safe to call frequently from the UI.
"""
from app.api.schemas import DomainInfo, DomainsResponse
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Canonical display names — kept here so the OpenAPI spec and UI stay in sync.
_DISPLAY_NAMES: dict[str, str] = {
    "ocp_sno_support": "OpenShift & SNO",
    "watsonx_orchestrate": "watsonx Orchestrate",
    "ibm_bob": "IBM Bob",
}


def get_domains(opensearch_client=None) -> DomainsResponse:
    """
    Return a DomainsResponse listing each domain currently indexed in the
    knowledge-chunks index together with its chunk count.

    Args:
        opensearch_client: Injected OpenSearch client (defaults to the shared
                           singleton). Injection is used in unit tests.
    """
    if opensearch_client is None:
        from app.retrieval.opensearch_client import get_opensearch_client
        opensearch_client = get_opensearch_client()

    settings = get_settings()
    index = settings.opensearch_index_chunks

    body = {
        "size": 0,
        "query": {"term": {"is_current": True}},
        "aggs": {
            "by_domain": {
                "terms": {"field": "domain_id", "size": 50}
            }
        },
    }

    try:
        resp = opensearch_client.search(index=index, body=body)
    except Exception as exc:
        logger.warning(f"domains_service: OpenSearch query failed — {exc}")
        return DomainsResponse(domains=[])

    buckets = resp.get("aggregations", {}).get("by_domain", {}).get("buckets", [])

    domain_list = [
        DomainInfo(
            domain_id=b["key"],
            display_name=_DISPLAY_NAMES.get(b["key"], b["key"]),
            chunk_count=b["doc_count"],
        )
        for b in sorted(buckets, key=lambda x: x["doc_count"], reverse=True)
    ]

    return DomainsResponse(domains=domain_list)
