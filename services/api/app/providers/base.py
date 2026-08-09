from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.providers.models import AiErrorCategory, ModelCapabilities, ProviderKind

StructuredOutput = TypeVar("StructuredOutput", bound=BaseModel)


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult[Output]:
    output: Output
    usage: ProviderUsage
    duration_ms: int


@dataclass(frozen=True)
class ProviderAdapterConfig:
    provider: ProviderKind
    base_url: str
    model: str
    capabilities: ModelCapabilities


class ProviderCallError(RuntimeError):
    def __init__(
        self,
        category: AiErrorCategory,
        safe_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        self.retryable = retryable


class ProviderAdapter(Protocol):
    @property
    def config(self) -> ProviderAdapterConfig: ...

    def generate_text(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int | None = None,
    ) -> ProviderResult[str]: ...

    def generate_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        output_model: type[StructuredOutput],
    ) -> ProviderResult[StructuredOutput]: ...
