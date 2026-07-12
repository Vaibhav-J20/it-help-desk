"""
Node 3: resolve_scope
Decides whether the request is in scope and whether clarification is needed.
Must not silently change an explicit user-provided version.
"""
from app.graph.state import SupportState
from app.policy.domain_policy import is_in_scope, is_question_out_of_scope

_DEFAULT_DOMAIN = "ocp_sno_support"
_SUPPORTED_DOMAINS = {"ocp_sno_support", "watsonx_orchestrate", "ibm_bob"}


# Questions about which platforms/OSes are supported are version-independent —
# never ask for an OCP version before answering them.
_PLATFORM_SUPPORT_TERMS = (
    "windows",
    "macos",
    "mac os",
    "supported operating system",
    "supported platform",
    "supported os",
    "can openshift run on",
    "can ocp run on",
    "can ocp be installed on",
    "can openshift be installed on",
    "can openshift container platform be installed on",
)


def _needs_version_clarification(question: str, extracted_scope: dict) -> bool:
    if extracted_scope.get("ocp_version"):
        return False

    lowered = question.lower()

    # Platform/OS support questions are the same across all versions — never block on version.
    if any(term in lowered for term in _PLATFORM_SUPPORT_TERMS):
        return False

    version_sensitive_terms = (
        "nmstateconfig",
        "cluster-manifests",
        "minimum hardware requirement",
        "ingresscontroller",
    )
    return any(term in lowered for term in version_sensitive_terms)


def run(state: SupportState) -> SupportState:
    intent = state.get("intent", "qa")
    required_clarification = state.get("required_clarification")
    question = state.get("user_question", "")
    extracted_scope = dict(state.get("extracted_scope") or {})
    domain_id = extracted_scope.get("domain_id") or _infer_domain(question)

    # If the classifier already determined that the user must clarify scope,
    # ask that question before attempting strict domain routing.
    if required_clarification:
        return {
            **state,
            "status": "NEEDS_CLARIFICATION",
            "trace": {**state.get("trace", {}), "resolve_scope": "needs_clarification"},
        }

    # Out of scope
    if (
        not domain_id
        or domain_id not in _SUPPORTED_DOMAINS
        or not is_in_scope(domain_id)
        or (domain_id == _DEFAULT_DOMAIN and is_question_out_of_scope(question))
        or (intent == "unsupported" and not domain_id)
    ):
        return {
            **state,
            "intent": "unsupported",
            "status": "OUT_OF_SCOPE",
            "trace": {**state.get("trace", {}), "resolve_scope": "out_of_scope"},
        }

    extracted_scope["domain_id"] = domain_id
    if domain_id == _DEFAULT_DOMAIN and _needs_version_clarification(question, extracted_scope):
        return {
            **state,
            "required_clarification": "Which OpenShift version are you using?",
            "status": "NEEDS_CLARIFICATION",
            "trace": {**state.get("trace", {}), "resolve_scope": "needs_version_clarification"},
        }

    # Build retrieval query — expand known synonym mismatches between how users
    # phrase questions and how the documentation phrases the same information.
    retrieval_query = _expand_retrieval_query(state["user_question"])

    from app.retrieval.filters import build_filters
    retrieval_filters = build_filters(extracted_scope)

    return {
        **state,
        "retrieval_query": retrieval_query,
        "retrieval_filters": retrieval_filters,
        "extracted_scope": extracted_scope,
        "trace": {**state.get("trace", {}), "resolve_scope": "in_scope"},
    }


# Maps user-phrasing patterns to documentation-phrasing expansions.
# Each entry: (trigger_substring, expansion_suffix).
# The suffix is appended to the query so BM25 can also match the doc's vocabulary.
_QUERY_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("minimum hardware requirement",    "recommended cluster resources vCPU memory storage"),
    ("system requirement",              "recommended cluster resources vCPU memory storage"),
    ("hardware requirement",            "recommended cluster resources vCPU memory storage"),
    ("how much ram",                    "recommended cluster resources memory storage vCPU"),
    ("how much memory",                 "recommended cluster resources memory storage vCPU"),
    ("how much storage",                "recommended cluster resources storage vCPU memory"),
    ("how much cpu",                    "recommended cluster resources vCPU memory storage"),
    ("how much disk",                   "recommended cluster resources storage vCPU memory"),
    ("disk space",                      "recommended cluster resources storage vCPU memory"),
    ("cpu core",                        "recommended cluster resources vCPU memory storage"),
    ("supported platform",              "baremetal vsphere external none platform supported"),
    ("supported operating system",      "RHCOS Red Hat Enterprise Linux CoreOS operating system"),
    ("error code",                      "error message troubleshooting diagnostic"),
    ("log location",                    "log file path journalctl debug"),
)


def _expand_retrieval_query(question: str) -> str:
    """
    Append documentation vocabulary to the retrieval query when user phrasing
    is known to diverge from the corpus vocabulary.
    Only the first matching expansion is applied.
    """
    lowered = question.lower()
    for trigger, expansion in _QUERY_EXPANSIONS:
        if trigger in lowered:
            return f"{question} {expansion}"
    return question


def _infer_domain(question: str) -> str | None:
    lowered = question.lower()
    if any(term in lowered for term in ("watsonx orchestrate", "orchestrate adk", "adk", "orchestrate agent", "ai builder")):
        return "watsonx_orchestrate"
    if any(term in lowered for term in ("ibm bob", "bob ide", "bob shell", "bobalytics", "bobcoin")):
        return "ibm_bob"
    if any(term in lowered for term in ("openshift", "open shift", "ocp", "sno", "single node openshift", "rhcos", "nmstateconfig", "agent-based installer")):
        return "ocp_sno_support"
    return None
