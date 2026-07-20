"""
Pure function: build OpenSearch filter DSL from extracted scope.
No I/O — fully unit testable.
"""

# Fields that must never be relaxed on a zero-result retry, regardless of
# whether they were inferred or explicitly supplied.
#
#   domain_id      — removing it allows cross-domain chunk leakage (e.g. an
#                    OpenShift question retrieving watsonx Orchestrate chunks).
#   is_current     — removing it would surface superseded document revisions.
#   classification — removing it would expose internal/confidential chunks to
#                    callers who are only authorised for public content.
#   access_scope   — removing it would expose restricted content (e.g.
#                    seller_enablement) to callers without that scope.
_NEVER_RELAX = frozenset({
    "domain_id", "product", "product_version", "is_current", "classification",
    "access_scope"
})


def build_filters(extracted_scope: dict) -> list[dict]:
    """
    Convert a scope dict into a list of OpenSearch bool/filter term clauses.

    Args:
        extracted_scope: dict with optional keys:
            - ocp_version (str)        — strict: must match exactly
            - deployment_type (str)
            - domain_id (str)
            - component (str)
            - product (str)          — strict product isolation for generic IBM docs
            - product_version (str)  — strict when the user names a version
            - classification (str)     — e.g. "public" or "internal"
            - access_scope (str)       — a single access-scope value the caller holds
            - is_current (bool)        — always True unless explicitly overridden

    Returns:
        List of OpenSearch filter clause dicts suitable for a bool query's
        "filter" array. Returns a list containing only the is_current clause
        if no other scope is provided.

    Examples:
        >>> build_filters({"ocp_version": "4.16", "deployment_type": "SNO"})
        [
            {"term": {"ocp_version": "4.16"}},
            {"term": {"deployment_type": "SNO"}},
            {"term": {"is_current": True}},
        ]
    """
    filters: list[dict] = []

    if extracted_scope.get("ocp_version"):
        filters.append({"term": {"ocp_version": extracted_scope["ocp_version"]}})

    if extracted_scope.get("ocp_versions"):
        filters.append({"terms": {"ocp_version": extracted_scope["ocp_versions"]}})

    if extracted_scope.get("deployment_type"):
        filters.append({"term": {"deployment_type": extracted_scope["deployment_type"]}})

    if extracted_scope.get("domain_id"):
        filters.append({"term": {"domain_id": extracted_scope["domain_id"]}})

    if extracted_scope.get("component"):
        filters.append({"term": {"components": extracted_scope["component"]}})

    if extracted_scope.get("product"):
        filters.append({"term": {"product": extracted_scope["product"]}})

    if extracted_scope.get("product_version"):
        filters.append({"term": {"product_version": extracted_scope["product_version"]}})

    # classification — restrict chunks to the caller's maximum authorised level.
    # e.g. pass "public" for unauthenticated callers; "internal" for IBM employees.
    if extracted_scope.get("classification"):
        filters.append({"term": {"classification": extracted_scope["classification"]}})

    # access_scope — restrict to chunks the caller is authorised to see.
    # e.g. a caller without "seller_enablement" must not receive seller-deck chunks.
    if extracted_scope.get("access_scope"):
        filters.append({"term": {"access_scope": extracted_scope["access_scope"]}})

    # Always filter to current revisions only — never serve superseded content.
    is_current = extracted_scope.get("is_current", True)
    filters.append({"term": {"is_current": is_current}})

    return filters


def relax_inferred_filters(filters: list[dict], inferred_keys: list[str]) -> list[dict]:
    """
    Remove filters that were inferred (not explicitly stated by the user).
    Used when the initial retrieval returns no results — retry with looser filters
    while keeping explicit version/product filters strict.

    The fields in _NEVER_RELAX are ALWAYS preserved regardless of inferred_keys.
    Relaxing domain_id/product → cross-domain or cross-product chunk leakage.
    Relaxing is_current → superseded content returned.
    Relaxing classification / access_scope → security boundary violated.

    Args:
        filters: the original filter list from build_filters()
        inferred_keys: field names that were inferred and may be relaxed

    Returns:
        New filter list with inferred fields removed (excluding protected fields).
    """
    relaxed = []
    for f in filters:
        clause = f.get("term") or f.get("terms") or {}
        key = next(iter(clause.keys()), None)
        if key in _NEVER_RELAX or key not in inferred_keys:
            relaxed.append(f)
    return relaxed
