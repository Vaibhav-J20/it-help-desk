"""
Application configuration — reads all settings from environment variables.
Never hard-code model IDs, URLs, or secrets here.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # IBM Cloud IAM
    ibm_cloud_api_key: str = ""

    # OpenSearch
    # Local Podman development uses loopback-only HTTP with the OpenSearch
    # security plugin disabled. Remote deployments must set HTTPS, credentials,
    # and a trusted CA explicitly in .env.
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str = ""
    opensearch_password: str = ""
    opensearch_verify_certs: bool = True
    # v2 indexes match ibm/granite-embedding-278m-multilingual (768-dim).
    # Never reuse a v1 index after an embedding-model change — dimensions or
    # similarity geometry may differ even when the output dimension is the same.
    opensearch_index_chunks: str = "knowledge_chunks_v2"
    opensearch_index_docs: str = "knowledge_documents_v2"
    # Must match the output dimension of WATSONX_EMBEDDING_MODEL_ID exactly.
    # ibm/granite-embedding-278m-multilingual  → 768
    # ibm/granite-embedding-107m-multilingual  → 384
    # Changing this value requires dropping and recreating the index.
    opensearch_embedding_dim: int = 768

    # watsonx.ai
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_project_id: str = ""
    # Set to a model confirmed available in your watsonx.ai account and region.
    # ibm/slate-125m-english-rtrvr-v2 is WITHDRAWN — do not use.
    # Confirmed available in us-south: ibm/granite-embedding-278m-multilingual (768-dim)
    watsonx_embedding_model_id: str = ""   # must be set — verified in target account
    watsonx_chat_model_id: str = ""        # must be set — verified in target account
    watsonx_rerank_model_id: str = ""      # only required when enable_reranker=true

    # IBM Cloud Object Storage
    cos_endpoint: str = ""
    cos_bucket: str = ""
    cos_api_key: str = ""

    # FastAPI auth
    api_key_secret: str = ""

    # Feature flags
    enable_reranker: bool = False

    # Retrieval tuning
    rrf_k: int = 60
    retrieval_top_bm25: int = 20
    retrieval_top_vector: int = 20
    retrieval_top_candidates: int = 12
    evidence_top_k: int = 6

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
