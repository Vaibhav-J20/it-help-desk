from pathlib import Path

from scripts.configure_live_web_search import _configuration_errors, _settings, _write_env


def test_configure_web_search_upserts_without_destroying_existing_values(
    tmp_path: Path, monkeypatch,
):
    monkeypatch.delenv("ENABLE_LIVE_WEB_SEARCH", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("IBM_CLOUD_API_KEY=keep-me\nENABLE_LIVE_WEB_SEARCH=false\n")

    _write_env(env_file, {
        "ENABLE_LIVE_WEB_SEARCH": "true",
        "LIVE_WEB_SEARCH_PROVIDER": "openai",
        "LIVE_WEB_SEARCH_ENDPOINT": "https://api.openai.com/v1/responses",
        "LIVE_WEB_SEARCH_API_KEY": "sk-test-key-that-is-long-enough",
        "LIVE_WEB_SEARCH_ALLOWED_DOMAINS": "www.ibm.com,support.ibm.com",
    })

    content = env_file.read_text()
    assert "IBM_CLOUD_API_KEY=keep-me" in content
    assert "ENABLE_LIVE_WEB_SEARCH=true" in content
    assert "ENABLE_LIVE_WEB_SEARCH=false" not in content
    assert _configuration_errors(_settings(env_file)) == []


def test_configure_web_search_check_reports_missing_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("LIVE_WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ENABLE_LIVE_WEB_SEARCH=true\n"
        "LIVE_WEB_SEARCH_PROVIDER=openai\n"
        "LIVE_WEB_SEARCH_ALLOWED_DOMAINS=www.ibm.com\n"
    )

    errors = _configuration_errors(_settings(env_file))
    assert any("API_KEY" in error for error in errors)
