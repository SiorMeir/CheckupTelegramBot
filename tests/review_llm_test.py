import pytest

from review.llm import (
    LLMConfig,
    LLMConfigError,
    LLMRequestTooLargeError,
    _build_chat_completion_payload,
    ensure_input_token_budget,
    load_llm_config_from_env,
)


def test_openai_provider_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "OPENAI")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMConfigError):
        load_llm_config_from_env()


def test_local_provider_requires_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "LOCAL")
    monkeypatch.setenv("LLM_MODEL", "local-model")
    monkeypatch.delenv("LOCAL_BASE_URL", raising=False)

    with pytest.raises(LLMConfigError):
        load_llm_config_from_env()


def test_local_provider_normalizes_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "LOCAL")
    monkeypatch.setenv("LLM_MODEL", "local-model")
    monkeypatch.setenv("LOCAL_BASE_URL", "http://localhost:1234")
    monkeypatch.setenv("LOCAL_API_KEY", "ignored")

    config = load_llm_config_from_env()

    assert config.base_url == "http://localhost:1234/v1"
    assert config.api_key is None


def test_input_budget_rejects_oversized_prompt():
    config = LLMConfig(
        provider="LOCAL",
        model="test",
        base_url="http://localhost:1234/v1",
        api_key=None,
        timeout_seconds=60,
        max_input_tokens=5,
    )

    with pytest.raises(LLMRequestTooLargeError):
        ensure_input_token_budget(config, "abcd" * 4, "efgh" * 4)


def test_openai_payload_omits_temperature():
    config = LLMConfig(
        provider="OPENAI",
        model="gpt-test",
        base_url="https://api.openai.com/v1",
        api_key="secret",
        timeout_seconds=60,
        max_input_tokens=8000,
    )

    payload = _build_chat_completion_payload(config, "system", "user")

    assert payload["model"] == "gpt-test"
    assert "temperature" not in payload


def test_local_payload_keeps_temperature():
    config = LLMConfig(
        provider="LOCAL",
        model="local-model",
        base_url="http://localhost:1234/v1",
        api_key=None,
        timeout_seconds=60,
        max_input_tokens=8000,
    )

    payload = _build_chat_completion_payload(config, "system", "user")

    assert payload["temperature"] == 0.3
