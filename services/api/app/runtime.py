import os
import warnings

from fastapi import FastAPI

from app.main import create_app

SESSION_TOKEN_ENV = "MOZHOU_API_SESSION_TOKEN"
INSECURE_DEV_ENV = "MOZHOU_ALLOW_INSECURE_DEV_API"


def create_runtime_app() -> FastAPI:
    session_token = os.environ.get(SESSION_TOKEN_ENV)
    allow_insecure_development = os.environ.get(INSECURE_DEV_ENV) == "1"
    if session_token is None and not allow_insecure_development:
        raise RuntimeError(
            "本地 API 缺少启动会话令牌；仅浏览器开发可显式设置 "
            f"{INSECURE_DEV_ENV}=1"
        )
    if session_token is None:
        warnings.warn(
            "墨舟本地 API 正以无会话令牌的浏览器开发兼容模式运行；不要用于桌面发行或共享网络。",
            RuntimeWarning,
            stacklevel=2,
        )
    return create_app(session_token=session_token)
