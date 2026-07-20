"""Unit tests for assist service request mapping."""
from app.api.schemas import AssistRequest, RequestedScope
from app.services.assist_service import _scope_to_dict, _state_to_response


def test_scope_maps_ibm_bob_component_to_domain_id():
    request = AssistRequest(
        question="What is IBM Bob Agent mode?",
        requested_scope=RequestedScope(component="IBM Bob"),
    )

    assert _scope_to_dict(request) == {"domain_id": "ibm_bob"}


def test_scope_maps_orchestrate_component_to_domain_id():
    request = AssistRequest(
        question="How do I create a tool in watsonx Orchestrate?",
        requested_scope=RequestedScope(component="watsonx Orchestrate"),
    )

    assert _scope_to_dict(request) == {"domain_id": "watsonx_orchestrate"}


def test_scope_preserves_real_component_filter():
    request = AssistRequest(
        question="What DNS records are required for SNO?",
        requested_scope=RequestedScope(component="dns", ocp_version="4.16"),
    )

    assert _scope_to_dict(request) == {
        "ocp_version": "4.16",
        "component": "dns",
    }


def test_explicit_domain_id_takes_precedence_over_component_mapping():
    """explicit domain_id in RequestedScope must win over component→domain mapping."""
    request = AssistRequest(
        question="How do I use Bob?",
        requested_scope=RequestedScope(
            domain_id="ibm_bob",
            component="watsonx Orchestrate",  # would normally map to watsonx_orchestrate
        ),
    )
    result = _scope_to_dict(request)
    assert result["domain_id"] == "ibm_bob"


def test_explicit_domain_id_passed_through_directly():
    request = AssistRequest(
        question="How do I create an agent?",
        requested_scope=RequestedScope(domain_id="watsonx_orchestrate"),
    )
    result = _scope_to_dict(request)
    assert result == {"domain_id": "watsonx_orchestrate"}


def test_explicit_domain_id_with_ocp_scope():
    request = AssistRequest(
        question="How do I install SNO?",
        requested_scope=RequestedScope(
            domain_id="ocp_sno_support",
            ocp_version="4.16",
            deployment_type="SNO",
        ),
    )
    result = _scope_to_dict(request)
    assert result == {
        "domain_id": "ocp_sno_support",
        "ocp_version": "4.16",
        "deployment_type": "SNO",
    }


def test_empty_scope_returns_empty_dict():
    request = AssistRequest(question="What are the options?")
    result = _scope_to_dict(request)
    assert result == {}


def test_generic_product_scope_is_preserved():
    request = AssistRequest(
        question="How do I install it?",
        requested_scope=RequestedScope(
            domain_id="ibm_products",
            product="IBM MQ",
            product_version="9.4.x",
        ),
    )
    assert _scope_to_dict(request) == {
        "domain_id": "ibm_products",
        "product": "IBM MQ",
        "product_version": "9.4.x",
    }


def test_live_web_citation_changes_safety_note():
    response = _state_to_response(
        {
            "status": "ANSWERED",
            "intent": "qa",
            "answer_markdown": "Official finding [S1]",
            "citations": [{
                "citation_id": "S1",
                "title": "IBM Instana overview",
                "product": "IBM Instana Observability",
                "document_id": "web-1",
                "source_uri": "https://www.ibm.com/products/instana",
                "retrieval_origin": "official_live_web",
                "web_search_provider": "tavily-web-search",
            }],
            "trace": {
                "retrieve": {
                    "adaptive": {
                        "stages": [
                            {"stage": "opensearch", "candidate_count": 0},
                            {
                                "stage": "official_live_web",
                                "candidate_count": 1,
                                "provider": "tavily",
                            },
                        ],
                        "web_search_performed": True,
                        "web_search_provider": "tavily",
                    }
                }
            },
        },
        "request-1",
        "trace-1",
    )

    assert "live official IBM web results" in response.safety_note
    assert response.citations[0].retrieval_source == "internet_search"
    assert response.retrieval_provenance.answer_sources == ["internet_search"]
    assert response.retrieval_provenance.opensearch_searched is True
    assert response.retrieval_provenance.internet_search_performed is True
    assert response.retrieval_provenance.internet_search_provider == "tavily"
    assert response.answer_markdown.startswith(
        "> **Retrieval path:** OpenSearch → internet search (Tavily)"
    )
    assert "> **Answer grounded in:** internet search" in response.answer_markdown
    assert response.source_urls == ["https://www.ibm.com/products/instana"]
    assert response.suggested_next_steps
    assert "[IBM Instana overview](https://www.ibm.com/products/instana)" in (
        response.answer_markdown or ""
    )
    assert "### Suggested next steps" in (response.answer_markdown or "")


def test_insufficient_evidence_returns_helpful_recovery_instead_of_dead_end():
    response = _state_to_response(
        {
            "status": "INSUFFICIENT_EVIDENCE",
            "intent": "qa",
            "user_question": "How do I configure IBM Example 9.9?",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Example",
                "product_version": "9.9",
            },
            "candidates": [{
                "title": "IBM Example overview",
                "source_uri": "https://www.ibm.com/docs/en/example",
            }],
            "citations": [],
            "trace": {
                "retrieve": {
                    "adaptive": {
                        "stages": [{"stage": "opensearch", "candidate_count": 0}],
                        "web_search_performed": True,
                        "web_search_provider": "tavily",
                    }
                }
            },
        },
        "request-2",
        "trace-2",
    )

    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.answer_markdown
    assert "### The exact procedure could not be verified" in response.answer_markdown
    assert "https://www.ibm.com/docs/en/example" not in response.answer_markdown
    assert "I don't have" not in response.answer_markdown
    assert response.retrieval_provenance.internet_search_performed is True


def test_generic_install_next_step_has_correct_grammar():
    response = _state_to_response(
        {
            "status": "INSUFFICIENT_EVIDENCE",
            "intent": "qa",
            "user_question": "How do I install this?",
            "extracted_scope": {},
            "citations": [],
            "candidates": [],
            "trace": {},
        },
        "request-3",
        "trace-3",
    )

    assert response.suggested_next_steps[0].startswith(
        "Confirm the exact product version"
    )


def test_version_listing_removes_redundant_model_limitation():
    response = _state_to_response(
        {
            "status": "ANSWERED",
            "intent": "qa",
            "user_question": "What versions are available for IBM Example documentation?",
            "answer_markdown": (
                "### Available versions\n\nVersions 2.x and 1.1 are available [S1].\n\n"
                "### What this does not establish\n\nThis does not list every product release [S1]."
            ),
            "citations": [{
                "citation_id": "S1",
                "title": "Available versions",
                "product": "IBM Example",
                "document_id": "catalog:example",
                "source_uri": "https://www.ibm.com/docs/en/example",
                "retrieval_origin": "global_metadata_catalog",
            }],
            "trace": {
                "retrieve": {
                    "adaptive": {
                        "stages": [
                            {"stage": "opensearch", "candidate_count": 0},
                            {"stage": "global_metadata_catalog", "candidate_count": 1},
                        ]
                    }
                }
            },
        },
        "request-versions",
        "trace-versions",
    )

    assert "Versions 2.x and 1.1" in (response.answer_markdown or "")
    assert "What this does not establish" not in (response.answer_markdown or "")
    assert response.citations[0].retrieval_source == "metadata_catalog"
