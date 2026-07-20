"""
Assist service — orchestrates the LangGraph workflow for the POST /v1/assist route.
"""
import uuid
import re
from urllib.parse import urlsplit
from app.api.schemas import (
    AssistRequest,
    AssistResponse,
    Citation,
    RetrievalProvenance,
)
from app.graph.state import SupportState
from app.graph.workflow import support_graph
from app.observability.logging import get_logger, log_request_event
from app.retrieval.section_ranker import candidate_set_is_confident
import time

logger = get_logger(__name__)


def handle_request(request: AssistRequest) -> AssistResponse:
    """
    Entry point for POST /v1/assist.
    Builds initial state, runs the LangGraph workflow, maps terminal state to response.
    """
    request_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    start_ms = time.monotonic()

    requested_scope = _scope_to_dict(request)
    initial_state: SupportState = {
        "request_id": request_id,
        "user_question": request.question,
        "conversation_context": [m.model_dump() for m in request.conversation_context],
        "extracted_scope": requested_scope,
        "trace": {
            "trace_id": trace_id,
            "explicit_scope_keys": sorted(requested_scope),
        },
    }

    try:
        final_state: SupportState = support_graph.invoke(initial_state)
    except Exception as e:
        logger.info(f"Graph execution error: {e}")
        log_request_event(
            logger, "support_request_error",
            request_id=request_id, trace_id=trace_id,
            error=str(e),
        )
        return AssistResponse(
            request_id=request_id,
            status="ERROR",
            trace_id=trace_id,
        )

    total_ms = round((time.monotonic() - start_ms) * 1000)
    status = final_state.get("status", "ERROR")

    log_request_event(
        logger, "support_request_complete",
        request_id=request_id,
        trace_id=trace_id,
        status=status,
        intent=final_state.get("intent"),
        candidate_count=len(final_state.get("candidates") or []),
        evidence_chunk_count=len(final_state.get("citations") or []),
        total_ms=total_ms,
    )

    return _state_to_response(final_state, request_id, trace_id)


def _scope_to_dict(request: AssistRequest) -> dict:
    scope = {}
    # domain_id from RequestedScope takes precedence over classifier inference
    # and over any component-based domain mapping below.
    if request.requested_scope.domain_id:
        scope["domain_id"] = request.requested_scope.domain_id
    if request.requested_scope.ocp_version:
        scope["ocp_version"] = request.requested_scope.ocp_version
    if request.requested_scope.deployment_type:
        scope["deployment_type"] = request.requested_scope.deployment_type
    if request.requested_scope.component:
        # Only apply component→domain mapping when no explicit domain_id was given.
        component_scope = _normalise_component_scope(request.requested_scope.component)
        if "domain_id" not in scope:
            scope.update(component_scope)
        elif "domain_id" in component_scope:
            # Explicit domain_id wins; still carry through non-domain keys (e.g. component).
            scope.update({k: v for k, v in component_scope.items() if k != "domain_id"})
        else:
            scope.update(component_scope)
    if request.requested_scope.product:
        scope["product"] = request.requested_scope.product
    if request.requested_scope.product_version:
        scope["product_version"] = request.requested_scope.product_version
    return scope


def _normalise_component_scope(component: str) -> dict:
    """
    Orchestrate sometimes sends product/domain names in requested_scope.component.
    Map those to domain filters so they do not become impossible component filters.
    """
    value = component.strip()
    key = value.lower()

    if key in {"ibm bob", "bob", "bob ide"}:
        return {"domain_id": "ibm_bob"}

    if key in {
        "watsonx orchestrate",
        "ibm watsonx orchestrate",
        "orchestrate",
        "orchestrate adk",
    }:
        return {"domain_id": "watsonx_orchestrate"}

    if key in {
        "openshift",
        "open shift",
        "ocp",
        "openshift container platform",
        "sno",
        "single node openshift",
    }:
        return {"domain_id": "ocp_sno_support"}

    return {"component": value}


