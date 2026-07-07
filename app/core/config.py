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
    opensearch_url: str = "https://localhost:9200"
    opensearch_username: str = "admin"
    opensearch_password: str = "admin"
    opensearch_index_chunks: str = "knowledge_chunks_v1"
    opensearch_index_docs: str = "knowledge_documents_v1"

    # watsonx.ai
    watsonx_url: str = "https://us-south.ml.cloud.ibm.com"
    watsonx_project_id: str = ""
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
