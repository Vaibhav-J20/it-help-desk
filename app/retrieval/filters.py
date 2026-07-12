"""
Pure function: build OpenSearch filter DSL from extracted scope.
No I/O — fully unit testable.
"""

# Fields that must never be relaxed on a zero-result retry, regardless of
# whether they were inferred or explicitly supplied.  Removing domain_id would
# allow a watsonx Orchestrate question to match OpenShift chunks (and
# vice-versa), producing wrong-product citations.  Removing is_current would
# surface superseded document revisions.
_NEVER_RELAX = frozenset({"domain_id", "is_current"})


def build_filters(extracted_scope: dict) -> list[dict]:
    """
    Convert a scope dict into a list of OpenSearch bool/filter term clauses.

    Args:
        extracted_scope: dict with optional keys:
            - ocp_version (str)   — strict: must match exactly
            - deployment_type (str)
            - domain_id (str)
            - component (str)
            - is_current (bool)   — always True unless explicitly overridden

    Returns:
        List of OpenSearch filter clause dicts suitable for a bool query's
        "filter" array. Returns an empty list if scope is empty.

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

    if extracted_scope.get("deployment_type"):
        filters.append({"term": {"deployment_type": extracted_scope["deployment_type"]}})

    if extracted_scope.get("domain_id"):
        filters.append({"term": {"domain_id": extracted_scope["domain_id"]}})

    if extracted_scope.get("component"):
        filters.append({"term": {"components": extracted_scope["component"]}})

    # Always filter to current revisions only — never serve superseded content
    is_current = extracted_scope.get("is_current", True)
    filters.append({"term": {"is_current": is_current}})

    return filters


def relax_inferred_filters(filters: list[dict], inferred_keys: list[str]) -> list[dict]:
    """
    Remove filters that were inferred (not explicitly stated by the user).
    Used when the initial retrieval returns no results — retry with looser filters
    while keeping explicit version/product filters strict.

    domain_id and is_current are NEVER relaxed regardless of inferred_keys.
    Relaxing domain_id would allow cross-domain chunk leakage (e.g. an
    OpenShift question retrieving watsonx Orchestrate chunks).

    Args:
        filters: the original filter list from build_filters()
        inferred_keys: field names that were inferred and may be relaxed

    Returns:
        New filter list with inferred fields removed (excluding protected fields).
    """
    relaxed = []
    for f in filters:
        key = next(iter(f.get("term", {}).keys()), None)
        if key in _NEVER_RELAX or key not in inferred_keys:
            relaxed.append(f)
    return relaxed