def _state_to_response(state: SupportState, request_id: str, trace_id: str) -> AssistResponse:
    raw_citations = state.get("citations") or []
    provenance = _retrieval_provenance(state, raw_citations)
    citations = [
        Citation(**{**citation, "retrieval_source": _citation_source(citation)})
        for citation in raw_citations
    ]
    used_live_web = any(
        citation.get("retrieval_origin") == "official_live_web"
        for citation in raw_citations
    )
    safety_note = (
        "This answer includes live official IBM web results that were not "
        "previously indexed; verify commands and product versions in your environment."
        if used_live_web else
        "Guidance is based only on the approved knowledge base; verify commands "
        "in your environment."
    )

    status = state.get("status", "ERROR")
    suggested_next_steps = _suggested_next_steps(state)
    source_urls = list(dict.fromkeys(
        citation.source_uri
        for citation in citations
        if citation.source_uri and _is_clickable_url(citation.source_uri)
    ))
    answer_markdown = state.get("answer_markdown")
    if answer_markdown:
        answer_markdown = _render_answer(
            answer_markdown,
            citations,
            provenance,
            suggested_next_steps,
            question=str(state.get("user_question") or ""),
        )
    elif status == "INSUFFICIENT_EVIDENCE":
        answer_markdown = _evidence_exhausted_answer(
            state,
            provenance,
            suggested_next_steps,
        )
    elif status == "OUT_OF_SCOPE":
        answer_markdown = _scope_recovery_answer(suggested_next_steps)

    return AssistResponse(
        request_id=request_id,
        status=status,
        intent=state.get("intent"),
        answer_markdown=answer_markdown,
        clarification_question=state.get("required_clarification"),
        citations=citations,
        source_urls=source_urls,
        suggested_next_steps=suggested_next_steps,
        retrieval_provenance=provenance,
        safety_note=safety_note,
        trace_id=trace_id,
    )


def _render_answer(
    answer: str,
    citations: list[Citation],
    provenance: RetrievalProvenance,
    next_steps: list[str],
    *,
    question: str,
) -> str:
    """Render deterministic provenance, next steps, and clickable sources."""
    body = re.split(r"(?im)^\s*###\s+Sources\s*$", answer, maxsplit=1)[0]
    body = re.split(
        r"(?im)^\s*###\s+(?:Suggested\s+)?Next\s+steps\s*$",
        body,
        maxsplit=1,
    )[0].rstrip()
    if _is_version_listing_question(question):
        body = re.split(
            r"(?im)^\s*###\s+What this does not establish\s*$",
            body,
            maxsplit=1,
        )[0].rstrip()
    parts = [_provenance_banner(provenance), body]
    if next_steps:
        parts.append(
            "### Suggested next steps\n\n"
            + "\n".join(f"- {step}" for step in next_steps)
        )
    if citations:
        parts.append(_sources_markdown(citations))
    return "\n\n".join(part for part in parts if part.strip()).strip()


def _is_version_listing_question(question: str) -> bool:
    lowered = question.casefold()
    return any(phrase in lowered for phrase in (
        "versions available", "available versions", "what versions",
        "which versions", "list versions", "documentation versions",
    ))


def _provenance_banner(provenance: RetrievalProvenance) -> str:
    """Show both the attempted retrieval path and the evidence actually used."""
    searched: list[str] = []
    if provenance.opensearch_searched:
        searched.append("OpenSearch")
    if provenance.metadata_catalog_searched:
        searched.append("IBM Docs catalog")
    if provenance.live_ibm_docs_retrieved:
        searched.append("live IBM Docs")
    if provenance.internet_search_performed:
        provider = provenance.internet_search_provider or "configured provider"
        searched.append(f"internet search ({provider.title()})")
    route = " → ".join(searched) if searched else "No retrieval source completed"

    used_labels = {
        "opensearch_index": "OpenSearch",
        "metadata_catalog": "IBM Docs catalog",
        "ibm_docs_cache": "cached IBM documentation",
        "live_ibm_docs": "live IBM documentation",
        "internet_search": "internet search",
    }
    used = ", ".join(
        used_labels[source] for source in provenance.answer_sources
    ) or "none"
    return (
        f"> **Retrieval path:** {route}  \n"
        f"> **Answer grounded in:** {used}"
    )


