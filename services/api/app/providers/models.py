from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.context.models import ContextPacket


class ProviderKind(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"


class AiTaskType(StrEnum):
    CHAPTER_BRIEF = "chapter_brief"
    CHAPTER_DRAFT = "chapter_draft"
    REFERENCE_ANALYSIS = "reference_analysis"
    REVIEW = "review"


class AiErrorCategory(StrEnum):
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    CANCELLED = "cancelled"


class ModelCapabilities(BaseModel):
    structured_output: bool = False
    streaming: bool = False
    server_cancellation: bool = False
    usage: bool = False


class ModelProfile(BaseModel):
    id: str
    name: str
    provider: ProviderKind
    base_url: str
    model: str
    capabilities: ModelCapabilities
    input_cost_microusd_per_million: int | None
    output_cost_microusd_per_million: int | None
    revision: int
    created_at: str
    updated_at: str


class AiTaskDefault(BaseModel):
    task_type: AiTaskType
    profile_id: str
    profile_name: str
    provider: ProviderKind
    model: str
    revision: int
    updated_at: str


class UpdateAiTaskDefaultRequest(BaseModel):
    profile_id: str = Field(min_length=36, max_length=36)
    expected_revision: int | None = Field(default=None, ge=0)


class AiOutboundPreview(BaseModel):
    task_type: AiTaskType
    profile_id: str | None
    profile_name: str
    provider: ProviderKind
    model: str
    data_types: list[str]
    content_scope: str
    character_count: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_microusd: int | None = Field(default=None, ge=0)
    context_packet: ContextPacket


class ActivateModelProfileRequest(BaseModel):
    api_key: SecretStr
    make_active: bool = True


class CreateModelProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    provider: ProviderKind
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=100, pattern=r"^[\w.:/-]+$")
    input_cost_microusd_per_million: int | None = Field(default=None, ge=0)
    output_cost_microusd_per_million: int | None = Field(default=None, ge=0)

    @field_validator("name", "base_url", "model")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("模型配置不能包含空字节")
        return value

    @model_validator(mode="after")
    def validate_base_url(self) -> CreateModelProfileRequest:
        from app.providers.validation import normalize_provider_base_url

        self.base_url = normalize_provider_base_url(self.provider, self.base_url)
        return self


class UpdateModelProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    provider: ProviderKind
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=100, pattern=r"^[\w.:/-]+$")
    input_cost_microusd_per_million: int | None = Field(default=None, ge=0)
    output_cost_microusd_per_million: int | None = Field(default=None, ge=0)
    expected_revision: int = Field(ge=0)

    @field_validator("name", "base_url", "model")
    @classmethod
    def reject_null_bytes(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("模型配置不能包含空字节")
        return value

    @model_validator(mode="after")
    def validate_base_url(self) -> UpdateModelProfileRequest:
        from app.providers.validation import normalize_provider_base_url

        self.base_url = normalize_provider_base_url(self.provider, self.base_url)
        return self
