from types import SimpleNamespace
from typing import Any

import pytest
from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from app.modules.llm.provider import LLMTransportError
from app.modules.llm.providers import (
    AnthropicProvider,
    AzureFoundryAnthropicProvider,
    OllamaProvider,
    OpenAIProvider,
    build_registered_provider,
)
from app.modules.settings.schemas import LlmConfigInput


class Extraction(BaseModel):
    answer: str


class FakeOpenAI:
    def __init__(self, *, parsed: Extraction | None = None, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error
        self.parsed = parsed or Extraction(answer="done")
        self.responses = SimpleNamespace(parse=self.responses_parse)
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.chat_parse))
        self.models = SimpleNamespace(retrieve=self.retrieve)

    def responses_parse(self, **kwargs: Any) -> Any:
        self.calls.append({"api": "responses", **kwargs})
        if self.error:
            raise self.error
        return SimpleNamespace(
            output_parsed=self.parsed,
            output_text=self.parsed.model_dump_json(),
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    def chat_parse(self, **kwargs: Any) -> Any:
        self.calls.append({"api": "chat", **kwargs})
        if self.error:
            raise self.error
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=self.parsed, content=None))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
        )

    def retrieve(self, model: str) -> object:
        self.calls.append({"api": "model-retrieve", "model": model})
        return object()


def test_openai_direct_uses_chat_and_validates_pydantic_output() -> None:
    client = FakeOpenAI()
    provider = OpenAIProvider(
        model="gpt-4.1-mini",
        api_key="test-secret",
        base_url="https://api.openai.com/v1",
        timeout_seconds=10,
        max_output_tokens=500,
        temperature=0.4,
        client_factory=lambda **_: client,
    )
    result = provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert result.value == Extraction(answer="done")
    assert result.usage.prompt_tokens == 3 and result.usage.completion_tokens == 2
    assert client.calls[0]["api"] == "chat"
    assert client.calls[0]["temperature"] == 0.4
    assert provider.check_connection() == (True, "Connected; configured model is available.", True)
    assert client.calls[-1] == {"api": "model-retrieve", "model": "gpt-4.1-mini"}


@pytest.mark.parametrize("model", ["o3-mini", "gpt-5", "gpt-5.4", "gpt-6-luna"])
def test_reasoning_model_uses_responses_without_temperature(model: str) -> None:
    client = FakeOpenAI()
    provider = OpenAIProvider(
        model=model,
        api_key="test-secret",
        base_url="https://api.openai.com/v1",
        timeout_seconds=10,
        max_output_tokens=500,
        temperature=0.4,
        client_factory=lambda **_: client,
    )
    result = provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert result.value.answer == "done"
    assert client.calls[0]["api"] == "responses"
    assert "temperature" not in client.calls[0]


def test_responses_maps_registered_reasoning_effort() -> None:
    client = FakeOpenAI()
    provider = build_registered_provider(
        provider="openai", model="gpt-6-luna", api_key="test-secret",
        base_url="https://api.openai.com/v1", timeout_seconds=10,
        max_output_tokens=500, temperature=0.4, max_repair_attempts=1,
        structured_output="json_schema",
        provider_config={"inference_parameters": {"reasoning_effort": "low"}},
    )
    provider._client_factory = lambda **_: client
    provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert client.calls[0]["api"] == "responses"
    assert client.calls[0]["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in client.calls[0]


def test_openai_errors_are_sanitized() -> None:
    class Unauthorized(OpenAIError):
        status_code = 401

    client = FakeOpenAI(error=Unauthorized("test-secret"))
    provider = OpenAIProvider(
        model="test-model",
        api_key="test-secret",
        base_url="https://api.openai.com/v1",
        timeout_seconds=10,
        max_output_tokens=500,
        temperature=0,
        client_factory=lambda **_: client,
    )
    with pytest.raises(LLMTransportError, match="rejected the configured credentials") as caught:
        provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert "test-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "code,parameter,expected",
    [
        ("unsupported_parameter", "temperature", "'temperature' setting"),
        ("invalid_value", "reasoning.effort", "'reasoning.effort' setting"),
        ("invalid_json_schema", "response_format", "structured-output format or JSON schema"),
        ("test-secret", "test-secret", "model API compatibility"),
    ],
)
def test_openai_bad_requests_are_actionable_without_echoing_provider_text(
    code: str, parameter: str, expected: str,
) -> None:
    class BadRequest(OpenAIError):
        status_code = 400

    error = BadRequest("test-secret private source content")
    error.code = code
    error.param = parameter
    client = FakeOpenAI(error=error)
    provider = OpenAIProvider(
        model="gpt-6-luna", api_key="test-secret", base_url="https://api.openai.com/v1",
        timeout_seconds=10, max_output_tokens=500, temperature=0,
        client_factory=lambda **_: client,
    )
    with pytest.raises(LLMTransportError, match=expected) as caught:
        provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert "test-secret" not in str(caught.value) and "private source content" not in str(caught.value)
    assert len(client.calls) == 1


