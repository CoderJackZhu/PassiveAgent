import json

import pytest

from passive_agent.integrations.llm_client import LLMClient


def test_llm_client_bounds_openai_sdk_timeout_and_retries():
    client = LLMClient(
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        request_timeout_seconds=12.5,
        max_retries=1,
    )

    assert client.request_timeout_seconds == 12.5
    assert client.client.timeout == 12.5
    assert client.client.max_retries == 0


def test_llm_client_clamps_request_timeout():
    client = LLMClient(api_key="test-key", request_timeout_seconds=0.01)

    assert client.request_timeout_seconds == 1.0
    assert client.client.timeout == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        '<think>reasoning about the response</think>\n\n{"summary": "ok"}',
        '<think>reasoning about the response</think>\n\n```json\n{"summary": "ok"}\n```',
    ],
)
async def test_generate_json_accepts_minimax_think_prefix(response, monkeypatch):
    client = LLMClient(api_key="test-key")

    async def fake_generate(system: str, user: str, expect_json: bool = False) -> str:
        return response

    monkeypatch.setattr(client, "generate", fake_generate)

    assert await client.generate_json("system", "user") == {"summary": "ok"}


@pytest.mark.asyncio
async def test_generate_json_regenerates_once_after_malformed_json(monkeypatch):
    client = LLMClient(api_key="test-key")
    responses = iter([
        '{"summary": "broken" "topics": []}',
        '{"summary": "ok", "topics": []}',
    ])
    calls = 0

    async def fake_generate(system: str, user: str, expect_json: bool = False) -> str:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(client, "generate", fake_generate)

    assert await client.generate_json("system", "user") == {
        "summary": "ok",
        "topics": [],
    }
    assert calls == 2


@pytest.mark.asyncio
async def test_generate_json_rejects_arbitrary_text_before_json(monkeypatch):
    client = LLMClient(api_key="test-key")

    async def fake_generate(system: str, user: str, expect_json: bool = False) -> str:
        return 'Here is the result: {"summary": "ok"}'

    monkeypatch.setattr(client, "generate", fake_generate)

    with pytest.raises(json.JSONDecodeError):
        await client.generate_json("system", "user")


@pytest.mark.asyncio
async def test_generate_json_preserves_think_tags_inside_json_strings(monkeypatch):
    client = LLMClient(api_key="test-key")
    response = '{"summary": "keep <think>literal</think> text"}'

    async def fake_generate(system: str, user: str, expect_json: bool = False) -> str:
        return response

    monkeypatch.setattr(client, "generate", fake_generate)

    assert await client.generate_json("system", "user") == {
        "summary": "keep <think>literal</think> text"
    }
