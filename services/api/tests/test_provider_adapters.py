import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel

from app.providers import ProviderCallError, ProviderUsage
from app.providers.models import AiErrorCategory, ModelCapabilities
from app.providers.openai_adapters import (
    OpenAiCompatibleChatAdapter,
    OpenAiResponsesAdapter,
)


class StructuredFixture(BaseModel):
    title: str


REPLAY_FIXTURES = Path(__file__).parent / "fixtures" / "provider_replays"


def replay_fixture(name: str) -> dict[str, object]:
    payload = json.loads((REPLAY_FIXTURES / name).read_text(encoding="utf-8"))
    assert payload["sanitized"] is True
    return payload


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
        fixture = replay_fixture("openai_responses_text.json")
        return httpx.Response(200, json=fixture["response"])

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


class FakeResponseStream:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def __iter__(self):
        yield SimpleNamespace(type="response.output_text.delta", delta="第一段")
        yield SimpleNamespace(type="response.output_text.delta", delta="第二段")

    def get_final_response(self):
        return SimpleNamespace(
            output_text="第一段第二段",
            usage=SimpleNamespace(input_tokens=12, output_tokens=8),
        )


class FakeResponsesResource:
    def __init__(self, stream: FakeResponseStream) -> None:
        self.fixture_stream = stream

    def stream(self, **request: object) -> FakeResponseStream:
        assert request["store"] is False
        return self.fixture_stream


def test_responses_stream_emits_deltas_usage_and_closes_connection() -> None:
    stream = FakeResponseStream()
    client = SimpleNamespace(responses=FakeResponsesResource(stream))
    adapter = OpenAiResponsesAdapter("unused", "gpt-test", client=client)
    deltas: list[str] = []

    result = adapter.generate_text_stream(
        instructions="写作",
        input_text="资料",
        on_delta=deltas.append,
    )

    assert result.output == "第一段第二段"
    assert deltas == ["第一段", "第二段"]
    assert result.usage == ProviderUsage(input_tokens=12, output_tokens=8)
    assert stream.closed


def test_compatible_stream_uses_sse_when_capability_is_enabled() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        events = replay_fixture("compatible_chat_stream.json")["events"]
        assert isinstance(events, list)
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    adapter = OpenAiCompatibleChatAdapter(
        "unused",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(streaming=True, usage=True),
        client=openai_client(handler),
    )
    deltas: list[str] = []

    result = adapter.generate_text_stream(
        instructions="写作",
        input_text="资料",
        on_delta=deltas.append,
    )

    assert result.output == "第一段第二段"
    assert deltas == ["第一段", "第二段"]
    assert result.usage == ProviderUsage(input_tokens=10, output_tokens=6)


def test_compatible_stream_falls_back_to_one_complete_delta() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "chatcmpl_fallback",
            "object": "chat.completion",
            "created": 1,
            "model": "compatible-test",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "完整结果"},
            }],
        })

    adapter = OpenAiCompatibleChatAdapter(
        "unused",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(streaming=False),
        client=openai_client(handler),
    )
    deltas: list[str] = []

    result = adapter.generate_text_stream(
        instructions="写作",
        input_text="资料",
        on_delta=deltas.append,
    )

    assert result.output == "完整结果"
    assert deltas == ["完整结果"]


def test_invalid_compatible_structured_output_is_actionable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "chatcmpl_invalid",
            "object": "chat.completion",
            "created": 1,
            "model": "compatible-test",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "not-json"},
            }],
        })

    adapter = OpenAiCompatibleChatAdapter(
        "unused",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(),
        client=openai_client(handler),
    )

    with pytest.raises(ProviderCallError) as caught:
        adapter.generate_structured(
            instructions="归纳",
            input_text="资料",
            output_model=StructuredFixture,
        )

    assert caught.value.category == AiErrorCategory.INVALID_RESPONSE
    assert caught.value.retryable


def test_provider_timeout_is_normalized_for_safe_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    adapter = OpenAiCompatibleChatAdapter(
        "unused",
        "compatible-test",
        "https://provider.test/v1",
        ModelCapabilities(),
        client=openai_client(handler),
    )

    with pytest.raises(ProviderCallError) as caught:
        adapter.generate_text(instructions="写作", input_text="资料")

    assert caught.value.category == AiErrorCategory.TIMEOUT
    assert caught.value.retryable