def _sources_markdown(citations: list[Citation]) -> str:
    lines = ["### Sources"]
    for citation in citations:
        title = _markdown_label(citation.title or "Source")
        product = _markdown_label(citation.product or "IBM documentation")
        version = citation.ocp_version or citation.product_version
        detail = product + (f" {version}" if version else "")
        if citation.page_start:
            page_label = (
                f"pp. {citation.page_start}–{citation.page_end}"
                if citation.page_end and citation.page_end != citation.page_start
                else f"p. {citation.page_start}"
            )
            detail += f", {page_label}"
        if citation.source_uri and _is_clickable_url(citation.source_uri):
            source = f"[{title}]({citation.source_uri})"
        else:
            source = title
        lines.append(f"- [{citation.citation_id}] {source} — {detail}")
    return "\n".join(lines)


def _evidence_exhausted_answer(
    state: SupportState,
    provenance: RetrievalProvenance,
    next_steps: list[str],
) -> str:
    attempts = []
    if provenance.opensearch_searched:
        attempts.append("the pre-existing OpenSearch knowledge index")
    if provenance.live_ibm_docs_retrieved:
        attempts.append("cached and live official IBM documentation pages")
    if provenance.internet_search_performed:
        provider = provenance.internet_search_provider or "the configured provider"
        attempts.append(f"approved internet sources through {provider.title()}")
    attempted = ", ".join(attempts) if attempts else "the configured enterprise sources"

    question = str(state.get("user_question") or "").strip()
    lowered = question.casefold()
    if any(term in lowered for term in (
        "announce", "announced", "latest", "current", "recent", "today",
    )):
        title = "### No verified current source matched the request"
        explanation = (
            f"I searched {attempted}, but the returned official material did not "
            "specifically establish the requested announcement or current fact. "
            "That does not prove the event did not occur; it means the available "
            "sources did not support a reliable answer."
        )
    elif any(term in lowered for term in (
        "command", "install", "configure", "rotate", "procedure", "steps",
    )):
        title = "### The exact procedure could not be verified"
        explanation = (
            f"I searched {attempted}, but none of the returned official material "
            "contained a sufficiently specific, version-matched procedure or "
            "command sequence. I did not combine unrelated commands or versions."
        )
    else:
        title = "### No sufficiently specific source matched the request"
        explanation = (
            f"I searched {attempted}. The returned material was not specific "
            "enough to answer the question reliably without guessing."
        )

    parts = [_provenance_banner(provenance), title, explanation]
    checked = _candidate_source_links(
        state.get("candidates") or [],
        question=str(state.get("user_question") or ""),
        product=str((state.get("extracted_scope") or {}).get("product") or ""),
    )
    if checked:
        parts.append(
            "### Relevant official pages found\n\n"
            + "\n".join(f"- [{_markdown_label(title)}]({url})" for title, url in checked)
        )
    if next_steps:
        parts.append(
            "### Suggested next steps\n\n"
            + "\n".join(f"- {step}" for step in next_steps)
        )
    return "\n\n".join(parts)


def _scope_recovery_answer(next_steps: list[str]) -> str:
    parts = [
        "### Clarify the technical product or platform",
        (
            "This service searches enterprise documentation for IBM products and "
            "OpenShift/OCP. Include the product name and the technical outcome you "
            "want so the request can be routed to indexed, live, and internet sources."
        ),
    ]
    if next_steps:
        parts.append(
            "### Suggested next steps\n\n"
            + "\n".join(f"- {step}" for step in next_steps)
        )
    return "\n\n".join(parts)


