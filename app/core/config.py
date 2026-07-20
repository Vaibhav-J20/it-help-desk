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
    # Do not use legacy Slate embedding IDs unless their current lifecycle and
    # regional availability have been verified in the target account.
    # Confirmed available in us-south: ibm/granite-embedding-278m-multilingual (768-dim)
    watsonx_embedding_model_id: str = ""   # must be set — verified in target account
    watsonx_chat_model_id: str = ""        # must be set — verified in target account
    watsonx_chat_max_tokens: int = 2048
    watsonx_chat_temperature: float = 0.0
    watsonx_rerank_model_id: str = ""      # only required when enable_reranker=true

    # IBM Cloud Object Storage
    cos_endpoint: str = ""
    cos_bucket: str = ""
    cos_api_key: str = ""

    # FastAPI auth
    api_key_secret: str = ""
    # watsonx Orchestrate requires exactly one server in imported OpenAPI.
    public_api_base_url: str = ""

    # Feature flags
    enable_reranker: bool = False
    enable_adaptive_retrieval: bool = False
    enable_live_ibm_docs: bool = False
    enable_live_official_sources: bool = False
    enable_live_docs_indexing: bool = False
    enable_live_web_search: bool = False

    # Metadata-first IBM Docs retrieval. The page-body cap is intentionally
    # hard-bounded at five by the live retriever even if env values are wrong.
    # These are part of Settings because FastAPI does not call python-dotenv;
    # reading them directly with os.getenv would ignore values stored in .env.
    ibm_docs_user_agent: str = ""
    ibm_docs_data_dir: str = "~/.local/share/it-helpdesk/ibm-docs-crawler"
    ibm_docs_delay_seconds: float = 1.5
    ibm_docs_timeout_seconds: float = 30.0
    ibm_docs_max_retries: int = 4
    ibm_docs_max_response_bytes: int = 20_000_000
    ibm_docs_max_chunks_per_document: int = 250
    ibm_docs_validate_public_dns: bool = True
    live_docs_initial_pages: int = 3
    live_docs_max_pages: int = 5
    live_docs_related_depth: int = 1
    live_docs_concurrency: int = 3
    live_docs_cache_ttl_seconds: int = 86400
    live_docs_catalog_candidates: int = 30
    live_docs_evidence_chunks: int = 10
    # Required when ENABLE_LIVE_DOCS_INDEXING=true. Keeping these separate from
    # the serving-index settings prevents an accidental write to a live corpus.
    live_docs_chunks_index: str = ""
    live_docs_docs_index: str = ""

    # Optional search provider. The app does not scrape search-result HTML and
    # sends no search traffic unless ENABLE_LIVE_WEB_SEARCH is true.
    live_web_search_provider: str = "http_json"
    live_web_search_endpoint: str = ""
    live_web_search_api_key: str = ""
    live_web_search_model: str = "gpt-5.5"
    live_web_search_allowed_domains: str = (
        "www.ibm.com,newsroom.ibm.com,support.ibm.com,cloud.ibm.com,redbooks.ibm.com,"
        "docs.redhat.com,access.redhat.com,developers.redhat.com"
    )
    live_web_search_timeout_seconds: float = 30.0
    live_web_search_max_results: int = 5
    live_web_search_content_chars: int = 4000
    live_web_search_answer_candidates: int = 3
    live_web_search_depth: str = "advanced"
    live_web_search_query_variants: int = 2

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
