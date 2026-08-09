import json
from collections.abc import Callable

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel

from app.providers import ProviderCallError
from app.providers.models import AiErrorCategory, ModelCapabilities
from app.providers.openai_adapters import (
    OpenAiCompatibleChatAdapter,
    OpenAiResponsesAdapter,
)


class StructuredFixture(BaseModel):
    title: str


def openai_client(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAI:
    return OpenAI(
        api_key="sk-test-abcdefghijklmnopqrstuvwxyz",
        base_url="https://provider.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


def test_responses_adapter_returns_text_usage_without_persisting_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["store"] is False
        assert payload["input"] == "本章资料"
        return httpx.Response(200, json={
            "id": "resp_fixture",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "instructions": payload["instructions"],
            "max_output_tokens": None,
            "model": payload["model"],
            "output": [{
                "id": "msg_fixture",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "annotations": [],
                    "logprobs": [],
                    "text": "一段可用的章节候选",
                }],
            }],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 120,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens": 80,
                "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 200,
            },
        })

    adapter = OpenAiResponsesAdapter(
        "unused-test-key-value-abcdefghijklmnopqrstuvwxyz",
        "gpt-test",
        client=openai_client(handler),
    )
    result = adapter.generate_text(instructions="写作", input_text="本章资料")

    assert result.output == "一段可用的章节候选"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 80
    assert result.duration_ms >= 0


def test_compatible_adapter_supports_text_and_local_json_fallback() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        content = "普通文本" if calls == 1 else '{"title":"结构化结果"}'
        assert "response_format" not in payload
        return httpx.Response(200, json={
            "id": f"chatcmpl_fixture_{calls}",
            "object": "chat.completion",
            "created": 1,
            "model": "compatible-test",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }],
            "usage": {
                "prompt_tokens": 30,
                "completion_tokens": 10,
                "total_tokens": 40,
            },
        })

    adapter = OpenAiCompatibleChatAdapter(
        "unused-test-key-value-abcdefghijklmnopqrstuvwxyz",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(),
        client=openai_client(handler),
    )

    text_result = adapter.generate_text(instructions="写作", input_text="资料")
    structured_result = adapter.generate_structured(
        instructions="归纳",
        input_text="资料",
        output_model=StructuredFixture,
    )

    assert text_result.output == "普通文本"
    assert text_result.usage.input_tokens == 30
    assert structured_result.output == StructuredFixture(title="结构化结果")


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (401, AiErrorCategory.AUTHENTICATION, False),
        (403, AiErrorCategory.PERMISSION, False),
        (429, AiErrorCategory.RATE_LIMIT, True),
        (503, AiErrorCategory.UNAVAILABLE, True),
    ],
)
def test_provider_http_errors_are_normalized_without_leaking_body(
    status_code: int,
    category: AiErrorCategory,
    retryable: bool,
) -> None:
    secret_body = "provider-debug-secret-should-not-leak"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": secret_body, "type": "fixture"}},
        )

    adapter = OpenAiCompatibleChatAdapter(
        "unused-test-key-value-abcdefghijklmnopqrstuvwxyz",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(),
        client=openai_client(handler),
    )

    with pytest.raises(ProviderCallError) as caught:
        adapter.generate_text(instructions="写作", input_text="资料")

    assert caught.value.category == category
    assert caught.value.retryable is retryable
    assert secret_body not in caught.value.safe_message
