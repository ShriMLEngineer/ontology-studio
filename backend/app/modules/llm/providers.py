"""Protocol-specific adapters for registered LLM providers.

All adapters normalize replies into the existing Pydantic-validated contract. Credentials are
passed only to server-side SDK clients and are never included in adapter errors or logs.
"""

import logging
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from anthropic import AnthropicError
from azure.core.exceptions import AzureError
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from app.modules.llm.openai_compatible import (
    OpenAICompatibleProvider,
    _summarize_error,
    inline_schema_refs,
    parse_structured,
)
from app.modules.llm.provider import (
    LLMOutputError,
    LLMTransportError,
    LLMUsage,
    StructuredResult,
    T,
)

logger = logging.getLogger(__name__)
_REASONING_MODEL = re.compile(r"^(o[134]\b|gpt-5(?:[-.]|$))", re.IGNORECASE)
_PROVIDER_ERRORS = (AnthropicError, AzureError, OpenAIError)
_QUOTA_EXHAUSTED = {"insufficient_quota", "credit_balance_exhausted"}


def _quota_exhausted(error: Exception) -> bool:
    return (
        getattr(error, "code", None) in _QUOTA_EXHAUSTED
        or getattr(error, "type", None) in _QUOTA_EXHAUSTED
    )


def _safe_error(error: Exception, timeout: float) -> str:
    status = getattr(error, "status_code", None)
    name = error.__class__.__name__.lower()
    if _quota_exhausted(error):
        return "The provider account has no remaining credit or quota. Check the plan and billing."
    if "timeout" in name:
        return f"The provider did not respond within {timeout:.0f} seconds."
    if status == 401:
        return "The provider rejected the configured credentials."
    if status == 403:
        return "The configured credentials do not have access to this model."
    if status == 404:
        return "The configured model or deployment was not found."
    if status == 429:
        return "The provider rate limit was reached. Try again later."
    if isinstance(status, int) and status >= 500:
        return f"The provider is temporarily unavailable (HTTP {status})."
    if status:
        return f"The provider returned an error (HTTP {status})."
    return "Could not reach the provider. Check the endpoint and network connection."


def _usage(value: Any, prompt_field: str, completion_field: str) -> LLMUsage:
    if value is None:
        return LLMUsage()
    return LLMUsage(
        prompt_tokens=int(getattr(value, prompt_field, 0) or 0),
        completion_tokens=int(getattr(value, completion_field, 0) or 0),
    )


