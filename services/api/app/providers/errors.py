from json import JSONDecodeError

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import ValidationError

from app.providers.base import ProviderCallError
from app.providers.models import AiErrorCategory


def normalize_provider_error(
    error: Exception,
    *,
    duration_ms: int | None = None,
) -> ProviderCallError:
    if isinstance(error, AuthenticationError):
        return _error(AiErrorCategory.AUTHENTICATION, "API Key 无效，请检查后重试", False, duration_ms)
    if isinstance(error, PermissionDeniedError):
        return _error(AiErrorCategory.PERMISSION, "当前 API Key 无权使用该模型", False, duration_ms)
    if isinstance(error, RateLimitError):
        return _error(AiErrorCategory.RATE_LIMIT, "模型服务限流，稍后可安全重试", True, duration_ms)
    if isinstance(error, (APITimeoutError, TimeoutError)):
        return _error(AiErrorCategory.TIMEOUT, "模型服务超时，可安全重试", True, duration_ms)
    if isinstance(error, APIConnectionError):
        return _error(AiErrorCategory.UNAVAILABLE, "无法连接模型服务，请检查网络或地址", True, duration_ms)
    if isinstance(error, APIStatusError):
        if error.status_code == 401:
            return _error(AiErrorCategory.AUTHENTICATION, "API Key 无效，请检查后重试", False, duration_ms)
        if error.status_code == 403:
            return _error(AiErrorCategory.PERMISSION, "当前 API Key 无权使用该模型", False, duration_ms)
        if error.status_code == 429:
            return _error(AiErrorCategory.RATE_LIMIT, "模型服务限流，稍后可安全重试", True, duration_ms)
        if error.status_code >= 500:
            return _error(AiErrorCategory.UNAVAILABLE, "模型服务暂时不可用，可安全重试", True, duration_ms)
    if isinstance(error, (JSONDecodeError, ValidationError, TypeError, ValueError)):
        return _error(AiErrorCategory.INVALID_RESPONSE, "模型返回内容不符合要求，请重试或换模型", True, duration_ms)
    return _error(AiErrorCategory.UNAVAILABLE, "模型服务未完成本次请求", True, duration_ms)


def _error(
    category: AiErrorCategory,
    safe_message: str,
    retryable: bool,
    duration_ms: int | None,
) -> ProviderCallError:
    return ProviderCallError(
        category,
        safe_message,
        retryable=retryable,
        duration_ms=duration_ms,
    )
