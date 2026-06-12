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
