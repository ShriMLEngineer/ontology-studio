import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,119}$")


def _env_name(value: str) -> str:
    if not _ENV_NAME.match(value):
        # The rejected value is deliberately not echoed: a user may have pasted a secret here.
        raise ValueError(
            "Enter the NAME of a server environment variable (letters, digits and underscores, "
            "for example OPENAI_API_KEY), never the secret itself."
        )
    return value


EnvName = Annotated[str, StringConstraints(strip_whitespace=True), AfterValidator(_env_name)]


class ConnectionTest(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    tested_at: datetime | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------------- LLM


class LlmConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    provider: Literal["openai", "anthropic", "azure-foundry", "ollama", "openai-compatible"] = "openai-compatible"
    base_url: Url | None = Field(default=None, description="Provider endpoint; omitted for direct OpenAI/Anthropic")
    model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    api_key_env: EnvName | None = Field(
        default=None, description="Name of the server environment variable that holds the API key (never the key)"
    )
    provider_config: dict[str, Any] = Field(default_factory=dict)
    structured_output: Literal["json_schema", "json_object", "prompt"] = "json_schema"
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: float = Field(default=600.0, ge=5.0, le=3600.0)
    max_output_tokens: int = Field(default=4096, ge=256, le=200_000)
    enabled: bool = True
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""

    @field_validator("base_url")
    @classmethod
    def _http(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("the endpoint must start with http:// or https://")
        return value.rstrip("/") if value else value

    @field_validator("provider_config")
    @classmethod
    def _no_secrets(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {"api_key", "apikey", "secret", "password", "token", "credential"}
        stack = [value]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, item in current.items():
                    if str(key).lower() in forbidden:
                        raise ValueError("Provider settings cannot contain credentials; use an environment-variable name.")
                    stack.append(item)
            elif isinstance(current, list):
                stack.extend(current)
        return value

    @model_validator(mode="after")
    def _provider_options(self) -> "LlmConfigInput":
        allowed = {
            "azure-foundry": {"deployment_type", "auth_method", "api_version", "resource", "inference_parameters"},
            "anthropic": {"inference_parameters"},
            "openai": {"inference_parameters"},
            "ollama": {"inference_parameters"},
            "openai-compatible": {"inference_parameters"},
        }[self.provider]
        extra = set(self.provider_config) - allowed
        if extra:
            raise ValueError(f"Unsupported settings for {self.provider}: {', '.join(sorted(extra))}")
        parameters = self.provider_config.get("inference_parameters", {})
        if not isinstance(parameters, dict):
            raise ValueError("inference_parameters must be an object.")
        supported = (
            {"top_p", "top_k"} if self.provider == "anthropic"
            else {"top_p", "reasoning_effort"} if self.provider in {"openai", "azure-foundry"}
            else {"top_p"}
        )
        unsupported = set(parameters) - supported
        if unsupported:
            raise ValueError(
                f"Unsupported inference parameters for {self.provider}: {', '.join(sorted(unsupported))}"
            )
        return self


class LlmConfigRead(BaseModel):
    id: str
    name: str
    builtin: bool
    provider: str
    base_url: str | None
    model: str | None
    api_key_env: str | None
    api_key_present: bool | None = Field(description="Whether the named environment variable is set (value never returned)")
    provider_config: dict[str, Any] = Field(default_factory=dict)
    structured_output: str
    temperature: float
    timeout_seconds: float
    max_output_tokens: int
    description: str
    configured: bool
    enabled: bool = True
    last_test: ConnectionTest | None
    used_by_projects: list[str]
    updated_by: str = ""
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------------- graph


class GraphConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    kind: str
    config: dict[str, Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = Field(default_factory=dict)
    secret_env: EnvName | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class GraphConnectionRead(BaseModel):
    id: str
    name: str
    builtin: bool
    kind: str
    kind_label: str
    model: str
    config: dict[str, Any]
    secret_env: str | None
    secret_present: bool | None
    description: str
    last_test: ConnectionTest | None
    used_by_projects: list[str]
    updated_by: str = ""
    updated_at: datetime | None = None


class ConfigFieldRead(BaseModel):
    key: str
    label: str
    required: bool
    secret: bool
    placeholder: str


class GraphKindRead(BaseModel):
    id: str
    label: str
    model: str
    builtin: bool
    registrable: bool
    available: bool
    description: str
    unavailable_reason: str
    fields: list[ConfigFieldRead]


# ---------------------------------------------------------------------------------- project defaults


class ProjectDefaults(BaseModel):
    project_id: str
    default_llm_config_id: str
    default_discovery_llm_config_id: str
    default_kg_llm_config_id: str
    default_graph_connection_id: str
    data_namespace: str | None
    effective_llm: LlmConfigRead
    effective_discovery_llm: LlmConfigRead
    effective_kg_llm: LlmConfigRead
    effective_graph: GraphConnectionRead


class ProjectDefaultsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_llm_config_id: str | None = None
    default_discovery_llm_config_id: str | None = None
    default_kg_llm_config_id: str | None = None
    default_graph_connection_id: str | None = None
    data_namespace: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
