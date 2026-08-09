import json
from time import perf_counter
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.providers.base import (
    ProviderAdapterConfig,
    ProviderResult,
    ProviderUsage,
    StructuredOutput,
)
from app.providers.errors import normalize_provider_error
from app.providers.models import ModelCapabilities, ProviderKind
from app.providers.validation import OPENAI_BASE_URL


class OpenAiResponsesAdapter:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        client: OpenAI | None = None,
    ) -> None:
        self._config = ProviderAdapterConfig(
            provider=ProviderKind.OPENAI,
            base_url=OPENAI_BASE_URL,
            model=model,
            capabilities=ModelCapabilities(
                structured_output=True,
                streaming=True,
                server_cancellation=False,
                usage=True,
            ),
        )
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=OPENAI_BASE_URL,
            timeout=120.0,
            max_retries=0,
        )

    @property
    def config(self) -> ProviderAdapterConfig:
        return self._config

    def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int | None = None,
    ) -> ProviderResult[str]:
        started = perf_counter()
        try:
            response = self.client.responses.create(
                model=self.config.model,
                instructions=instructions,
                input=input_text,
                max_output_tokens=max_output_tokens,
                store=False,
            )
            output = response.output_text.strip()
            if not output:
                raise ValueError("empty provider response")
            return ProviderResult(
                output=output,
                usage=_responses_usage(response.usage),
                duration_ms=_duration_ms(started),
            )
        except Exception as error:
            raise normalize_provider_error(error) from error

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        output_model: type[StructuredOutput],
    ) -> ProviderResult[StructuredOutput]:
        started = perf_counter()
        try:
            response = self.client.responses.parse(
                model=self.config.model,
                instructions=instructions,
                input=input_text,
                text_format=output_model,
                store=False,
            )
            output = response.output_parsed
            if not isinstance(output, output_model):
                raise TypeError("missing structured provider response")
            return ProviderResult(
                output=output,
                usage=_responses_usage(response.usage),
                duration_ms=_duration_ms(started),
            )
        except Exception as error:
            raise normalize_provider_error(error) from error


class OpenAiCompatibleChatAdapter:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        capabilities: ModelCapabilities,
        *,
        client: OpenAI | None = None,
    ) -> None:
        self._config = ProviderAdapterConfig(
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url=base_url,
            model=model,
            capabilities=capabilities,
        )
        self.client = client or OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
            max_retries=0,
        )

    @property
    def config(self) -> ProviderAdapterConfig:
        return self._config

    def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int | None = None,
    ) -> ProviderResult[str]:
        started = perf_counter()
        try:
            completion = self.client.chat.completions.create(
                model=self.config.model,
                messages=_messages(instructions, input_text),
                max_completion_tokens=max_output_tokens,
            )
            output = completion.choices[0].message.content
            if not isinstance(output, str) or not output.strip():
                raise ValueError("empty provider response")
            return ProviderResult(
                output=output.strip(),
                usage=_chat_usage(completion.usage),
                duration_ms=_duration_ms(started),
            )
        except Exception as error:
            raise normalize_provider_error(error) from error

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        output_model: type[StructuredOutput],
    ) -> ProviderResult[StructuredOutput]:
        started = perf_counter()
        schema_instruction = (
            f"\n只返回一个 JSON 对象，必须通过以下 JSON Schema："
            f"{json.dumps(output_model.model_json_schema(), ensure_ascii=False, separators=(',', ':'))}"
        )
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": _messages(instructions + schema_instruction, input_text),
        }
        if self.config.capabilities.structured_output:
            request["response_format"] = {"type": "json_object"}
        try:
            completion = self.client.chat.completions.create(**request)
            raw = completion.choices[0].message.content
            if not isinstance(raw, str):
                raise TypeError("missing structured provider response")
            output = output_model.model_validate(json.loads(raw))
            return ProviderResult(
                output=output,
                usage=_chat_usage(completion.usage),
                duration_ms=_duration_ms(started),
            )
        except Exception as error:
            raise normalize_provider_error(error) from error


def _messages(instructions: str, input_text: str) -> list[ChatCompletionMessageParam]:
    return [
        {"role": "system", "content": instructions},
        {"role": "user", "content": input_text},
    ]


def _responses_usage(usage: object | None) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=_nonnegative_int(getattr(usage, "input_tokens", None)),
        output_tokens=_nonnegative_int(getattr(usage, "output_tokens", None)),
    )


def _chat_usage(usage: object | None) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=_nonnegative_int(getattr(usage, "prompt_tokens", None)),
        output_tokens=_nonnegative_int(getattr(usage, "completion_tokens", None)),
    )


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _duration_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))
