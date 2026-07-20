"""
Node 2: classify_and_extract
Determines intent and extracts version/deployment_type/component hints.
Uses the watsonx.ai chat model with the classify_extract prompt.
"""
import json
from pathlib import Path
import re
from app.graph.state import SupportState
from app.observability.logging import get_logger

logger = get_logger(__name__)
_PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "classify_extract.md"


def run(state: SupportState, generate_fn=None) -> SupportState:
    """
    Args:
        state:       Current graph state.
        generate_fn: Injected callable(prompt: str) -> str.
                     Defaults to app.providers.watsonx_chat.generate.
    """
    question = state["user_question"]
    api_scope = state.get("extracted_scope") or {}
    if _explicit_scope_is_complete(api_scope):
        # requested_scope is an authenticated API contract and already wins
        # over model inference below. Avoid a slow, redundant LLM call when it
        # identifies a complete routing boundary; deterministic resolve_scope
        # still performs registry canonicalization and clarification checks.
        parsed = {
            **_safe_defaults(),
            "intent": _deterministic_intent(question),
            "domain_id": api_scope.get("domain_id"),
        }
        classification_source = "explicit_scope"
    else:
        if generate_fn is None:
            from app.providers.watsonx_chat import generate as generate_fn
        template = _PROMPT_FILE.read_text()
        prompt = template.replace("{question}", question)

        try:
            raw = generate_fn(prompt)
            parsed = _parse_classification(raw)
            classification_source = "watsonx_model"
        except Exception as e:
            logger.info(f"classify_extract failed: {e} — using safe defaults")
            parsed = _safe_defaults()
            classification_source = "safe_defaults"

    extracted_scope = {
        k: v for k, v in {
            "ocp_version": parsed.get("ocp_version"),
            "deployment_type": parsed.get("deployment_type"),
            "domain_id": parsed.get("domain_id"),
            "component": parsed.get("component"),
            "product": parsed.get("product"),
            "product_version": parsed.get("product_version"),
        }.items() if v is not None
    }

    # Merge with any explicitly requested scope from the API request
    merged_scope = {**extracted_scope, **api_scope}  # API explicit values win

    required_clarification = (
        parsed.get("clarification_question")
        if parsed.get("needs_clarification")
        else None
    )
    if required_clarification and _clarification_satisfied_by_scope(
        required_clarification,
        merged_scope,
        question,
    ):
        required_clarification = None

    return {
        **state,
        "intent": parsed.get("intent", "qa"),
        "extracted_scope": merged_scope,
        "required_clarification": required_clarification,
        "trace": {
            **state.get("trace", {}),
            "classify_extract": {
                "intent": parsed.get("intent"),
                "domain_id": merged_scope.get("domain_id"),
                "needs_clarification": required_clarification is not None,
                "source": classification_source,
            },
        },
    }


def _explicit_scope_is_complete(scope: dict) -> bool:
    """Return True when requested_scope already supplies a safe route."""
    domain_id = str(scope.get("domain_id") or "")
    if domain_id in {"watsonx_orchestrate", "ibm_bob"}:
        return True
    if domain_id == "ocp_sno_support":
        return bool(scope.get("ocp_version"))
    if domain_id == "ibm_products":
        return bool(scope.get("product") or scope.get("portfolio_family"))
    return False


def _deterministic_intent(question: str) -> str:
    """Classify the small intent vocabulary for an already-scoped request."""
    lowered = " ".join(question.casefold().split())
    if re.search(
        r"\b(?:error|failed|failure|failing|issue|problem|troubleshoot|"
        r"diagnos(?:e|is|ing)|not\s+working|cannot|can't)\b",
        lowered,
    ):
        return "troubleshoot"
    if re.search(r"\b(?:summari[sz]e|summary|brief|overview|recap)\b", lowered):
        return "summarize"
    return "qa"


def _parse_classification(raw: str) -> dict:
    # Strip markdown code fences if present
    text = raw.strip().strip("```json").strip("```").strip()
    return json.loads(text)


def _safe_defaults() -> dict:
    return {
        "intent": "qa",
        "domain_id": None,
        "ocp_version": None,
        "deployment_type": None,
        "component": None,
        "product": None,
        "product_version": None,
        "needs_clarification": False,
        "clarification_question": None,
    }


def _clarification_satisfied_by_scope(
    clarification_question: str,
    scope: dict,
    user_question: str,
) -> bool:
    """
    Treat explicit API requested_scope as authoritative when it supplies the
    missing scope the model asked for.

    Deployment type is only mandatory for deployment-specific questions. General
    troubleshooting can proceed with an explicit OCP version alone.
    """
    clarification = clarification_question.lower()
    question = user_question.lower()

    asks_version = "version" in clarification or "ocp" in clarification
    if asks_version and not scope.get("ocp_version"):
        return False

    asks_deployment = any(
        phrase in clarification
        for phrase in ("deployment", "sno", "single node", "standard", "compact")
    )
    deployment_specific_question = any(
        phrase in question
        for phrase in ("sno", "single node", "compact", "standard", "bootstrap")
    )
    if asks_deployment and deployment_specific_question and not scope.get("deployment_type"):
        return False

    return bool(
        scope.get("domain_id")
        or scope.get("ocp_version")
        or scope.get("deployment_type")
        or scope.get("component")
    )
