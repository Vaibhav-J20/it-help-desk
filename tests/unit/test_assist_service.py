"""Unit tests for assist service request mapping."""
from app.api.schemas import AssistRequest, RequestedScope
from app.services.assist_service import _scope_to_dict


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
