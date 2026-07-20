"""Regression tests for dedicated-domain routing without global catalog scans."""

import pytest

from app.graph.nodes import resolve_scope


@pytest.mark.parametrize(
    ("domain_id", "question", "extra_scope"),
    [
        (
            "watsonx_orchestrate",
            "What did IBM announce about watsonx Orchestrate at Think 2026?",
            {},
        ),
        ("ibm_bob", "How do IBM Bob custom modes work?", {}),
        (
            "ocp_sno_support",
            "What DNS records are required for SNO 4.16?",
            {"ocp_version": "4.16", "deployment_type": "SNO"},
        ),
    ],
)
def test_dedicated_domain_does_not_scan_generic_product_catalog(
    monkeypatch,
    domain_id: str,
    question: str,
    extra_scope: dict,
):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("generic IBM product discovery must not run")

    monkeypatch.setattr(resolve_scope, "_match_enabled_ibm_product", unexpected)
    monkeypatch.setattr(resolve_scope, "_match_global_ibm_product", unexpected)

    result = resolve_scope.run({
        "user_question": question,
        "intent": "qa",
        "extracted_scope": {"domain_id": domain_id, **extra_scope},
        "trace": {},
    })

    assert result.get("status") not in {"OUT_OF_SCOPE", "ERROR"}
    assert result["extracted_scope"]["domain_id"] == domain_id
