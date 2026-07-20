"""
Node 3: resolve_scope
Decides whether the request is in scope and whether clarification is needed.
Must not silently change an explicit user-provided version.
"""
from dataclasses import dataclass
import re

from app.graph.state import SupportState
from app.observability.logging import get_logger
from app.policy.domain_policy import is_in_scope
from app.retrieval.portfolio import detect_portfolio_family

logger = get_logger(__name__)

_DEFAULT_DOMAIN = "ocp_sno_support"
_PRODUCT_VERSION_RE = r"\d+(?:\.(?:\d+|x)){1,3}"
_OCP_VERSION_PATTERN = re.compile(r"\b4\.\d+\b")


@dataclass(frozen=True)
class IBMProductMatch:
    product_name: str
    product_version: str | None
    needs_version: bool
    available_versions: tuple[str, ...]
    unavailable_version: str | None = None
    catalog_content_key: str | None = None


# Questions that are version-independent — never ask for OCP version before answering.
# Covers: platform/OS support questions, hardware/system requirements.
_NO_VERSION_CLARIFICATION_TERMS = (
    # Platform and OS support
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
    # Hardware / system requirements — corpus says "recommended cluster resources",
    # users say "minimum hardware requirements". Answer is the same across versions.
    "hardware requirement",
    "system requirement",
    "minimum requirement",
    "how much ram",
    "how much memory",
    "how much cpu",
    "how much disk",
    "how much storage",
    "disk space required",
    "storage required",
    "cpu required",
    "ram required",
)
# Keep old name as alias so existing references don't break.
_PLATFORM_SUPPORT_TERMS = _NO_VERSION_CLARIFICATION_TERMS


def _needs_version_clarification(question: str, extracted_scope: dict) -> bool:
    if extracted_scope.get("ocp_version"):
        return False

    lowered = question.lower()

    # Exact version-sensitive concepts take precedence over the broader
    # convenience exemptions below. Minimum SNO requirements can change across
    # OpenShift releases, so an unversioned request must be clarified.
    version_sensitive_terms = (
        "nmstateconfig",
        "cluster-manifests",
        "minimum hardware requirement",
        "ingresscontroller",
    )
    if any(term in lowered for term in version_sensitive_terms):
        return True

    # Version-independent questions — never block on version clarification.
    if any(term in lowered for term in _NO_VERSION_CLARIFICATION_TERMS):
        return False

    return False


