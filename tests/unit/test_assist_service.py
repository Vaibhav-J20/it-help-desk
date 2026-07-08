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