class _StructuredSdkProvider:
    def __init__(
        self, *, name: str, model: str, timeout_seconds: float, max_output_tokens: int,
        temperature: float, max_repair_attempts: int,
    ) -> None:
        self._name = name
        self._model = model
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._max_repair_attempts = max_repair_attempts

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def _complete(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> tuple[str, T | None, LLMUsage]:
        raise NotImplementedError

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> StructuredResult[T]:
        prompt = user
        last_text = ""
        last_error: Exception | None = None
        usage = LLMUsage()
        for attempt in range(1 + self._max_repair_attempts):
            for retry in range(3):
                try:
                    last_text, parsed, call_usage = self._complete(
                        system=system, user=prompt, schema=schema, schema_name=schema_name
                    )
                    break
                except LLMTransportError:
                    raise
                except _PROVIDER_ERRORS as error:
                    status = getattr(error, "status_code", None)
                    transient = (
                        status in (429, 500, 502, 503, 504) or "timeout" in error.__class__.__name__.lower()
                    ) and not _quota_exhausted(error)
                    if not transient or retry == 2:
                        raise LLMTransportError(_safe_error(error, self._timeout)) from error
                    time.sleep(0.25 * (2 ** retry))
            usage = usage + call_usage
            try:
                value = schema.model_validate(parsed.model_dump()) if parsed is not None else parse_structured(last_text, schema)
                return StructuredResult(value=value, raw_text=last_text, usage=usage, attempts=attempt + 1)
            except (ValueError, ValidationError) as error:
                last_error = error
                logger.warning("LLM output failed Pydantic validation (attempt %s).", attempt + 1)
                prompt = (
                    f"{user}\n\nYour previous response failed schema validation: "
                    f"{_summarize_error(error)}. Reply with corrected JSON only."
                )
        raise LLMOutputError(
            f"The model returned output that does not match the required schema after "
            f"{1 + self._max_repair_attempts} attempt(s): "
            f"{_summarize_error(last_error) if last_error else 'unknown error'}",
            raw_text=last_text,
        )

    def check_connection(self, timeout: float = 10.0) -> tuple[bool, str, bool | None]:
        raise NotImplementedError


class OpenAIProvider(_StructuredSdkProvider):
    def __init__(
        self, *, model: str, api_key: str, base_url: str, timeout_seconds: float,
        max_output_tokens: int, temperature: float, inference_parameters: dict[str, Any] | None = None,
        max_repair_attempts: int = 1, client_factory: Callable[..., Any] | None = None,
        azure_entra: bool = False, default_query: dict[str, str] | None = None,
        api_style: str | None = None, inference_probe_fallback: bool = False,
        provider_name: str = "openai",
    ) -> None:
        super().__init__(
            name=provider_name, model=model, timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens, temperature=temperature,
            max_repair_attempts=max_repair_attempts,
        )
        self._api_key = api_key
        self._base_url = base_url
        self._parameters = inference_parameters or {}
        self._client_factory = client_factory
        self._azure_entra = azure_entra
        self._default_query = default_query
        self._api_style = api_style or ("responses" if _REASONING_MODEL.match(model) else "chat")
        self._inference_probe_fallback = inference_probe_fallback

    def _client(self, timeout: float) -> Any:
        if self._client_factory:
            return self._client_factory(timeout=timeout)
        from openai import OpenAI

        options: dict[str, Any] = {
            "api_key": self._api_key, "base_url": self._base_url,
            "timeout": timeout, "max_retries": 0,
        }
        if self._default_query:
            options["default_query"] = self._default_query
        if self._azure_entra:
            from azure.identity import DefaultAzureCredential

            token = DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default")
            options["api_key"] = token.token
        return OpenAI(**options)

    def _complete(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> tuple[str, T | None, LLMUsage]:
        parameters = dict(self._parameters)
        if _REASONING_MODEL.match(self._model):
            parameters.pop("temperature", None)
        else:
            parameters.setdefault("temperature", self._temperature)
        client = self._client(self._timeout)
        if self._api_style == "responses":
            response = client.responses.parse(
                model=self._model,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                text_format=schema,
                max_output_tokens=self._max_output_tokens,
                **parameters,
            )
            parsed = getattr(response, "output_parsed", None)
            output_text = getattr(response, "output_text", "") or ""
            raw_usage = _usage(getattr(response, "usage", None), "input_tokens", "output_tokens")
        else:
            response = client.chat.completions.parse(
                model=self._model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=schema,
                max_completion_tokens=self._max_output_tokens,
                **parameters,
            )
            choice = response.choices[0]
            parsed = getattr(choice.message, "parsed", None)
            output_text = choice.message.content or ""
            raw_usage = _usage(getattr(response, "usage", None), "prompt_tokens", "completion_tokens")
        if parsed is not None and not isinstance(parsed, BaseModel):
            parsed = schema.model_validate(parsed)
        return output_text or (parsed.model_dump_json() if parsed else ""), parsed, raw_usage

    def check_connection(self, timeout: float = 10.0) -> tuple[bool, str, bool | None]:
        try:
            self._client(timeout).models.retrieve(self._model)
            return True, "Connected; configured model is available.", True
        except (OpenAIError, AzureError) as error:
            if self._inference_probe_fallback and getattr(error, "status_code", None) in (404, 405):
                try:
                    client = self._client(timeout)
                    if self._api_style == "responses":
                        response = client.responses.create(
                            model=self._model, input="Reply OK.", max_output_tokens=1
                        )
                        available = bool(getattr(response, "output_text", None))
                    else:
                        response = client.chat.completions.create(
                            model=self._model,
                            messages=[{"role": "user", "content": "Reply OK."}],
                            max_completion_tokens=1,
                        )
                        available = bool(response.choices)
                    if available:
                        return True, "Connected; configured model responded.", True
                except (OpenAIError, AzureError) as probe_error:
                    return False, _safe_error(probe_error, timeout), False
            return False, _safe_error(error, timeout), False


class AnthropicProvider(_StructuredSdkProvider):
    def __init__(
        self, *, model: str, api_key: str, base_url: str, timeout_seconds: float,
        max_output_tokens: int, temperature: float, inference_parameters: dict[str, Any] | None = None,
        max_repair_attempts: int = 1, client_factory: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(
            name="anthropic", model=model, timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens, temperature=temperature,
            max_repair_attempts=max_repair_attempts,
        )
        self._api_key = api_key
        self._base_url = base_url
        self._parameters = inference_parameters or {}
        self._client_factory = client_factory

    def _client(self, timeout: float) -> Any:
        if self._client_factory:
            return self._client_factory(timeout=timeout)
        from anthropic import Anthropic

        return Anthropic(api_key=self._api_key, base_url=self._base_url, timeout=timeout, max_retries=0)

    def _complete(
        self, *, system: str, user: str, schema: type[T], schema_name: str
    ) -> tuple[str, T | None, LLMUsage]:
        params: dict[str, Any] = dict(self._parameters)
        params.setdefault("temperature", self._temperature)
        response = self._client(self._timeout).messages.create(
            model=self._model,
            max_tokens=self._max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": inline_schema_refs(schema.model_json_schema())}
            },
            **params,
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return text, None, _usage(getattr(response, "usage", None), "input_tokens", "output_tokens")

    def check_connection(self, timeout: float = 10.0) -> tuple[bool, str, bool | None]:
        try:
            response = self._client(timeout).messages.create(
                model=self._model, max_tokens=1, messages=[{"role": "user", "content": "Reply with OK."}]
            )
            if not getattr(response, "content", None):
                return False, "The provider returned no model response.", False
            return True, "Connected; configured model responded.", True
        except (AnthropicError, AzureError) as error:
            return False, _safe_error(error, timeout), False


class AzureFoundryAnthropicProvider(AnthropicProvider):
    def __init__(self, *, resource: str, auth_method: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._resource = resource
        self._auth_method = auth_method
        self._name = "azure-foundry-anthropic"

    def _client(self, timeout: float) -> Any:
        if self._client_factory:
            return self._client_factory(timeout=timeout)
        from anthropic import AnthropicFoundry

        options: dict[str, Any] = {"resource": self._resource, "timeout": timeout, "max_retries": 0}
        if self._auth_method == "entra_id":
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            options["azure_ad_token_provider"] = get_bearer_token_provider(
                DefaultAzureCredential(), "https://ai.azure.com/.default"
            )
        else:
            options["api_key"] = self._api_key
        return AnthropicFoundry(**options)


class OllamaProvider(OpenAICompatibleProvider):
    """Native Ollama endpoint for generation, with model-presence verification for Settings."""

    def __init__(self, *, base_url: str, **kwargs: Any) -> None:
        endpoint = base_url.rstrip("/")
        self._ollama_url = endpoint.removesuffix("/v1")
        super().__init__(base_url=f"{self._ollama_url}/v1", **kwargs)

    @property
    def name(self) -> str:
        return "ollama"

    def check_connection(self, timeout: float = 10.0) -> tuple[bool, str, bool | None]:
        import httpx2

        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            response = httpx2.post(
                f"{self._ollama_url}/api/show",
                json={"model": self.model},
                headers=headers,
                timeout=httpx2.Timeout(timeout, connect=min(timeout, 5.0)),
            )
        except httpx2.TimeoutException:
            return False, f"The Ollama server did not respond within {timeout:.0f} seconds.", False
        except httpx2.HTTPError as error:
            return False, f"Could not reach the Ollama server ({error.__class__.__name__}).", False
        if response.status_code == 200:
            return True, "Connected; configured model is available.", True
        if response.status_code == 404:
            return False, f"Model '{self.model}' is not available on the Ollama server.", False
        if response.status_code in (401, 403):
            return False, "The Ollama server rejected the configured credentials.", False
        return False, f"The Ollama server returned HTTP {response.status_code}.", False


def _inference_parameters(config: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    value = config.get("inference_parameters", {})
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key in allowed and item is not None}


def build_registered_provider(
    *, provider: str, base_url: str | None, model: str, api_key: str | None,
    provider_config: dict[str, Any] | None, structured_output: str, temperature: float,
    timeout_seconds: float, max_output_tokens: int, max_repair_attempts: int,
) -> Any:
    """Create the proper provider client; legacy OpenAI-compatible rows remain readable."""
    options = provider_config or {}
    parameter_allowlist = (
        {"top_p", "top_k"} if provider == "anthropic"
        else {"top_p", "reasoning_effort"} if provider in {"openai", "azure-foundry"}
        else {"top_p"}
    )
    parameters = _inference_parameters(options, parameter_allowlist)
    if provider in ("ollama", "openai-compatible"):
        if not base_url:
            raise ValueError("A base URL is required for this provider.")
        provider_class = OllamaProvider if provider == "ollama" else OpenAICompatibleProvider
        return provider_class(
            base_url=base_url, model=model, api_key=api_key, structured_output=structured_output,
            temperature=temperature, timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens, max_repair_attempts=max_repair_attempts,
            inference_parameters=parameters,
        )
    if provider == "openai":
        return OpenAIProvider(
            model=model, api_key=api_key or "", base_url=base_url or "https://api.openai.com/v1",
            timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens, temperature=temperature,
            inference_parameters=parameters, max_repair_attempts=max_repair_attempts,
            api_style="responses" if _REASONING_MODEL.match(model) else "chat",
        )
    if provider == "anthropic":
        return AnthropicProvider(
            model=model, api_key=api_key or "", base_url=base_url or "https://api.anthropic.com",
            timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens, temperature=temperature,
            inference_parameters=parameters, max_repair_attempts=max_repair_attempts,
        )
    if provider == "azure-foundry":
        deployment_type = options.get("deployment_type")
        auth_method = options.get("auth_method", "api_key")
        if not base_url:
            raise ValueError("An Azure Foundry endpoint is required.")
        if deployment_type == "anthropic":
            resource = options.get("resource") or urlsplit(base_url).hostname
            if not resource:
                raise ValueError("An Azure Foundry resource name is required.")
            return AzureFoundryAnthropicProvider(
                resource=str(resource).split(".")[0], auth_method=auth_method,
                model=model, api_key=api_key or "", base_url=base_url,
                timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens,
                temperature=temperature, inference_parameters=parameters,
                max_repair_attempts=max_repair_attempts,
            )
        if deployment_type not in ("azure-openai", "openai-compatible"):
            raise ValueError("Choose an Azure Foundry deployment API type.")
        if deployment_type == "azure-openai":
            endpoint = f"{base_url.rstrip('/')}/openai/v1/"
            query = None
        else:
            endpoint = base_url.rstrip("/")
            if not endpoint.endswith("/models"):
                endpoint += "/models"
            query = {"api-version": str(options.get("api_version") or "2024-05-01-preview")}
        return OpenAIProvider(
            model=model, api_key=api_key or "", base_url=endpoint,
            timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens, temperature=temperature,
            inference_parameters=parameters, max_repair_attempts=max_repair_attempts,
            azure_entra=auth_method == "entra_id", default_query=query,
            api_style="chat" if deployment_type == "openai-compatible" else (
                "responses" if _REASONING_MODEL.match(model) else "chat"
            ),
            inference_probe_fallback=True,
            provider_name=f"azure-foundry-{deployment_type}",
        )
    raise ValueError(f"Unsupported LLM provider '{provider}'.")


def provider_snapshot(record: Any) -> dict[str, Any]:
    """Return non-secret registry settings required to explain a historical model run."""
    return {
        "config_id": record.id,
        "name": record.name,
        "provider": record.provider,
        "model": record.model,
        "endpoint": record.base_url,
        "provider_config": record.provider_config or {},
        "temperature": record.temperature,
        "max_output_tokens": record.max_output_tokens,
        "timeout_seconds": record.timeout_seconds,
        "enabled": record.enabled,
        "api_key_env": record.api_key_env,
    }