def run(state: SupportState) -> SupportState:
    intent = state.get("intent", "qa")
    required_clarification = state.get("required_clarification")
    question = state.get("user_question", "")
    extracted_scope = dict(state.get("extracted_scope") or {})

    mentioned_ocp_versions = tuple(dict.fromkeys(
        _OCP_VERSION_PATTERN.findall(question.lower())
    ))
    if len(mentioned_ocp_versions) > 1 and _is_comparison_question(question):
        # A comparison is already explicit enough to proceed. A scalar version
        # inferred by the classifier would silently discard half the request.
        required_clarification = None
        extracted_scope.pop("ocp_version", None)
        extracted_scope["ocp_versions"] = list(mentioned_ocp_versions)

    # Portfolio questions intentionally span products. Orchestrate may attach
    # watsonx_orchestrate merely because the user said "watsonx"; treating that
    # hint as authoritative would restrict retrieval to one product and create
    # a misleading partial answer. Preserve only security-related scope and
    # route the request to the portfolio-aware official-source path.
    portfolio_family = detect_portfolio_family(question)
    if portfolio_family:
        prior_domain = extracted_scope.get("domain_id")
        extracted_scope = {
            key: value
            for key, value in extracted_scope.items()
            if key in {"classification", "access_scope", "is_current"}
        }
        extracted_scope.update({
            "domain_id": "ibm_products",
            "portfolio_family": portfolio_family,
        })
        from app.retrieval.filters import build_filters

        return {
            **state,
            "retrieval_query": question,
            "retrieval_filters": build_filters(extracted_scope),
            "extracted_scope": extracted_scope,
            "required_clarification": None,
            "trace": {
                **state.get("trace", {}),
                "resolve_scope": "portfolio_query",
                "portfolio_family": portfolio_family,
                **(
                    {"overrode_domain_hint": prior_domain}
                    if prior_domain and prior_domain != "ibm_products" else {}
                ),
            },
        }

    deterministic_clarification = _broad_request_clarification(question)
    if deterministic_clarification:
        return {
            **state,
            "extracted_scope": extracted_scope,
            "required_clarification": deterministic_clarification,
            "status": "NEEDS_CLARIFICATION",
            "trace": {
                **state.get("trace", {}),
                "resolve_scope": "needs_clarification",
            },
        }

    product_hint = str(extracted_scope.get("product") or "")
    requested_domain = str(extracted_scope.get("domain_id") or "")
    if requested_domain and requested_domain != "ibm_products":
        # Dedicated domains (OpenShift, Orchestrate, and Bob) are already an
        # exact retrieval boundary. Searching the global IBM Docs product
        # catalog here adds no routing information and can scan a very large
        # metadata graph before every otherwise-simple question.
        matched_ibm_product = None
    else:
        matched_ibm_product = _match_enabled_ibm_product(
            f"{question} {product_hint}".lower(),
            version_hint=str(extracted_scope.get("product_version") or ""),
        )
        if matched_ibm_product is None:
            matched_ibm_product = _match_global_ibm_product(
                f"{question} {product_hint}".lower(),
                version_hint=str(extracted_scope.get("product_version") or ""),
            )
    domain_id = extracted_scope.get("domain_id") or _infer_domain(question)
    if matched_ibm_product is not None and domain_id is None:
        domain_id = "ibm_products"

    # A product documentation-version listing is already a complete request.
    # Some generation models ask what details the user wants about the
    # versions, which blocks the metadata catalog before it can answer the
    # exact question. Deterministic intent wins over that unnecessary prompt.
    if matched_ibm_product is not None and _is_version_listing_question(question):
        required_clarification = None

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
        or not is_in_scope(domain_id)
        or (intent == "unsupported" and not domain_id)
    ):
        return {
            **state,
            "intent": "unsupported",
            "status": "OUT_OF_SCOPE",
            "trace": {**state.get("trace", {}), "resolve_scope": "out_of_scope"},
        }

    extracted_scope["domain_id"] = domain_id
    # Dedicated domains are already an exact retrieval boundary. Classifier
    # product labels are free text (for example "OpenShift Container Platform")
    # and can differ from canonical indexed values (for example "OpenShift").
    # Keeping those labels as term filters can turn a valid corpus hit into a
    # false zero-result query. Generic IBM products are canonicalized below and
    # therefore retain their strict product/version filters.
    if domain_id != "ibm_products":
        extracted_scope.pop("product", None)
        extracted_scope.pop("product_version", None)
    if domain_id == "ibm_products" and matched_ibm_product:
        # The registry value, not free-form LLM output, becomes the exact
        # OpenSearch filter and prevents cross-product evidence leakage.
        product_name = matched_ibm_product.product_name
        product_version = matched_ibm_product.product_version
        needs_version = matched_ibm_product.needs_version
        extracted_scope["product"] = product_name
        if matched_ibm_product.catalog_content_key:
            extracted_scope["catalog_content_key"] = (
                matched_ibm_product.catalog_content_key
            )
        if matched_ibm_product.unavailable_version:
            requested = matched_ibm_product.unavailable_version
            available = ", ".join(matched_ibm_product.available_versions)
            return {
                **state,
                "extracted_scope": extracted_scope,
                "required_clarification": (
                    f"I have verified {product_name} documentation for {available}, "
                    f"but not {requested}. Did you mean {available}, or can you "
                    "confirm the exact product and version?"
                ),
                "status": "NEEDS_CLARIFICATION",
                "trace": {
                    **state.get("trace", {}),
                    "resolve_scope": "known_product_unavailable_version",
                    "requested_product_version": requested,
                    "available_product_versions": list(
                        matched_ibm_product.available_versions
                    ),
                },
            }
        if product_version:
            extracted_scope["product_version"] = product_version
        if needs_version and _generic_question_needs_version(question):
            return {
                **state,
                "extracted_scope": extracted_scope,
                "required_clarification": f"Which {product_name} version are you using?",
                "status": "NEEDS_CLARIFICATION",
                "trace": {
                    **state.get("trace", {}),
                    "resolve_scope": "needs_product_version_clarification",
                },
            }
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
        "required_clarification": None,
        "trace": {**state.get("trace", {}), "resolve_scope": "in_scope"},
    }


