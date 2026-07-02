"""
watsonx.ai chat/generation provider.
Model ID comes from WATSONX_CHAT_MODEL_ID env var — never hard-coded.
"""
from functools import lru_cache
from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames as GenParams
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)

_GENERATE_PARAMS = {
    GenParams.MAX_NEW_TOKENS: 1024,
    GenParams.MIN_NEW_TOKENS: 10,
    GenParams.TEMPERATURE: 0.0,    # deterministic for grounded answers
    GenParams.STOP_SEQUENCES: [],
}


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
        params=_GENERATE_PARAMS,
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
    response = model.generate_text(prompt=prompt)
    return response