def test_exhausted_quota_is_reported_clearly_and_not_retried() -> None:
    class QuotaExhausted(OpenAIError):
        status_code = 429
        code = "credit_balance_exhausted"
        type = "insufficient_quota"

    client = FakeOpenAI(error=QuotaExhausted("no credits"))
    provider = OpenAIProvider(
        model="test-model",
        api_key="test-secret",
        base_url="https://api.openai.com/v1",
        timeout_seconds=10,
        max_output_tokens=500,
        temperature=0,
        client_factory=lambda **_: client,
    )
    with pytest.raises(LLMTransportError, match="no remaining credit or quota"):
        provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert len(client.calls) == 1, "a permanent quota error must not be retried"


def test_anthropic_uses_native_messages_and_pydantic_validation() -> None:
    captured: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"answer":"native"}')],
            usage=SimpleNamespace(input_tokens=4, output_tokens=3),
        )

    provider = AnthropicProvider(
        model="claude-sonnet-5-5",
        api_key="test-secret",
        base_url="https://api.anthropic.com",
        timeout_seconds=10,
        max_output_tokens=500,
        temperature=0,
        client_factory=lambda **_: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    result = provider.generate_structured(system="extract", user="text", schema=Extraction, schema_name="result")
    assert result.value.answer == "native"
    assert captured[0]["output_config"]["format"]["type"] == "json_schema"
    assert captured[0]["max_tokens"] == 500


def test_azure_foundry_factory_uses_protocol_specific_adapters() -> None:
    anthropic = build_registered_provider(
        provider="azure-foundry",
        base_url="https://my-resource.services.ai.azure.com/anthropic",
        model="claude-sonnet-deployment",
        api_key="",
        provider_config={"deployment_type": "anthropic", "auth_method": "entra_id"},
        structured_output="json_schema",
        temperature=0,
        timeout_seconds=20,
        max_output_tokens=500,
        max_repair_attempts=1,
    )
    assert isinstance(anthropic, AzureFoundryAnthropicProvider)
    assert anthropic.name == "azure-foundry-anthropic"

    azure_openai = build_registered_provider(
        provider="azure-foundry",
        base_url="https://my-resource.openai.azure.com",
        model="my-deployment",
        api_key="azure-key",
        provider_config={"deployment_type": "azure-openai", "auth_method": "api_key"},
        structured_output="json_schema",
        temperature=0,
        timeout_seconds=20,
        max_output_tokens=500,
        max_repair_attempts=1,
    )
    assert isinstance(azure_openai, OpenAIProvider)
    assert azure_openai._base_url == "https://my-resource.openai.azure.com/openai/v1/"
    assert azure_openai.name == "azure-foundry-azure-openai"

    foundry_model = build_registered_provider(
        provider="azure-foundry",
        base_url="https://my-resource.services.ai.azure.com",
        model="deployment",
        api_key="foundry-key",
        provider_config={"deployment_type": "openai-compatible", "auth_method": "api_key"},
        structured_output="json_schema",
        temperature=0,
        timeout_seconds=20,
        max_output_tokens=500,
        max_repair_attempts=1,
    )
    assert isinstance(foundry_model, OpenAIProvider)
    assert foundry_model._base_url.endswith("/models")
    assert foundry_model._default_query == {"api-version": "2024-05-01-preview"}
    assert foundry_model._api_style == "chat"


def test_ollama_adapter_preserves_openai_compatible_runtime_and_checks_model(monkeypatch: Any) -> None:
    import httpx2

    from app.modules.llm import providers

    seen: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> Any:
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx2, "post", post)
    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="qwen2.5:7b",
        api_key=None,
        structured_output="json_schema",
        temperature=0,
        timeout_seconds=30,
        max_output_tokens=1000,
    )
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.check_connection() == (True, "Connected; configured model is available.", True)
    assert seen == {"url": "http://localhost:11434/api/show", "json": {"model": "qwen2.5:7b"}}
    assert providers.OllamaProvider.name.fget(provider) == "ollama"


