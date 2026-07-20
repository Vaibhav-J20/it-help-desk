"""
FastAPI application factory.
Health and readiness endpoints are available without authentication.
"""
from fastapi import FastAPI
from app.api.routes import router
from app.api.schemas import HealthResponse, ReadyResponse
from app.core.config import get_settings
from app.observability.logging import get_logger

logger = get_logger(__name__)


def _retrieval_readiness(settings) -> dict[str, bool]:
    """Validate fallback configuration without spending search API credits."""
    adaptive = bool(settings.enable_adaptive_retrieval)
    live_enabled = bool(
        settings.enable_live_ibm_docs or settings.enable_live_official_sources
    )
    live_configured = bool(
        not live_enabled
        or (adaptive and settings.ibm_docs_user_agent.strip())
    )
    web_enabled = bool(settings.enable_live_web_search)
    provider = settings.live_web_search_provider.strip().lower()
    domains = [
        value.strip()
        for value in settings.live_web_search_allowed_domains.split(",")
        if value.strip()
    ]
    web_configured = bool(
        not web_enabled
        or (
            adaptive
            and provider in {"tavily", "openai", "http_json"}
            and settings.live_web_search_endpoint.strip()
            and settings.live_web_search_api_key.strip()
            and domains
        )
    )
    return {
        "adaptive_retrieval": adaptive,
        "live_ibm_docs_enabled": live_enabled,
        "live_ibm_docs_configured": live_configured,
        "internet_search_enabled": web_enabled,
        "internet_search_configured": web_configured,
    }


def create_app() -> FastAPI:
    settings = get_settings()
    public_base_url = settings.public_api_base_url.strip().rstrip("/")

    app = FastAPI(
        title="Enterprise IT Support Copilot",
        description=(
            "Citation-grounded technical support for OpenShift/SNO, watsonx "
            "Orchestrate, IBM Bob, and registered IBM products such as Guardium, "
            "Instana, Verify, Cloud Pak for Data, and Cloud Pak for Integration. "
            "Answers use approved indexed content and bounded live retrieval from "
            "registered official IBM documentation sources."
        ),
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
        servers=([{"url": public_base_url}] if public_base_url else None),
    )

    app.include_router(router)

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness probe — no dependency checks."""
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        """Verify core dependencies and enabled retrieval fallbacks."""
        from app.retrieval.opensearch_client import ping_opensearch
        from app.providers.watsonx_embeddings import ping_watsonx_embeddings

        os_ok = ping_opensearch()
        wx_ok = ping_watsonx_embeddings()
        retrieval = _retrieval_readiness(settings)

        overall = "ready" if (
            os_ok
            and wx_ok
            and retrieval["live_ibm_docs_configured"]
            and retrieval["internet_search_configured"]
        ) else "degraded"
        return ReadyResponse(
            status=overall,
            opensearch=os_ok,
            watsonx=wx_ok,
            **retrieval,
        )

    logger.info(f"App created — LOG_LEVEL={settings.log_level}")
    return app


app = create_app()
