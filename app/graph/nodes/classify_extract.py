"""
Node 2: classify_and_extract
Determines intent and extracts version/deployment_type/component hints.
Uses the watsonx.ai chat model with the classify_extract prompt.
"""
import json
from pathlib import Path
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
    if generate_fn is None:
        from app.providers.watsonx_chat import generate as generate_fn

    question = state["user_question"]
    template = _PROMPT_FILE.read_text()
    prompt = template.replace("{question}", question)

    try:
        raw = generate_fn(prompt)
        parsed = _parse_classification(raw)
    except Exception as e:
        logger.info(f"classify_extract failed: {e} — using safe defaults")
        parsed = _safe_defaults()

    extracted_scope = {
        k: v for k, v in {
            "ocp_version": parsed.get("ocp_version"),
            "deployment_type": parsed.get("deployment_type"),
            "component": parsed.get("component"),
        }.items() if v is not None
    }

    # Merge with any explicitly requested scope from the API request
    api_scope = state.get("extracted_scope") or {}
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
                "needs_clarification": required_clarification is not None,
            },
        },
    }


def _parse_classification(raw: str) -> dict:
    # Strip markdown code fences if present
    text = raw.strip().strip("```json").strip("```").strip()
    return json.loads(text)


def _safe_defaults() -> dict:
    return {
        "intent": "qa",
        "ocp_version": None,
        "deployment_type": None,
        "component": None,
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

    return bool(scope.get("ocp_version") or scope.get("deployment_type") or scope.get("component"))
