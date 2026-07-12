"""Unit tests for OpenSearch filter builder."""
from app.retrieval.filters import build_filters, relax_inferred_filters


def test_empty_scope_only_has_is_current():
    filters = build_filters({})
    assert filters == [{"term": {"is_current": True}}]


def test_ocp_version_added():
    filters = build_filters({"ocp_version": "4.16"})
    assert {"term": {"ocp_version": "4.16"}} in filters


def test_deployment_type_added():
    filters = build_filters({"deployment_type": "SNO"})
    assert {"term": {"deployment_type": "SNO"}} in filters


def test_domain_id_added():
    filters = build_filters({"domain_id": "ocp_sno_support"})
    assert {"term": {"domain_id": "ocp_sno_support"}} in filters


def test_component_maps_to_components_array():
    filters = build_filters({"component": "bootstrap"})
    assert {"term": {"components": "bootstrap"}} in filters


def test_is_current_always_present():
    filters = build_filters({"ocp_version": "4.16"})
    assert {"term": {"is_current": True}} in filters


def test_is_current_can_be_overridden():
    filters = build_filters({"is_current": False})
    assert {"term": {"is_current": False}} in filters
    assert {"term": {"is_current": True}} not in filters


def test_full_scope():
    scope = {
        "ocp_version": "4.16",
        "deployment_type": "SNO",
        "domain_id": "ocp_sno_support",
        "component": "dns",
    }
    filters = build_filters(scope)
    assert len(filters) == 5  # 4 scope fields + is_current


def test_relax_inferred_removes_component():
    filters = [
        {"term": {"ocp_version": "4.16"}},
        {"term": {"components": "bootstrap"}},
        {"term": {"is_current": True}},
    ]
    relaxed = relax_inferred_filters(filters, inferred_keys=["components"])
    assert {"term": {"components": "bootstrap"}} not in relaxed
    assert {"term": {"ocp_version": "4.16"}} in relaxed


def test_relax_inferred_keeps_explicit_version():
    filters = [
        {"term": {"ocp_version": "4.16"}},
        {"term": {"domain_id": "ocp_sno_support"}},
        {"term": {"is_current": True}},
    ]
    relaxed = relax_inferred_filters(filters, inferred_keys=["domain_id"])
    assert {"term": {"ocp_version": "4.16"}} in relaxed
    # domain_id is in _NEVER_RELAX — it must survive even when listed in inferred_keys
    assert {"term": {"domain_id": "ocp_sno_support"}} in relaxed


def test_relax_inferred_never_removes_domain_id():
    """domain_id must survive relax_inferred_filters regardless of inferred_keys."""
    filters = [
        {"term": {"domain_id": "watsonx_orchestrate"}},
        {"term": {"components": "adk"}},
        {"term": {"is_current": True}},
    ]
    relaxed = relax_inferred_filters(filters, inferred_keys=["domain_id", "components"])
    assert {"term": {"domain_id": "watsonx_orchestrate"}} in relaxed
    assert {"term": {"components": "adk"}} not in relaxed
    assert {"term": {"is_current": True}} in relaxed


def test_relax_inferred_never_removes_is_current():
    """is_current must survive relax_inferred_filters regardless of inferred_keys."""
    filters = [
        {"term": {"components": "dns"}},
        {"term": {"is_current": True}},
    ]
    relaxed = relax_inferred_filters(filters, inferred_keys=["is_current", "components"])
    assert {"term": {"is_current": True}} in relaxed
    assert {"term": {"components": "dns"}} not in relaxed
