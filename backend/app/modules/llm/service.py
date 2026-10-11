from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.core.config import Settings
from app.core.errors import UnavailableError
from app.modules.llm.openai_compatible import OpenAICompatibleProvider
from app.modules.llm.provider import LLMNotConfiguredError, LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider | None:
    """Create the configured provider, or ``None`` when no LLM endpoint is configured."""
    if not settings.llm_base_url or not settings.llm_model:
        return None
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key.get_secret_value() if settings.llm_api_key else None,
        structured_output=settings.llm_structured_output,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        max_repair_attempts=settings.llm_max_repair_attempts,
    )


def get_llm_provider(request: Request) -> LLMProvider | None:
    return getattr(request.app.state, "llm_provider", None)


def require_llm_provider(
    provider: Annotated[LLMProvider | None, Depends(get_llm_provider)],
) -> LLMProvider:
    if provider is None:
        raise UnavailableError(
            "No LLM provider is configured. Set OLS_LLM_BASE_URL and OLS_LLM_MODEL (see .env.example).",
            code=LLMNotConfiguredError.code,
        )
    return provider


class LLMStatus(BaseModel):
    configured: bool
    provider: str | None = None
    model: str | None = None
    endpoint_host: str | None = None
    structured_output: str | None = None
    reachable: bool | None = None
    model_available: bool | None = None
    detail: str


router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status", response_model=LLMStatus)
def llm_status(
    request: Request,
    provider: Annotated[LLMProvider | None, Depends(get_llm_provider)],
    check: Annotated[bool, Query(description="Probe the endpoint's /models API")] = False,
) -> LLMStatus:
    settings: Settings = request.app.state.settings
    if provider is None:
        return LLMStatus(
            configured=False,
            detail="AI discovery is disabled until OLS_LLM_BASE_URL and OLS_LLM_MODEL are configured.",
        )
    status = LLMStatus(
        configured=True,
        provider=provider.name,
        model=provider.model,
        structured_output=settings.llm_structured_output,
        detail="Configured",
    )
    if isinstance(provider, OpenAICompatibleProvider):
        status.endpoint_host = urlsplit(provider.base_url).netloc or provider.base_url
        if check:
            status.reachable, status.detail, status.model_available = provider.check_connection()
    return status