def _suggested_next_steps(state: SupportState) -> list[str]:
    question = str(state.get("user_question") or "")
    lowered = question.casefold()
    scope = state.get("extracted_scope") or {}
    domain_labels = {
        "ocp_sno_support": "OpenShift",
        "watsonx_orchestrate": "watsonx Orchestrate",
        "ibm_bob": "IBM Bob",
    }
    product = str(
        scope.get("product")
        or domain_labels.get(str(scope.get("domain_id") or ""))
        or "the product"
    )
    version = str(
        scope.get("ocp_version") or scope.get("product_version") or ""
    )
    product_label = f"{product} {version}".strip()
    if state.get("status") == "OUT_OF_SCOPE":
        return [
            "Name the IBM or OpenShift product you are working with.",
            "Describe whether you need installation, configuration, commands, troubleshooting, or product information.",
        ]
    if any(term in lowered for term in (
        "announce", "announced", "latest", "current", "recent", "today",
    )):
        return [
            "Ask for a capability-by-capability comparison with the previous release.",
            "Ask what IBM documented about preview access, availability, and rollout.",
            "Ask for the announced architecture and governance workflow with official sources.",
        ]
    if any(term in lowered for term in (
        "products", "offerings", "portfolio", "product list",
    )):
        return [
            "Compare the listed products by use case and intended user.",
            "Describe your goal and ask which product best fits it.",
            "Ask for the current documentation link for a specific product.",
        ]
    if any(term in lowered for term in (
        "versions available", "available versions", "what versions",
        "which versions", "documentation versions",
    )):
        return [
            "Ask what changed between two of the listed versions.",
            "Ask for installation or upgrade guidance for one exact version.",
            "Ask which platforms are documented for the selected version.",
        ]
    if "dns" in lowered:
        return [
            f"Ask for the complete {product_label} DNS checklist for your deployment type.",
            "Ask for commands to validate forward, wildcard, and reverse DNS resolution.",
            "Share the cluster name and base domain for a concrete validation checklist.",
        ]
    if (
        any(term in lowered for term in ("certificate", "tls", "ssl"))
        and any(term in lowered for term in (
            "rotate", "rotating", "rotation", "renew", "refresh", "lifespan",
        ))
    ):
        return [
            f"Ask how to inspect the current certificate and renewal status for {product_label}.",
            "Ask what the official documentation says about changing the certificate lifespan.",
            "If automatic renewal failed, share the certificate dates, affected services, and exact error.",
        ]
    if state.get("intent") == "troubleshoot" or any(
        term in lowered for term in ("error", "failed", "failure", "not working", "troubleshoot")
    ):
        return [
            "Share the exact error text and the command or action that produced it.",
            "Provide the product version, operating system, and deployment environment.",
            "Ask for a source-grounded diagnostic checklist before applying changes.",
        ]
    if any(term in lowered for term in ("install", "setup", "deploy")):
        first_step = (
            f"Ask for the prerequisite and compatibility checklist for {product_label}."
            if version else
            "Confirm the exact product version and target operating system or platform."
        )
        return [
            first_step,
            "Ask for documented verification commands and expected results.",
            "After each step, share the output or error for targeted troubleshooting.",
        ]
    if any(term in lowered for term in ("what is", "overview", "brief", "about")):
        return [
            f"Ask for the main use cases and capabilities of {product}.",
            f"Ask for {product} architecture, deployment options, or prerequisites.",
            f"Ask for the current official documentation links for {product}.",
        ]
    return [
        f"Ask for version-specific installation or configuration guidance for {product}.",
        "Ask for the exact documented commands, prerequisites, or supported platforms.",
        "Share your version and environment for a more precise answer.",
    ]


