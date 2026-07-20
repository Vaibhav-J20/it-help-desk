from app.core.config import Settings
from app.main import _retrieval_readiness


def test_retrieval_readiness_accepts_fully_configured_fallbacks():
    readiness = _retrieval_readiness(Settings(
        _env_file=None,
        enable_adaptive_retrieval=True,
        enable_live_ibm_docs=True,
        enable_live_web_search=True,
        ibm_docs_user_agent="IT-Helpdesk contact@example.com",
        live_web_search_provider="tavily",
        live_web_search_endpoint="https://api.tavily.com/search",
        live_web_search_api_key="test-key",
        live_web_search_allowed_domains="www.ibm.com",
    ))

    assert readiness["live_ibm_docs_configured"] is True
    assert readiness["internet_search_configured"] is True


def test_retrieval_readiness_flags_enabled_but_incomplete_fallbacks():
    readiness = _retrieval_readiness(Settings(
        _env_file=None,
        enable_adaptive_retrieval=False,
        enable_live_ibm_docs=True,
        enable_live_web_search=True,
        ibm_docs_user_agent="",
        live_web_search_endpoint="",
        live_web_search_api_key="",
    ))

    assert readiness["live_ibm_docs_configured"] is False
    assert readiness["internet_search_configured"] is False
