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


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="OpenShift & SNO Technical Support Copilot",
        description=(
            "Citation-grounded technical support for OCP and SNO. "
            "Answers are sourced exclusively from approved PDF documentation."
        ),
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.include_router(router)

    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    async def healthz() -> HealthResponse:
        """Liveness probe — no dependency checks."""
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=ReadyResponse, tags=["health"])
    async def readyz() -> ReadyResponse:
        """Readiness probe — verifies OpenSearch and watsonx.ai are reachable."""
        from app.retrieval.opensearch_client import ping_opensearch
        from app.providers.watsonx_embeddings import ping_watsonx_embeddings

        os_ok = ping_opensearch()
        wx_ok = ping_watsonx_embeddings()

        overall = "ready" if (os_ok and wx_ok) else "degraded"
        return ReadyResponse(status=overall, opensearch=os_ok, watsonx=wx_ok)

    logger.info(f"App created — LOG_LEVEL={settings.log_level}")
    return app


app = create_app()
