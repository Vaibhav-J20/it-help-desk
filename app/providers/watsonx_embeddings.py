"""
watsonx.ai embedding provider.
Model ID comes from WATSONX_EMBEDDING_MODEL_ID env var — never hard-coded.
"""
from functools import lru_cache
from ibm_watsonx_ai import APIClient, Credentials
from ibm_watsonx_ai.foundation_models import Embeddings
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_embeddings_client() -> Embeddings:
    settings = get_settings()
    if not settings.watsonx_embedding_model_id:
        raise RuntimeError(
            "WATSONX_EMBEDDING_MODEL_ID is not set. "
            "Verify available models in your watsonx.ai account and set this env var."
        )
    if not settings.watsonx_project_id:
        raise RuntimeError("WATSONX_PROJECT_ID is not set.")

    credentials = Credentials(
        url=settings.watsonx_url,
        api_key=settings.ibm_cloud_api_key,
    )
    return Embeddings(
        model_id=settings.watsonx_embedding_model_id,
        credentials=credentials,
        project_id=settings.watsonx_project_id,
    )


def embed_text(text: str) -> list[float]:
    """
    Generate an embedding vector for a single text string.

    Args:
        text: The text to embed.

    Returns:
        List of floats representing the embedding vector.
    """
    client = _get_embeddings_client()
    result = client.embed_documents(texts=[text])
    return result[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embedding vectors for a list of texts (batch).
    Used by the ingestion pipeline.

    Args:
        texts: List of text strings to embed.

    Returns:
        List of embedding vectors, one per input text.
    """
    client = _get_embeddings_client()
    return client.embed_documents(texts=texts)


def ping_watsonx_embeddings() -> bool:
    """Return True if the embedding client can be initialised, False otherwise."""
    try:
        _get_embeddings_client()
        return True
    except Exception as e:
        logger.info(f"watsonx embeddings ping failed: {e}")
        return False
