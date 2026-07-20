"""
watsonx.ai chat/generation provider.
Model ID comes from WATSONX_CHAT_MODEL_ID env var — never hard-coded.
Uses the chat completions API (/ml/v1/text/chat).
"""
from functools import lru_cache
from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)

@lru_cache(maxsize=1)
def _get_model() -> ModelInference:
    settings = get_settings()
    if not settings.watsonx_chat_model_id:
        raise RuntimeError(
            "WATSONX_CHAT_MODEL_ID is not set. "
            "Verify available models in your watsonx.ai account and set this env var."
        )
    credentials = Credentials(
        url=settings.watsonx_url,
        api_key=settings.ibm_cloud_api_key,
    )
    return ModelInference(
        model_id=settings.watsonx_chat_model_id,
        credentials=credentials,
        project_id=settings.watsonx_project_id,
    )


def generate(prompt: str) -> str:
    """
    Send a fully-formed prompt to the watsonx.ai chat model and return the text response.

    Args:
        prompt: Complete prompt string, including system instructions and evidence blocks.

    Returns:
        Generated text string.
    """
    model = _get_model()
    settings = get_settings()
    chat_params = {
        "max_tokens": max(256, settings.watsonx_chat_max_tokens),
        "temperature": min(2.0, max(0.0, settings.watsonx_chat_temperature)),
    }
    messages = [{"role": "user", "content": prompt}]
    response = model.chat(messages=messages, params=chat_params)
    return response["choices"][0]["message"]["content"]