# Maps user-phrasing patterns to documentation-phrasing expansions.
# Each entry: (trigger_substring, expansion_suffix).
# The suffix is appended to the query so BM25 can also match the doc's vocabulary.
_QUERY_EXPANSIONS: tuple[tuple[str, str], ...] = (
    ("networkpolicy",                    "list describe network policy namespace pod labels allowed ingress egress traffic"),
    ("network policy",                   "list describe network policy namespace pod labels allowed ingress egress traffic"),
    ("node rebooted",                    "cluster operators node status kubelet crio journalctl systemctl oc get co oc get nodes must-gather"),
    ("not coming back up",               "cluster operators node status kubelet crio journalctl systemctl oc get co oc get nodes must-gather"),
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


def _is_comparison_question(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in (
        " between ", " compared to ", " compare ", " difference ", " changed ",
    ))


def _broad_request_clarification(question: str) -> str | None:
    """Catch short, underspecified requests even when the classifier guesses a scope."""
    lowered = re.sub(r"\s+", " ", question.lower().strip()).rstrip("?.!")
    if re.fullmatch(
        r"(?:how (?:do|can) i )?(?:configure|set up|troubleshoot) "
        r"(?:the )?(?:networking|storage|authentication|security)",
        lowered,
    ):
        return (
            "Which IBM product and version are you using, and which specific "
            "area do you want to configure?"
        )
    if re.fullmatch(r"what is (?:the )?bootstrap process", lowered):
        return (
            "Which IBM product, version, and deployment type's bootstrap "
            "process do you mean?"
        )
    if (
        lowered.startswith("how do i configure ")
        and (lowered.endswith(" on openshift") or lowered.endswith(" on ocp"))
        and not _OCP_VERSION_PATTERN.search(lowered)
    ):
        return (
            "Which product and OpenShift versions are you using, and which "
            "specific component or setting do you need to configure?"
        )
    return None


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
    if _match_enabled_ibm_product(lowered):
        return "ibm_products"
    # Do not reject an IBM-named product merely because it is absent from the
    # local registry or metadata graph. The adaptive router can still perform
    # a final, allowlisted official-domain web search for it.
    if re.search(r"\bibm\b", lowered):
        return "ibm_products"
    # Known IBM product names that are not yet enabled still route to the
    # generic domain and are then rejected by the registry gate, rather than
    # leaking adjacent OpenShift evidence for a cross-product question.
    if any(term in lowered for term in (
        "ibm mq", "db2", "api connect", "app connect", "cloud pak", "websphere",
    )):
        return "ibm_products"
    if any(term in lowered for term in ("openshift", "open shift", "ocp", "sno", "single node openshift", "rhcos", "nmstateconfig", "agent-based installer")):
        return "ocp_sno_support"
    return None


def _match_enabled_ibm_product(
    lowered_question: str,
    *,
    version_hint: str = "",
) -> IBMProductMatch | None:
    """Route additional products only when their public corpus is enabled."""
    try:
        from app.ingestion.ibm_docs_crawler.registry import load_registry

        registry = load_registry()
    except Exception as exc:
        logger.warning(f"IBM Docs registry unavailable during product routing: {exc}")
        return None
    for product in registry.products:
        enabled_versions = [version for version in product.versions if version.crawl_enabled]
        if not enabled_versions:
            continue
        names = [product.product_name, product.product_id.replace("-", " "), *product.aliases]
        if any(name.lower() in lowered_question for name in names if name):
            available_versions = tuple(
                version.product_version for version in enabled_versions
            )
            explicit_version = (
                version_hint.strip()
                or _version_near_product_name(lowered_question, names)
            )
            if explicit_version:
                selected = next((
                    version for version in enabled_versions
                    if _versions_match(explicit_version, version.version_id)
                    or _versions_match(explicit_version, version.product_version)
                ), None)
                if selected is None:
                    return IBMProductMatch(
                        product_name=product.product_name,
                        product_version=None,
                        needs_version=False,
                        available_versions=available_versions,
                        unavailable_version=explicit_version,
                    )
                return IBMProductMatch(
                    product_name=product.product_name,
                    product_version=selected.product_version,
                    needs_version=False,
                    available_versions=available_versions,
                )

            mentioned = [
                version for version in enabled_versions
                if _version_is_mentioned(version.version_id, lowered_question)
                or _version_is_mentioned(version.product_version, lowered_question)
            ]
            if len(mentioned) == 1:
                return IBMProductMatch(
                    product_name=product.product_name,
                    product_version=mentioned[0].product_version,
                    needs_version=False,
                    available_versions=available_versions,
                )
            if len(enabled_versions) == 1:
                return IBMProductMatch(
                    product_name=product.product_name,
                    product_version=enabled_versions[0].product_version,
                    needs_version=False,
                    available_versions=available_versions,
                )
            return IBMProductMatch(
                product_name=product.product_name,
                product_version=None,
                needs_version=True,
                available_versions=available_versions,
            )
    return None


def _match_global_ibm_product(
    lowered_question: str,
    *,
    version_hint: str = "",
) -> IBMProductMatch | None:
    """Resolve any public IBM Docs product from the global metadata catalog."""
    try:
        from pathlib import Path
        import os

        from app.core.config import get_settings
        from app.ingestion.ibm_docs_crawler.catalog import (
            MetadataCatalog,
            is_confident_target_match,
        )

        data_dir = Path(os.path.expandvars(
            get_settings().ibm_docs_data_dir
        )).expanduser()
        catalog = MetadataCatalog(data_dir)
    except Exception as exc:
        logger.warning(f"Global IBM Docs catalog unavailable during routing: {exc}")
        return None

    explicit_version = version_hint.strip() or _version_anywhere(lowered_question)
    matches = catalog.resolve_targets(
        lowered_question,
        product_version=explicit_version or None,
        limit=10,
    )
    if not matches and explicit_version:
        unversioned = catalog.resolve_targets(lowered_question, limit=10)
        if not unversioned:
            return None
        top = next((
            target for target in unversioned
            if is_confident_target_match(target, lowered_question)
        ), None)
        if top is None:
            return None
        versions = tuple(
            dict.fromkeys(
                item.product_version
                for item in catalog.versions_for_product(top.product_id)
            )
        )
        return IBMProductMatch(
            product_name=top.product_name,
            product_version=None,
            needs_version=False,
            available_versions=versions,
            unavailable_version=explicit_version,
            catalog_content_key=top.content_key,
        )
    if not matches:
        return None

    top = next((
        target for target in matches
        if is_confident_target_match(target, lowered_question)
    ), None)
    if top is None:
        return None
    same_product = catalog.versions_for_product(top.product_id)
    versions = tuple(dict.fromkeys(
        item.product_version for item in same_product if item.product_version
    ))
    version_listing = _is_version_listing_question(lowered_question)
    return IBMProductMatch(
        product_name=top.product_name,
        product_version=(
            explicit_version or (None if version_listing else top.product_version)
        ),
        needs_version=(len(versions) > 1 and not explicit_version and not version_listing),
        available_versions=versions,
        catalog_content_key=top.content_key,
    )


def _version_near_product_name(
    lowered_question: str,
    names: list[str],
) -> str:
    """Extract a version only when it follows the product name or alias.

    This avoids treating values such as a Windows or database version as the
    IBM product version merely because they occur elsewhere in the question.
    """
    for name in sorted((value for value in names if value), key=len, reverse=True):
        pattern = re.compile(
            rf"(?<!\w){re.escape(name.lower())}(?!\w)\s+"
            rf"(?:version\s+|v)?(?P<version>{_PRODUCT_VERSION_RE})(?![\w.])"
        )
        match = pattern.search(lowered_question)
        if match:
            return match.group("version")
    return ""


def _versions_match(requested: str, configured: str) -> bool:
    requested_normalized = requested.lower().strip()
    configured_normalized = configured.lower().strip()
    if requested_normalized == configured_normalized:
        return True
    if configured_normalized.endswith(".x"):
        family = configured_normalized[:-2]
        return (
            requested_normalized == family
            or requested_normalized.startswith(f"{family}.")
        )
    return False


def _version_is_mentioned(version: str, lowered_question: str) -> bool:
    lowered = version.lower().strip()
    if lowered in {"current", "latest", "saas"}:
        return lowered in lowered_question.split()
    return lowered in lowered_question


def _generic_question_needs_version(question: str) -> bool:
    lowered = question.lower()
    if _is_version_listing_question(lowered):
        return False
    return any(term in lowered for term in (
        "install", "configure", "configuration", "command", "powershell", "shell",
        "cli", "api", "error", "fail", "troubleshoot", "upgrade", "migrate",
    ))


def _is_version_listing_question(question: str) -> bool:
    lowered = question.lower()
    return any(phrase in lowered for phrase in (
        "versions available", "available versions", "what versions",
        "which versions", "list versions", "documentation versions",
    ))


def _version_anywhere(question: str) -> str:
    match = re.search(rf"(?<![\w.])(?P<version>{_PRODUCT_VERSION_RE})(?![\w.])", question)
    return match.group("version") if match else ""
