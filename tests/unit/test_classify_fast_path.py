"""Tests for the authoritative requested-scope classification fast path."""

from app.graph.nodes.classify_extract import run


def test_dedicated_product_scope_skips_redundant_model_call():
    def must_not_run(_prompt: str) -> str:
        raise AssertionError("classification model should not be called")

    result = run(
        {
            "user_question": (
                "What did IBM announce about watsonx Orchestrate at Think 2026?"
            ),
            "extracted_scope": {"domain_id": "watsonx_orchestrate"},
            "trace": {},
        },
        generate_fn=must_not_run,
    )

    assert result["intent"] == "qa"
    assert result["trace"]["classify_extract"]["source"] == "explicit_scope"


def test_explicit_generic_product_scope_skips_model_and_detects_troubleshooting():
    result = run(
        {
            "user_question": "IBM Instana is failing to collect host metrics.",
            "extracted_scope": {
                "domain_id": "ibm_products",
                "product": "IBM Instana Observability",
            },
            "trace": {},
        },
        generate_fn=lambda _prompt: (_ for _ in ()).throw(
            AssertionError("classification model should not be called")
        ),
    )

    assert result["intent"] == "troubleshoot"
    assert result["extracted_scope"]["product"] == "IBM Instana Observability"


def test_broad_ibm_products_domain_still_uses_model_for_product_extraction():
    calls = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        return """{
          "intent": "qa",
          "domain_id": "ibm_products",
          "product": "IBM Concert",
          "product_version": null,
          "ocp_version": null,
          "deployment_type": null,
          "component": null,
          "needs_clarification": false,
          "clarification_question": null
        }"""

    result = run(
        {
            "user_question": "What is IBM Concert?",
            "extracted_scope": {"domain_id": "ibm_products"},
            "trace": {},
        },
        generate_fn=generate,
    )

    assert len(calls) == 1
    assert result["extracted_scope"]["product"] == "IBM Concert"
    assert result["trace"]["classify_extract"]["source"] == "watsonx_model"


def test_unversioned_ocp_scope_keeps_model_clarification_path():
    calls = []

    def generate(_prompt: str) -> str:
        calls.append(True)
        return """{
          "intent": "qa",
          "domain_id": "ocp_sno_support",
          "product": null,
          "product_version": null,
          "ocp_version": null,
          "deployment_type": "SNO",
          "component": "installation",
          "needs_clarification": true,
          "clarification_question": "Which OpenShift version are you using?"
        }"""

    result = run(
        {
            "user_question": "How do I install SNO?",
            "extracted_scope": {"domain_id": "ocp_sno_support"},
            "trace": {},
        },
        generate_fn=generate,
    )

    assert len(calls) == 1
    assert result["required_clarification"] == "Which OpenShift version are you using?"