def test_provider_configuration_rejects_secrets_and_unsupported_parameters() -> None:
    with pytest.raises(ValidationError):
        LlmConfigInput(
            name="Bad",
            provider="openai",
            model="gpt-4.1-mini",
            api_key_env="OPENAI_API_KEY",
            provider_config={"api_key": "plaintext-secret"},
        )
    with pytest.raises(ValidationError):
        LlmConfigInput(
            name="Bad parameter",
            provider="openai",
            model="gpt-4.1-mini",
            api_key_env="OPENAI_API_KEY",
            provider_config={"inference_parameters": {"top_k": 3}},
        )


def test_registered_models_are_routed_split_by_project_and_can_be_deactivated(
    client: Any, monkeypatch: Any
) -> None:
    openai = client.post(
        "/api/settings/llm-configurations",
        json={
            "name": "OpenAI direct",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "api_key_env": "OPENAI_TEST_KEY",
        },
    )
    assert openai.status_code == 201, openai.text
    direct = openai.json()
    assert direct["base_url"] == "https://api.openai.com/v1"
    assert direct["configured"] is False
    assert "api_key" not in direct
    monkeypatch.setenv("OPENAI_TEST_KEY", "never-return-this")

    ollama = client.post(
        "/api/settings/llm-configurations",
        json={
            "name": "Local Qwen",
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5:7b",
        },
    )
    assert ollama.status_code == 201, ollama.text
    local = ollama.json()
    assert local["configured"] is True and local["api_key_env"] is None

    project = client.post(
        "/api/projects",
        json={
            "name": "Provider selection",
            "default_discovery_llm_config_id": direct["id"],
            "default_kg_llm_config_id": local["id"],
        },
    )
    assert project.status_code == 201, project.text
    defaults = client.get(f"/api/projects/{project.json()['id']}/defaults").json()
    assert defaults["default_discovery_llm_config_id"] == direct["id"]
    assert defaults["default_kg_llm_config_id"] == local["id"]

    monkeypatch.setattr(
        OpenAIProvider,
        "check_connection",
        lambda self, timeout=10: (True, "Connected; configured model is available.", True),
    )
    tested = client.post(f"/api/settings/llm-configurations/{direct['id']}/test")
    assert tested.status_code == 200 and tested.json()["last_test"]["ok"] is True
    status = client.get("/api/llm/status", params={"config_id": direct["id"]}).json()
    assert status["provider"] == "openai" and status["model"] == "gpt-4.1-mini"
    assert "never-return-this" not in tested.text + status.__str__()

    blocked = client.post(
        f"/api/settings/llm-configurations/{local['id']}/activation",
        json={"enabled": False},
    )
    assert blocked.status_code == 409

    updated = client.put(
        f"/api/projects/{project.json()['id']}/defaults",
        json={"default_discovery_llm_config_id": "env-default", "default_kg_llm_config_id": "env-default"},
    )
    assert updated.status_code == 200, updated.text
    deactivated = client.post(
        f"/api/settings/llm-configurations/{local['id']}/activation",
        json={"enabled": False},
    )
    assert deactivated.status_code == 200 and deactivated.json()["enabled"] is False


def test_ollama_registration_test_checks_configured_model(monkeypatch: Any, client: Any) -> None:
    import httpx2

    seen: dict[str, Any] = {}

    def post(url: str, **kwargs: Any) -> Any:
        seen.update(url=url, body=kwargs["json"])
        return SimpleNamespace(status_code=404)

    monkeypatch.setattr(httpx2, "post", post)
    config = client.post(
        "/api/settings/llm-configurations",
        json={
            "name": "Ollama remote",
            "provider": "ollama",
            "base_url": "https://ollama.example",
            "model": "missing-model",
        },
    ).json()
    tested = client.post(f"/api/settings/llm-configurations/{config['id']}/test").json()
    assert tested["last_test"]["ok"] is False
    assert "not available" in tested["last_test"]["message"]
    assert seen == {
        "url": "https://ollama.example/api/show",
        "body": {"model": "missing-model"},
    }