"""Unit tests for graph nodes (input_guard, evidence_gate, validate_citations)."""
import pytest
from app.graph.nodes.input_guard import run as input_guard
from app.graph.nodes.evidence_gate import run as evidence_gate
from app.graph.nodes.validate_citations import run as validate_citations
from app.graph.nodes.resolve_scope import run as resolve_scope
from app.graph.nodes.classify_extract import run as classify_extract
from app.graph.nodes import retrieve as retrieve_node
from app.graph.nodes import resolve_scope as resolve_scope_node
from app.graph.nodes import compose_answer as compose_answer_node


# ── input_guard ──────────────────────────────────────────────────────────────

def test_input_guard_passes_valid():
    state = {"user_question": "How do I configure SNO bootstrap?", "trace": {}}
    result = input_guard(state)
    assert result.get("status") != "INVALID_REQUEST"
    assert result["user_question"] == "How do I configure SNO bootstrap?"


def test_input_guard_rejects_empty():
    state = {"user_question": "", "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_rejects_too_short():
    state = {"user_question": "Hi", "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_rejects_too_long():
    state = {"user_question": "x" * 2001, "trace": {}}
    result = input_guard(state)
    assert result["status"] == "INVALID_REQUEST"


def test_input_guard_normalises_whitespace():
    state = {"user_question": "  How  do  I  install  SNO?  ", "trace": {}}
    result = input_guard(state)
    assert result["user_question"] == "How do I install SNO?"


def test_input_guard_clears_empty_context():
    state = {
        "user_question": "How does DNS work in SNO?",
        "conversation_context": [{"role": "user", "content": ""}],
        "trace": {},
    }
    result = input_guard(state)
    assert result["conversation_context"] == []


def test_compose_answer_leaves_retrieval_provenance_to_api_response():
    result = compose_answer_node.run(
        {
            "user_question": "What is IBM Example?",
            "candidates": [{
                "chunk_id": "web-1",
                "document_id": "web-doc-1",
                "title": "IBM Example overview",
                "product": "IBM Example",
                "product_version": "1.0",
                "source_uri": "https://www.ibm.com/products/example",
                "section_path": "Search result excerpt",
                "chunk_text": "IBM Example is an example product.",
                "retrieval_origin": "official_live_web",
            }],
            "trace": {},
        },
        generate_fn=lambda _prompt: "### IBM Example\n\nIBM Example is documented. [S1]",
    )

    assert result["answer_markdown"].startswith("### IBM Example")


# ── classify_extract ─────────────────────────────────────────────────────────

def test_classify_extract_explicit_scope_satisfies_general_clarification():
    def _generate(_prompt):
        return """
        {
          "intent": "troubleshoot",
          "ocp_version": null,
          "deployment_type": null,
          "component": "api_server",
          "needs_clarification": true,
          "clarification_question": "What version of OpenShift are you using and is it a standard or Single Node OpenShift deployment?"
        }
        """

    state = {
        "user_question": "The OpenShift API server is not responding after installation.",
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = classify_extract(state, generate_fn=_generate)
    assert result["required_clarification"] is None


def test_classify_extract_keeps_deployment_clarification_for_sno_question():
    def _generate(_prompt):
        return """
        {
          "intent": "troubleshoot",
          "ocp_version": null,
          "deployment_type": null,
          "component": "bootstrap",
          "needs_clarification": true,
          "clarification_question": "What version of OpenShift are you using and is it a standard or Single Node OpenShift deployment?"
        }
        """

    state = {
        "user_question": "My SNO bootstrap is timing out.",
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = classify_extract(state, generate_fn=_generate)
    assert result["required_clarification"] is not None


# ── resolve_scope ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "How do I create a ServiceNow ticket for an OpenShift incident?",
    "Can you access my live OpenShift cluster and check the node status?",
    "Write me a Python script to automate OpenShift deployments.",
])
def test_resolve_scope_routes_technical_openshift_requests_without_keyword_blocks(question):
    state = {
        "user_question": question,
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    }
    result = resolve_scope(state)
    assert result.get("status") != "OUT_OF_SCOPE"
    assert result["extracted_scope"]["domain_id"] == "ocp_sno_support"


def test_resolve_scope_keeps_unrelated_non_ibm_request_out_of_scope():
    result = resolve_scope({
        "user_question": "What is the latest version of Kubernetes released this week?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["status"] == "OUT_OF_SCOPE"


def test_resolve_scope_does_not_bind_generic_words_to_unrelated_catalog_product():
    result = resolve_scope({
        "user_question": "Give me information about the latest version released this week",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["status"] == "OUT_OF_SCOPE"


def test_resolve_scope_prefers_exact_product_identity_over_security_intent_words():
    result = resolve_scope({
        "user_question": (
            "How do I configure risk-based authentication in "
            "IBM Security Verify SaaS?"
        ),
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["extracted_scope"]["product"] == "IBM Security Verify"


def test_resolve_scope_recognizes_product_root_with_additional_intent_words():
    result = resolve_scope({
        "user_question": "How do I configure an Instana synthetic test?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["extracted_scope"]["product"] == "IBM Instana Observability"


def test_resolve_scope_requires_version_for_minimum_sno_hardware():
    result = resolve_scope({
        "user_question": (
            "What is the minimum hardware requirement for a Single Node "
            "OpenShift installation?"
        ),
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["required_clarification"] == "Which OpenShift version are you using?"


@pytest.mark.parametrize("question", [
    "How do I configure networking?",
    "What is the bootstrap process?",
    "How do I configure IBM Db2 on OpenShift?",
])
def test_resolve_scope_clarifies_broad_requests(question):
    result = resolve_scope({
        "user_question": question,
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["required_clarification"]


def test_all_ibm_products_routes_to_portfolio_instead_of_out_of_scope():
    result = resolve_scope_node.run({
        "user_question": "List me all the products IBM has",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result.get("status") != "OUT_OF_SCOPE"
    assert result["extracted_scope"] == {
        "domain_id": "ibm_products",
        "portfolio_family": "ibm",
    }
    assert result["trace"]["resolve_scope"] == "portfolio_query"
    assert {"term": {"domain_id": "ibm_products"}} in result["retrieval_filters"]


def test_watsonx_portfolio_overrides_accidental_orchestrate_scope():
    result = resolve_scope_node.run({
        "user_question": "What are the watsonx products that IBM has to offer?",
        "intent": "qa",
        "extracted_scope": {"domain_id": "watsonx_orchestrate"},
        "trace": {"explicit_scope_keys": ["domain_id"]},
    })

    assert result.get("status") != "OUT_OF_SCOPE"
    assert result["extracted_scope"] == {
        "domain_id": "ibm_products",
        "portfolio_family": "watsonx",
    }
    assert result["trace"]["overrode_domain_hint"] == "watsonx_orchestrate"


def test_product_relationship_question_is_not_mistaken_for_portfolio_listing(
    monkeypatch,
):
    monkeypatch.setattr(
        resolve_scope_node,
        "_match_enabled_ibm_product",
        lambda *_args, **_kwargs: resolve_scope_node.IBMProductMatch(
            "IBM Instana Observability", "current", False, ("current",)
        ),
    )
    result = resolve_scope_node.run({
        "user_question": "Which IBM products integrate with Instana?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["trace"]["resolve_scope"] == "in_scope"
    assert "portfolio_family" not in result["extracted_scope"]


def test_unregistered_ibm_product_remains_eligible_for_official_web_search(
    monkeypatch,
):
    monkeypatch.setattr(
        resolve_scope_node, "_match_enabled_ibm_product", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        resolve_scope_node, "_match_global_ibm_product", lambda *_a, **_k: None
    )
    result = resolve_scope_node.run({
        "user_question": "What is IBM FutureProduct and what does it do?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result.get("status") != "OUT_OF_SCOPE"
    assert result["extracted_scope"]["domain_id"] == "ibm_products"
    assert {"term": {"domain_id": "ibm_products"}} in result["retrieval_filters"]


def test_resolve_scope_preserves_both_versions_for_comparison():
    result = resolve_scope({
        "user_question": (
            "What changed in the SNO installation process between OCP 4.14 "
            "and OCP 4.16?"
        ),
        "intent": "qa",
        "required_clarification": "Which OpenShift version are you using?",
        "extracted_scope": {"ocp_version": "4.16", "deployment_type": "SNO"},
        "trace": {},
    })

    assert result.get("status") != "NEEDS_CLARIFICATION"
    assert result["extracted_scope"]["ocp_versions"] == ["4.14", "4.16"]
    assert {"terms": {"ocp_version": ["4.14", "4.16"]}} in result["retrieval_filters"]


def test_generic_ibm_product_scope_adds_strict_product_and_version(monkeypatch):
    monkeypatch.setattr(
        resolve_scope_node,
        "_match_enabled_ibm_product",
        lambda *_args, **_kwargs: resolve_scope_node.IBMProductMatch(
            "IBM MQ", "9.4.x", False, ("9.4.x",)
        ),
    )
    result = resolve_scope_node.run({
        "user_question": "How do I install IBM MQ 9.4.x?",
        "intent": "qa",
        "extracted_scope": {"domain_id": "ibm_products"},
        "trace": {},
    })
    assert {"term": {"product": "IBM MQ"}} in result["retrieval_filters"]
    assert {"term": {"product_version": "9.4.x"}} in result["retrieval_filters"]


def test_dedicated_domain_discards_free_text_classifier_product_filter():
    result = resolve_scope_node.run({
        "user_question": "What command runs must-gather in OpenShift 4.16?",
        "intent": "qa",
        "extracted_scope": {
            "domain_id": "ocp_sno_support",
            "ocp_version": "4.16",
            "product": "OpenShift Container Platform",
            "product_version": "4.16",
        },
        "trace": {},
    })

    assert {"term": {"domain_id": "ocp_sno_support"}} in result["retrieval_filters"]
    assert {"term": {"ocp_version": "4.16"}} in result["retrieval_filters"]
    assert not any("product" in clause.get("term", {}) for clause in result["retrieval_filters"])


def test_version_listing_ignores_unnecessary_classifier_clarification(monkeypatch):
    monkeypatch.setattr(
        resolve_scope_node,
        "_match_enabled_ibm_product",
        lambda *_args, **_kwargs: resolve_scope_node.IBMProductMatch(
            "IBM watsonx Code Assistant for Z",
            None,
            False,
            ("1.1.x", "1.2.x"),
            catalog_content_key="WCAZ_1.2.x",
        ),
    )
    result = resolve_scope_node.run({
        "user_question": (
            "What versions are available for IBM watsonx Code Assistant for Z "
            "documentation?"
        ),
        "intent": "qa",
        "required_clarification": (
            "What specific information about the versions are you looking for?"
        ),
        "extracted_scope": {"domain_id": "ibm_products"},
        "trace": {},
    })

    assert result.get("status") != "NEEDS_CLARIFICATION"
    assert result["required_clarification"] is None
    assert result["extracted_scope"]["product"] == (
        "IBM watsonx Code Assistant for Z"
    )


def test_generic_ibm_command_question_clarifies_when_multiple_versions(monkeypatch):
    monkeypatch.setattr(
        resolve_scope_node,
        "_match_enabled_ibm_product",
        lambda *_args, **_kwargs: resolve_scope_node.IBMProductMatch(
            "IBM MQ", None, True, ("9.3.x", "9.4.x")
        ),
    )
    result = resolve_scope_node.run({
        "user_question": "Which command installs IBM MQ?",
        "intent": "qa",
        "extracted_scope": {"domain_id": "ibm_products"},
        "trace": {},
    })
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["required_clarification"] == "Which IBM MQ version are you using?"


def test_known_guardium_unavailable_version_needs_clarification():
    result = resolve_scope_node.run({
        "user_question": "Help me install Guardium 11.8",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    })

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["trace"]["resolve_scope"] == "known_product_unavailable_version"
    assert "11.8" in result["required_clarification"]
    assert "12.x" in result["required_clarification"]


def test_known_guardium_explicit_unavailable_version_needs_clarification():
    result = resolve_scope_node.run({
        "user_question": "Help me install Guardium",
        "intent": "qa",
        "extracted_scope": {
            "domain_id": "ibm_products",
            "product": "IBM Guardium Data Protection",
            "product_version": "11.8",
        },
        "trace": {},
    })

    assert result["status"] == "NEEDS_CLARIFICATION"
    assert "11.8" in result["required_clarification"]


def test_wildcard_product_version_family_matches_specific_minor():
    assert resolve_scope_node._versions_match("12.1", "12.x")
    assert resolve_scope_node._versions_match("11.5", "11.5.x")
    assert not resolve_scope_node._versions_match("11.8", "12.x")


def test_broken_ibm_registry_logs_warning_and_fails_closed(monkeypatch):
    from app.ingestion.ibm_docs_crawler import registry as registry_module

    warnings = []

    class CapturingLogger:
        def warning(self, message):
            warnings.append(message)

    monkeypatch.setattr(
        registry_module,
        "load_registry",
        lambda: (_ for _ in ()).throw(registry_module.RegistryError("malformed registry")),
    )
    monkeypatch.setattr(resolve_scope_node, "logger", CapturingLogger())
    assert resolve_scope_node._match_enabled_ibm_product("ibm mq") is None
    assert any("malformed registry" in warning for warning in warnings)


def test_resolve_scope_clarifies_nmstateconfig_without_version():
    state = {
        "user_question": "What is the purpose of the NMStateConfig manifest in the agent-based installer?",
        "intent": "qa",
        "extracted_scope": {},
        "trace": {},
    }
    result = resolve_scope(state)
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert "version" in result["required_clarification"].lower()


# ── retrieve ─────────────────────────────────────────────────────────────────

def test_retrieve_relaxes_component_and_inferred_deployment_filters(monkeypatch):
    calls = []

    def _hybrid_retrieve(query, filters, opensearch_client, embedding_fn):
        calls.append(filters)
        return [] if len(calls) == 1 else [{"chunk_id": "c1"}]

    monkeypatch.setattr(
        "app.retrieval.hybrid_retriever.hybrid_retrieve",
        _hybrid_retrieve,
    )
    state = {
        "user_question": "What is the rendezvous host in the Agent-based Installer workflow?",
        "retrieval_query": "What is the rendezvous host in the Agent-based Installer workflow?",
        "retrieval_filters": [
            {"term": {"components": "api_server"}},
            {"term": {"deployment_type": "compact"}},
            {"term": {"domain_id": "ocp_sno_support"}},
            {"term": {"is_current": True}},
        ],
        "trace": {},
    }

    result = retrieve_node.run(state, opensearch_client=object(), embedding_fn=lambda _: [0.0])

    assert result["candidates"] == [{"chunk_id": "c1"}]
    assert {"term": {"components": "api_server"}} not in calls[1]
    assert {"term": {"deployment_type": "compact"}} not in calls[1]
    # domain_id and is_current must survive the retry — never removed.
    assert {"term": {"domain_id": "ocp_sno_support"}} in calls[1]
    assert {"term": {"is_current": True}} in calls[1]


def test_retrieve_never_relaxes_domain_id(monkeypatch):
    """domain_id must always be preserved on zero-hit retry to prevent cross-domain leakage."""
    calls = []

    def _hybrid_retrieve(query, filters, opensearch_client, embedding_fn):
        calls.append(filters)
        return []   # always empty — forces the retry path

    monkeypatch.setattr(
        "app.retrieval.hybrid_retriever.hybrid_retrieve",
        _hybrid_retrieve,
    )
    state = {
        "user_question": "How do I set up an agent in Orchestrate?",
        "retrieval_query": "How do I set up an agent in Orchestrate?",
        "retrieval_filters": [
            {"term": {"domain_id": "watsonx_orchestrate"}},
            {"term": {"components": "agents"}},
            {"term": {"is_current": True}},
        ],
        "trace": {},
    }

    retrieve_node.run(state, opensearch_client=object(), embedding_fn=lambda _: [0.0])

    # Both calls must have domain_id — it must never be relaxed.
    assert len(calls) == 2
    for call_filters in calls:
        assert {"term": {"domain_id": "watsonx_orchestrate"}} in call_filters


def test_retrieve_keeps_explicit_deployment_filter(monkeypatch):
    calls = []

    def _hybrid_retrieve(query, filters, opensearch_client, embedding_fn):
        calls.append(filters)
        return []

    monkeypatch.setattr(
        "app.retrieval.hybrid_retriever.hybrid_retrieve",
        _hybrid_retrieve,
    )
    state = {
        "user_question": "What changed in the installation process?",
        "retrieval_query": "What changed in the installation process?",
        "retrieval_filters": [
            {"term": {"deployment_type": "SNO"}},
            {"term": {"is_current": True}},
        ],
        "trace": {"explicit_scope_keys": ["deployment_type"]},
    }

    retrieve_node.run(state, opensearch_client=object(), embedding_fn=lambda _: [0.0])

    assert {"term": {"deployment_type": "SNO"}} in calls[1]


# ── evidence_gate ─────────────────────────────────────────────────────────────

def _chunk(version="4.16"):
    return {
        "chunk_id": "c1",
        "ocp_version": version,
        "title": "SNO Guide",
        "chunk_text": "text",
        "document_id": "d1",
    }


def test_evidence_gate_sufficient():
    state = {
        "candidates": [_chunk("4.16")],
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = evidence_gate(state)
    assert result.get("status") != "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "sufficient"


def test_evidence_gate_no_candidates():
    state = {"candidates": [], "extracted_scope": {}, "trace": {}}
    result = evidence_gate(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "insufficient"


def test_evidence_gate_version_mismatch():
    state = {
        "candidates": [_chunk("4.14")],
        "extracted_scope": {"ocp_version": "4.16"},
        "trace": {},
    }
    result = evidence_gate(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"


def test_evidence_gate_accepts_product_version_family_shorthand():
    state = {
        "candidates": [{
            **_chunk(None),
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4.x",
        }],
        "extracted_scope": {
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4",
        },
        "trace": {},
    }

    result = evidence_gate(state)

    assert result.get("status") != "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "sufficient"


def test_evidence_gate_rejects_wrong_product_version():
    state = {
        "candidates": [{
            **_chunk(None),
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.3.x",
        }],
        "extracted_scope": {
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4",
        },
        "trace": {},
    }

    result = evidence_gate(state)

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["trace"]["evidence_gate"]["reason"] == "version_mismatch"


def test_evidence_gate_honors_explicit_future_release_applicability():
    state = {
        "candidates": [{
            **_chunk(None),
            "product": "IBM Cloud Pak for Data",
            "product_version": "4.7.0; and future releases",
        }],
        "extracted_scope": {
            "product": "IBM Cloud Pak for Data",
            "product_version": "5.4",
        },
        "trace": {},
    }

    result = evidence_gate(state)

    assert result.get("status") != "INSUFFICIENT_EVIDENCE"
    assert result["evidence_decision"] == "sufficient"


def test_evidence_gate_rejects_wrong_explicit_platform():
    state = {
        "user_question": "How to install Guardium on Windows?",
        "candidates": [{
            **_chunk(None),
            "product": "IBM Guardium Data Protection",
            "title": "Linux-UNIX: Install and configure S-TAPs",
            "section_path": "Procedure",
            "chunk_text": "Install the S-TAP on a Linux or UNIX server.",
            "source_uri": "https://www.ibm.com/docs/en/gdp/12.x?topic=linux-install",
        }],
        "extracted_scope": {
            "domain_id": "ibm_products",
            "product": "IBM Guardium Data Protection",
            "product_version": "12.x",
        },
        "trace": {},
    }

    result = evidence_gate(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["trace"]["evidence_gate"]["reason"] == "explicit_platform_mismatch"


# ── validate_citations ────────────────────────────────────────────────────────

def test_validate_citations_valid():
    state = {
        "answer_markdown": "Check the DNS config [S1].",
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    assert result["status"] == "ANSWERED"
    assert len(result["citations"]) == 1
    assert result["citations"][0]["citation_id"] == "S1"


def test_compose_answer_normalizes_gpt_oss_citation_glyphs():
    from app.graph.nodes.compose_answer import run as compose_answer

    state = {
        "user_question": "What is required?",
        "candidates": [_chunk()],
        "trace": {},
    }
    result = compose_answer(
        state,
        generate_fn=lambda _prompt: "The requirement is documented【S1】.",
    )

    assert result["answer_markdown"] == "The requirement is documented[S1]."


def test_validate_citations_no_citations_returns_insufficient():
    """An answer with zero [S#] tags is ungrounded → INSUFFICIENT_EVIDENCE."""
    state = {
        "answer_markdown": "No citations here.",
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["answer_markdown"] is None
    assert result["trace"]["validate_citations"]["reason"] == "no_citations"


def test_validate_citations_invalid_index():
    state = {
        "answer_markdown": "See [S5] for details.",  # only 1 candidate
        "candidates": [_chunk()],
        "trace": {},
    }
    result = validate_citations(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["answer_markdown"] is None


def test_validate_citations_rejects_refusal_in_main_answer():
    state = {
        "answer_markdown": (
            "### Answer\nThe provided evidence does not include the requested "
            "procedure [S1].\n\n### Sources\n[S1] Source"
        ),
        "candidates": [_chunk()],
        "trace": {},
    }

    result = validate_citations(state)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["trace"]["validate_citations"]["reason"] == (
        "answer_disclaims_requested_evidence"
    )


def test_validate_citations_requests_one_broader_retry_after_indexed_non_answer():
    state = {
        "answer_markdown": (
            "### Answer\nThere is no information available about Think 2026 [S1]."
        ),
        "candidates": [_chunk()],
        "trace": {
            "retrieve": {
                "adaptive": {"selected_stage": "opensearch", "stages": []}
            }
        },
    }

    result = validate_citations(state)

    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["trace"]["adaptive_retry_requested"] is True
    assert result["trace"]["validate_citations"]["adaptive_retry_requested"] is True


def test_validate_citations_allows_bounded_limitations_section():
    state = {
        "answer_markdown": (
            "### Answer\nRun the documented diagnostic command [S1].\n\n"
            "### What this does not establish\nThe evidence does not include "
            "every optional tuning setting.\n\n### Sources\n[S1] Source"
        ),
        "candidates": [_chunk()],
        "trace": {},
    }

    result = validate_citations(state)
    assert result["status"] == "ANSWERED"
    assert len(result["citations"]) == 1
