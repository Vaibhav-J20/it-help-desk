"""Unit tests for domains_service — GET /v1/domains."""
from unittest.mock import MagicMock
from app.services.domains_service import get_domains


def _mock_client(buckets: list[dict]) -> MagicMock:
    """Return an OpenSearch client mock that yields the given aggregation buckets."""
    client = MagicMock()
    client.search.return_value = {
        "aggregations": {
            "by_domain": {"buckets": buckets}
        }
    }
    return client


def test_returns_all_domains_sorted_by_chunk_count():
    buckets = [
        {"key": "ibm_bob", "doc_count": 1136},
        {"key": "watsonx_orchestrate", "doc_count": 4869},
        {"key": "ocp_sno_support", "doc_count": 7940},
    ]
    result = get_domains(opensearch_client=_mock_client(buckets))
    domain_ids = [d.domain_id for d in result.domains]
    assert domain_ids == ["ocp_sno_support", "watsonx_orchestrate", "ibm_bob"]


def test_display_names_resolved():
    buckets = [{"key": "watsonx_orchestrate", "doc_count": 4869}]
    result = get_domains(opensearch_client=_mock_client(buckets))
    assert result.domains[0].display_name == "watsonx Orchestrate"


def test_unknown_domain_uses_key_as_display_name():
    buckets = [{"key": "some_future_domain", "doc_count": 100}]
    result = get_domains(opensearch_client=_mock_client(buckets))
    assert result.domains[0].display_name == "some_future_domain"


def test_empty_index_returns_empty_list():
    result = get_domains(opensearch_client=_mock_client([]))
    assert result.domains == []


def test_opensearch_failure_returns_empty_list():
    client = MagicMock()
    client.search.side_effect = Exception("connection refused")
    result = get_domains(opensearch_client=client)
    assert result.domains == []


def test_chunk_counts_correct():
    buckets = [
        {"key": "ocp_sno_support", "doc_count": 7940},
        {"key": "watsonx_orchestrate", "doc_count": 4869},
    ]
    result = get_domains(opensearch_client=_mock_client(buckets))
    by_id = {d.domain_id: d.chunk_count for d in result.domains}
    assert by_id["ocp_sno_support"] == 7940
    assert by_id["watsonx_orchestrate"] == 4869
