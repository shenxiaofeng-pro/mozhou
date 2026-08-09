import ipaddress
from urllib.parse import urlsplit, urlunsplit

from app.providers.models import ProviderKind

OPENAI_BASE_URL = "https://api.openai.com/v1"
LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def normalize_provider_base_url(provider: ProviderKind, value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("模型地址格式无效") from error
    hostname = parsed.hostname
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("模型地址必须是不含凭据、query 或 fragment 的 HTTP(S) URL")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("模型地址端口无效")
    if parsed.scheme == "http" and not _is_loopback(hostname):
        raise ValueError("非本机模型地址必须使用 HTTPS")

    normalized_path = parsed.path.rstrip("/")
    normalized = urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))
    if provider == ProviderKind.OPENAI and normalized != OPENAI_BASE_URL:
        raise ValueError("OpenAI profile 必须使用官方 API 地址")
    return normalized


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def default_capabilities(provider: ProviderKind) -> dict[str, bool]:
    if provider == ProviderKind.OPENAI:
        return {
            "structured_output": True,
            "streaming": True,
            "server_cancellation": False,
            "usage": True,
        }
    return {
        "structured_output": False,
        "streaming": False,
        "server_cancellation": False,
        "usage": False,
    }
