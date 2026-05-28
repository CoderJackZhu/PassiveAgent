from types import SimpleNamespace

import pytest

from passive_agent.main import _build_llm


def _config(provider="openai_compatible", api_key_env="XIAOMI_API_KEY"):
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider=provider,
            api_key_env=api_key_env,
            base_url="https://token-plan-cn.xiaomimimo.com/v1",
            model="mimo-v2.5-pro",
            temperature=0.2,
            max_concurrency=3,
            max_retries=2,
            retry_backoff_base_seconds=0.5,
        )
    )


def test_build_llm_accepts_openai_compatible_provider(monkeypatch):
    monkeypatch.setenv("XIAOMI_API_KEY", "test-key")

    llm = _build_llm(_config())

    assert llm is not None
    assert llm.api_key_env == "XIAOMI_API_KEY"
    assert llm.base_url == "https://token-plan-cn.xiaomimimo.com/v1"
    assert llm.model == "mimo-v2.5-pro"
    assert llm.temperature == 0.2
    assert llm.max_concurrency == 3
    assert llm.max_retries == 2
    assert llm.retry_backoff_base_seconds == 0.5


def test_build_llm_keeps_deepseek_as_compatible_alias(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    llm = _build_llm(
        _config(
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
        )
    )

    assert llm is not None
    assert llm.api_key_env == "DEEPSEEK_API_KEY"


def test_build_llm_rejects_unknown_provider_when_required(monkeypatch):
    monkeypatch.setenv("UNKNOWN_API_KEY", "test-key")

    with pytest.raises(Exception, match="not supported"):
        _build_llm(_config(provider="unknown", api_key_env="UNKNOWN_API_KEY"), required=True)
