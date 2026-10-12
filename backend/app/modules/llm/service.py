from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import UnavailableError
from app.db.session import get_session
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
    config_name: str | None = Field(default=None, description="LLM configuration (Settings) that was resolved")
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
    session: Annotated[Session, Depends(get_session)],
    check: Annotated[bool, Query(description="Run the configured provider's connection/model check")] = False,
    project_id: Annotated[str | None, Query(description="Report the project's default LLM configuration")] = None,
    config_id: Annotated[str | None, Query(description="Report a specific LLM configuration")] = None,
) -> LLMStatus:
    from app.modules.settings.router import get_settings_service

    settings: Settings = request.app.state.settings
    name: str | None = None
    if project_id or config_id:
        settings_service = get_settings_service(request, session)
        effective = settings_service.effective_llm_id(project_id, config_id) if project_id else config_id
        provider = settings_service.provider_for(effective)
        name = settings_service.get_llm(effective or "env-default").name
    if provider is None:
        return LLMStatus(
            configured=False,
            config_name=name,
            detail="No LLM is available: register an LLM configuration in Settings or configure the environment "
            "default (OLS_LLM_BASE_URL, OLS_LLM_MODEL).",
        )
    status = LLMStatus(
        configured=True,
        config_name=name,
        provider=provider.name,
        model=provider.model,
        structured_output=getattr(provider, "_structured_output", settings.llm_structured_output),
        detail="Configured",
    )
    effective_id = settings_service.effective_llm_id(project_id, config_id) if project_id else config_id
    selected_endpoint = (
        settings_service.get_llm(effective_id).base_url
        if effective_id
        else settings.llm_base_url
    )
    if selected_endpoint:
        endpoint = urlsplit(selected_endpoint)
        if endpoint.hostname:
            status.endpoint_host = endpoint.hostname
            if endpoint.port:
                status.endpoint_host += f":{endpoint.port}"
    if check:
        status.reachable, status.detail, status.model_available = provider.check_connection()
    return status