def _candidate_source_links(
    candidates: list[dict],
    *,
    question: str,
    product: str,
) -> list[tuple[str, str]]:
    stop_words = {
        "about", "according", "and", "are", "data", "documented", "documentation",
        "for", "from", "how", "ibm", "internal", "pak", "steps", "the", "to",
        "what", "with",
    }
    product_tokens = {
        token for token in re.findall(r"[a-z0-9]+", product.casefold())
    }
    query_tokens = {
        token for token in re.findall(r"[a-z0-9]+", question.casefold())
        if len(token) >= 3 and token not in stop_words and token not in product_tokens
    }
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate.get("source_uri") or "").strip()
        if not _is_clickable_url(url) or url in seen:
            continue
        # A page shown under "Relevant official pages" must independently
        # support the requested topic and intent. The previous two-token rule
        # admitted unrelated ADK and Docling pages for an exact Think 2026
        # announcement question.
        if not candidate_set_is_confident(question, [candidate]):
            continue
        haystack = " ".join((
            str(candidate.get("title") or ""),
            str(candidate.get("section_path") or ""),
            str(candidate.get("chunk_text") or ""),
            url,
        )).casefold()
        matched = {token for token in query_tokens if token in haystack}
        if query_tokens and len(matched) < min(2, len(query_tokens)):
            continue
        seen.add(url)
        output.append((str(candidate.get("title") or "Official source"), url))
        if len(output) >= 5:
            break
    return output


def _is_clickable_url(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and not parsed.username
        and not parsed.password
    )


def _markdown_label(value: str) -> str:
    cleaned = re.sub(r"[\[\]\r\n]+", " ", value).strip()
    words = cleaned.split()
    output: list[str] = []
    for word in words:
        if output and output[-1].casefold() == word.casefold():
            continue
        output.append(word)
    return " ".join(output)


def _citation_source(citation: dict) -> str:
    origin = str(citation.get("retrieval_origin") or "opensearch")
    provider = str(citation.get("web_search_provider") or "")
    if origin == "official_live_web" and provider not in {
        "",
        "ibm-official-portfolio",
    }:
        return "internet_search"
    if origin in {"live_ibm_docs", "official_live_docs", "official_live_web"}:
        return "live_ibm_docs"
    if origin in {"persistent_cache", "persistent_cache_revalidated"}:
        return "ibm_docs_cache"
    if origin == "global_metadata_catalog":
        return "metadata_catalog"
    return "opensearch_index"


def _retrieval_provenance(state: SupportState, citations: list[dict]) -> RetrievalProvenance:
    source_order = (
        "opensearch_index",
        "metadata_catalog",
        "ibm_docs_cache",
        "live_ibm_docs",
        "internet_search",
    )
    source_set = {_citation_source(citation) for citation in citations}
    answer_sources = [source for source in source_order if source in source_set]

    trace = state.get("trace") or {}
    retrieve_trace = trace.get("retrieve") or {}
    adaptive = retrieve_trace.get("adaptive")
    stages = adaptive.get("stages", []) if isinstance(adaptive, dict) else []
    stage_names = {
        str(stage.get("stage"))
        for stage in stages
        if isinstance(stage, dict)
    }
    metadata_searched = "global_metadata_catalog" in stage_names
    opensearch_searched = (
        "opensearch" in stage_names
        or (bool(retrieve_trace) and not isinstance(adaptive, dict))
    )
    internet_searched = bool(
        isinstance(adaptive, dict) and adaptive.get("web_search_performed")
    )
    live_retrieved = bool(
        stage_names.intersection({"live_ibm_docs", "official_live_docs"})
        or ("official_live_web" in stage_names and not internet_searched)
    )
    provider = (
        str(adaptive.get("web_search_provider") or "") or None
        if isinstance(adaptive, dict)
        else None
    )

    labels = {
        "opensearch_index": "pre-existing OpenSearch knowledge",
        "metadata_catalog": "the IBM Docs metadata catalog",
        "ibm_docs_cache": "cached official IBM documentation",
        "live_ibm_docs": "live official IBM page retrieval",
        "internet_search": (
            f"live internet search via {provider.title()}"
            if provider else "live internet search"
        ),
    }
    summary = (
        "Used " + " and ".join(labels[source] for source in answer_sources) + "."
        if answer_sources else
        "No source supplied sufficient cited evidence."
    )
    return RetrievalProvenance(
        answer_sources=answer_sources,
        opensearch_searched=opensearch_searched,
        metadata_catalog_searched=metadata_searched,
        live_ibm_docs_retrieved=live_retrieved,
        internet_search_performed=internet_searched,
        internet_search_provider=provider if internet_searched else None,
        summary=summary,
    )
