"""
Node 1: input_guard
Validates the incoming request, normalises the question, generates request ID.
Must not retrieve documents or generate answers.
"""
import uuid
from app.graph.state import SupportState


def run(state: SupportState) -> SupportState:
    question = (state.get("user_question") or "").strip()

    if not question or len(question) < 3:
        return {
            **state,
            "status": "INVALID_REQUEST",
            "trace": {**state.get("trace", {}), "input_guard": "empty_or_too_short"},
        }

    if len(question) > 2000:
        return {
            **state,
            "status": "INVALID_REQUEST",
            "trace": {**state.get("trace", {}), "input_guard": "question_too_long"},
        }

    # Normalise whitespace
    question = " ".join(question.split())

    # Clean conversation context — remove entries with empty content
    context = [
        m for m in (state.get("conversation_context") or [])
        if m.get("content", "").strip()
    ]

    request_id = state.get("request_id") or str(uuid.uuid4())

    return {
        **state,
        "request_id": request_id,
        "user_question": question,
        "conversation_context": context,
        "trace": {**state.get("trace", {}), "input_guard": "passed"},
    }
