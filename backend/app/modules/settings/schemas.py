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
    """Registration of a graph database. ``kind`` (alias ``provider``) selects the provider; the
    provider's catalogue entry defines and validates ``config`` and the credential reference."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    kind: str
    config: dict[str, str | int | float | bool] = Field(default_factory=dict)
    secret_env: EnvName | None = None
    enabled: bool = True
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""

    @model_validator(mode="before")
    @classmethod
    def _provider_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "provider" in data:
            data = dict(data)
            provider = data.pop("provider")
            if data.get("kind") not in (None, provider):
                raise ValueError("'provider' and 'kind' must match when both are given.")
            data["kind"] = provider
        return data


class GraphCapabilities(BaseModel):
    """What a registration can do, stated separately so a connection is never mistaken for deployment readiness."""

    registered: bool = True
    connection_supported: bool
    connected: bool = Field(description="The last connection test succeeded")
    read_supported: bool = Field(description="The Graph Explorer can read deployments back from this provider")
    deployment_supported: bool = Field(description="The provider adapter can write and verify a build's projection")
    write_configured: bool = Field(description="This registration allows writes (for example a SPARQL update endpoint)")
    deployment_ready: bool = Field(description="Enabled, connected (where applicable), supported and writable")
    deployment_verified: bool = Field(description="A deployment to this registration was written and read back successfully")
    live_tested: bool = Field(description="The provider adapter was exercised against a real server of this provider")
    verification_note: str = ""
    last_deployment_at: datetime | None = None


class GraphConnectionRead(BaseModel):
    id: str
    name: str
    builtin: bool
    kind: str
    provider: str
    kind_label: str
    model: str
    protocol: str = ""
    config: dict[str, Any]
    effective_endpoints: dict[str, str | None] = Field(default_factory=dict)
    secret_env: str | None
    secret_present: bool | None
    description: str
    enabled: bool = True
    is_default: bool = False
    status: Literal["not_tested", "connected", "failed"] = "not_tested"
    capabilities: GraphCapabilities
    deployment_count: int = 0
    last_test: ConnectionTest | None
    used_by_projects: list[str]
    updated_by: str = ""
    updated_at: datetime | None = None


class FieldOptionRead(BaseModel):
    value: str
    label: str


class VisibleWhenRead(BaseModel):
    field: str
    values: list[str]


class ConfigFieldRead(BaseModel):
    key: str
    label: str
    required: bool
    secret: bool
    placeholder: str
    type: str = "text"
    default: str = ""
    options: list[FieldOptionRead] = Field(default_factory=list)
    help: str = ""
    visible_when: VisibleWhenRead | None = None
    minimum: float | None = None
    maximum: float | None = None


class GraphKindRead(BaseModel):
    id: str
    label: str
    model: str
    builtin: bool
    registrable: bool
    available: bool
    description: str
    unavailable_reason: str
    protocol: str = ""
    connection_supported: bool = True
    read_supported: bool = False
    deployment_supported: bool = False
    live_tested: bool = False
    verification_note: str = ""
    fields: list[ConfigFieldRead]


class GraphActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


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
