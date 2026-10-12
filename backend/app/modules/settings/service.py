"""Settings use cases: LLM configurations, graph connections, project defaults and resolution.

Built-ins are virtual (not rows): the *environment default* LLM (``OLS_LLM_*``), the local SQL
property graph and the embedded Oxigraph store. Registered configurations reference secrets by
environment-variable name only; values are read when a connection is opened or tested.
"""

import logging
import time
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import utcnow
from app.core.secrets import get_secret, secret_is_set
from app.modules.activity.service import record_activity
from app.modules.graph.targets import (
    BUILTIN_TARGETS,
    KINDS,
    ConnectionResult,
    check_local_sql,
    check_oxigraph,
    check_sparql,
)
from app.modules.graph.targets.catalog import (
    REGISTRATION_ORDER,
    TargetKind,
    display_config,
    is_writable,
    normalize_config,
    sparql_endpoints,
)
from app.modules.llm.provider import LLMProvider
from app.modules.llm.providers import build_registered_provider, provider_snapshot
from app.modules.projects.models import Project
from app.modules.settings.models import GraphConnection, LlmConfiguration
from app.modules.settings.schemas import (
    ConfigFieldRead,
    ConnectionTest,
    FieldOptionRead,
    GraphCapabilities,
    GraphConnectionInput,
    GraphConnectionRead,
    GraphKindRead,
    LlmConfigInput,
    LlmConfigRead,
    ProjectDefaults,
    ProjectDefaultsUpdate,
    VisibleWhenRead,
)

ENV_DEFAULT_LLM = "env-default"
LOCAL_SQL = "local-sql"
OXIGRAPH_EMBEDDED = "oxigraph-embedded"


logger = logging.getLogger("ols.settings")


def _audit(*, event_type: str, summary: str, details: dict[str, Any]) -> None:
    """Configurations are global (not project-scoped): changes go to the server log; records keep
    ``updated_by`` / ``updated_at`` and the last connection test."""
    logger.info("%s: %s %s", event_type, summary, details)


def _test(value: dict[str, Any] | None) -> ConnectionTest | None:
    return ConnectionTest.model_validate(value) if value else None


def _stamp(result: ConnectionResult) -> dict[str, Any]:
    return {**result.as_dict(), "tested_at": utcnow().isoformat()}


class SettingsService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        env_provider: LLMProvider | None,
        builtin_tests: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.env_provider = env_provider
        # Built-ins are not rows: their last test result lives in application state.
        self._builtin_tests = builtin_tests if builtin_tests is not None else {}

    # ------------------------------------------------------------------------------ helpers

    def _projects_using(self, column: str, config_id: str) -> list[str]:
        return list(self.session.scalars(select(Project.name).where(getattr(Project, column) == config_id)))

    def _require_project(self, project_id: str) -> Project:
        project = self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")
        return project

    def _name_taken(self, model: Any, name: str, exclude: str | None = None) -> bool:
        existing = self.session.scalars(select(model).where(model.name == name)).first()
        return existing is not None and existing.id != exclude

    # ------------------------------------------------------------------------------ LLM

    def _env_llm(self) -> LlmConfigRead:
        s = self.settings
        configured = self.env_provider is not None
        return LlmConfigRead(
            id=ENV_DEFAULT_LLM,
            name="Environment default",
            builtin=True,
            provider=self.env_provider.name if self.env_provider else "openai-compatible",
            base_url=s.llm_base_url,
            model=self.env_provider.model if self.env_provider else s.llm_model,
            api_key_env="OLS_LLM_API_KEY" if s.llm_api_key else None,
            api_key_present=bool(s.llm_api_key) if s.llm_api_key else None,
            provider_config={},
            structured_output=s.llm_structured_output,
            temperature=s.llm_temperature,
            timeout_seconds=s.llm_timeout_seconds,
            max_output_tokens=s.llm_max_output_tokens,
            description="Configured on the server with OLS_LLM_BASE_URL and OLS_LLM_MODEL (read-only here).",
            configured=configured,
            enabled=configured,
            last_test=_test(self._builtin_tests.get(ENV_DEFAULT_LLM)),
            used_by_projects=self._projects_using("default_llm_config_id", ENV_DEFAULT_LLM),
        )

    def _llm_read(self, record: LlmConfiguration) -> LlmConfigRead:
        required_key = record.provider in {"openai", "anthropic"} or (
            record.provider == "azure-foundry"
            and (record.provider_config or {}).get("auth_method", "api_key") == "api_key"
        )
        key_available = secret_is_set(record.api_key_env)
        configured = record.enabled and (key_available if required_key or record.api_key_env else True)
        return LlmConfigRead(
            id=record.id,
            name=record.name,
            builtin=False,
            provider=record.provider,
            base_url=record.base_url,
            model=record.model,
            api_key_env=record.api_key_env,
            api_key_present=secret_is_set(record.api_key_env) if record.api_key_env else None,
            provider_config=record.provider_config or {},
            structured_output=record.structured_output,
            temperature=record.temperature,
            timeout_seconds=record.timeout_seconds,
            max_output_tokens=record.max_output_tokens,
            description=record.description,
            configured=configured,
            enabled=record.enabled,
            last_test=_test(record.last_test),
            used_by_projects=sorted({
                *self._projects_using("default_llm_config_id", record.id),
                *self._projects_using("default_discovery_llm_config_id", record.id),
                *self._projects_using("default_kg_llm_config_id", record.id),
            }),
            updated_by=record.updated_by,
            updated_at=record.updated_at,
        )

    def _llm_record(self, config_id: str) -> LlmConfiguration:
        record = self.session.get(LlmConfiguration, config_id)
        if record is None:
            raise NotFoundError(f"LLM configuration '{config_id}' was not found.", code="LLM_CONFIG_NOT_FOUND")
        return record

    def list_llm(self) -> list[LlmConfigRead]:
        records = self.session.scalars(select(LlmConfiguration).order_by(LlmConfiguration.name))
        return [self._env_llm(), *(self._llm_read(r) for r in records)]

    def get_llm(self, config_id: str) -> LlmConfigRead:
        return self._env_llm() if config_id == ENV_DEFAULT_LLM else self._llm_read(self._llm_record(config_id))

    def _normalized_llm_values(self, data: LlmConfigInput) -> dict[str, Any]:
        values = data.model_dump()
        provider = values["provider"]
        base_url = values["base_url"]
        defaults = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "ollama": "http://localhost:11434",
        }
        if not base_url:
            base_url = defaults.get(provider)
        if not base_url:
            raise BusinessRuleError("An endpoint URL is required for this provider.", code="LLM_ENDPOINT_REQUIRED")
        parts = urlsplit(base_url)
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise BusinessRuleError("Enter a valid provider endpoint URL without credentials or query parameters.",
                                    code="LLM_ENDPOINT_INVALID")
        local_ollama = provider == "ollama" and (
            parts.hostname.lower() == "localhost" or parts.hostname.lower().endswith(".localhost")
            or (self._is_ip(parts.hostname) and not ip_address(parts.hostname).is_global)
        )
        if provider != "openai-compatible":
            if parts.scheme != "https" and not local_ollama:
                raise BusinessRuleError("Provider endpoints must use HTTPS; HTTP is only allowed for local Ollama.",
                                        code="LLM_ENDPOINT_INSECURE")
            if self._is_ip(parts.hostname) and not ip_address(parts.hostname).is_global and not local_ollama:
                raise BusinessRuleError("Private and loopback addresses are not allowed for this provider.",
                                        code="LLM_ENDPOINT_UNSAFE")
        config = dict(values.get("provider_config") or {})
        if provider == "azure-foundry":
            deployment = config.get("deployment_type")
            if deployment not in {"azure-openai", "openai-compatible", "anthropic"}:
                raise BusinessRuleError("Select a supported Azure deployment/API type.",
                                        code="AZURE_DEPLOYMENT_TYPE_REQUIRED")
            auth = config.get("auth_method", "api_key")
            if auth not in {"api_key", "entra_id"}:
                raise BusinessRuleError("Azure authentication must be API key or Microsoft Entra ID.",
                                        code="AZURE_AUTH_INVALID")
            config["auth_method"] = auth
            if auth == "api_key" and not values.get("api_key_env"):
                raise BusinessRuleError("Set the environment-variable name holding the Azure API key.",
                                        code="LLM_CREDENTIAL_REQUIRED")
            if deployment == "anthropic" and auth == "entra_id":
                config.setdefault("resource", parts.hostname.split(".")[0])
        elif provider in {"openai", "anthropic"} and not values.get("api_key_env"):
            raise BusinessRuleError("Set the environment-variable name holding the provider API key.",
                                    code="LLM_CREDENTIAL_REQUIRED")
        if provider == "ollama":
            config["inference_parameters"] = dict(config.get("inference_parameters") or {})
        values["base_url"] = base_url.rstrip("/")
        values["provider_config"] = config
        return values

    @staticmethod
    def _is_ip(host: str) -> bool:
        try:
            ip_address(host)
            return True
        except ValueError:
            return False

    def create_llm(self, data: LlmConfigInput, actor: str) -> LlmConfigRead:
        if self._name_taken(LlmConfiguration, data.name):
            raise ConflictError(f"An LLM configuration named '{data.name}' already exists.", code="LLM_CONFIG_NAME_TAKEN")
        record = LlmConfiguration(**self._normalized_llm_values(data), updated_by=actor)
        self.session.add(record)
        self.session.flush()
        _audit(event_type="settings.llm_registered", summary=f"LLM configuration '{record.name}' registered",
                        details={"config_id": record.id, "model": record.model, "actor": actor})
        self.session.commit()
        return self._llm_read(record)

    def update_llm(self, config_id: str, data: LlmConfigInput, actor: str) -> LlmConfigRead:
        if config_id == ENV_DEFAULT_LLM:
            raise BusinessRuleError("The environment default is configured on the server.", code="BUILTIN_READ_ONLY")
        record = self._llm_record(config_id)
        if self._name_taken(LlmConfiguration, data.name, exclude=record.id):
            raise ConflictError(f"An LLM configuration named '{data.name}' already exists.", code="LLM_CONFIG_NAME_TAKEN")
        values = self._normalized_llm_values(data)
        changed = sorted(k for k, v in values.items() if getattr(record, k) != v)
        for key, value in values.items():
            setattr(record, key, value)
        if changed:
            record.last_test = None
            record.updated_by = actor
            _audit(event_type="settings.llm_updated",
                            summary=f"LLM configuration '{record.name}' updated ({', '.join(changed)})",
                            details={"config_id": record.id, "actor": actor})
        self.session.commit()
        return self._llm_read(record)

    def set_llm_enabled(self, config_id: str, enabled: bool, actor: str) -> LlmConfigRead:
        if config_id == ENV_DEFAULT_LLM:
            raise BusinessRuleError("The environment default is configured on the server.", code="BUILTIN_READ_ONLY")
        record = self._llm_record(config_id)
        if record.enabled == enabled:
            return self._llm_read(record)
        if not enabled and self._llm_projects_using(config_id):
            raise ConflictError(
                "Choose another project default before deactivating this configuration.",
                code="LLM_CONFIG_IN_USE",
                details={"projects": self._llm_projects_using(config_id)},
            )
        record.enabled = enabled
        record.last_test = None
        record.updated_by = actor
        _audit(
            event_type="settings.llm_activated" if enabled else "settings.llm_deactivated",
            summary=f"LLM configuration '{record.name}' {'activated' if enabled else 'deactivated'}",
            details={"config_id": record.id, "actor": actor},
        )
        self.session.commit()
        return self._llm_read(record)

    def _llm_projects_using(self, config_id: str) -> list[str]:
        ids = (
            self._projects_using("default_llm_config_id", config_id)
            + self._projects_using("default_discovery_llm_config_id", config_id)
            + self._projects_using("default_kg_llm_config_id", config_id)
        )
        return sorted(set(ids))

    def delete_llm(self, config_id: str, actor: str) -> None:
        if config_id == ENV_DEFAULT_LLM:
            raise BusinessRuleError("The environment default cannot be deleted.", code="BUILTIN_READ_ONLY")
        record = self._llm_record(config_id)
        users = sorted({
            *self._projects_using("default_llm_config_id", config_id),
            *self._projects_using("default_discovery_llm_config_id", config_id),
            *self._projects_using("default_kg_llm_config_id", config_id),
        })
        if users:
            raise ConflictError(
                f"'{record.name}' is the default LLM of {', '.join(users)}. Choose another default first.",
                code="CONFIG_IN_USE",
                details={"projects": users},
            )
        _audit(event_type="settings.llm_deleted", summary=f"LLM configuration '{record.name}' deleted",
                        details={"config_id": record.id, "actor": actor})
        self.session.delete(record)
        self.session.commit()

    def provider_for(self, config_id: str | None) -> LLMProvider | None:
        """The provider for a configuration id; the environment default may be absent (None)."""
        if config_id in (None, ENV_DEFAULT_LLM):
            return self.env_provider
        record = self._llm_record(config_id)
        if not record.enabled:
            raise BusinessRuleError(f"LLM configuration '{record.name}' is deactivated.", code="LLM_CONFIG_DISABLED")
        api_key = get_secret(record.api_key_env)
        required_key = record.provider in {"openai", "anthropic"} or (
            record.provider == "azure-foundry"
            and (record.provider_config or {}).get("auth_method", "api_key") == "api_key"
        )
        if (required_key or record.api_key_env) and not api_key:
            raise BusinessRuleError(
                f"Environment variable {record.api_key_env or '(not configured)'} is not set on the server.",
                code="LLM_CREDENTIAL_MISSING",
            )
        try:
            return build_registered_provider(
                provider=record.provider,
                base_url=record.base_url,
                model=record.model,
                api_key=api_key,
                provider_config=record.provider_config or {},
                structured_output=record.structured_output,
                temperature=record.temperature,
                timeout_seconds=record.timeout_seconds,
                max_output_tokens=record.max_output_tokens,
                max_repair_attempts=self.settings.llm_max_repair_attempts,
            )
        except (ImportError, ValueError) as error:
            raise BusinessRuleError(str(error), code="LLM_CONFIGURATION_INVALID") from error

    def llm_snapshot(self, config_id: str | None) -> dict[str, Any]:
        if config_id in (None, ENV_DEFAULT_LLM):
            return {
                "config_id": ENV_DEFAULT_LLM,
                "provider": self.env_provider.name if self.env_provider else None,
                "model": self.env_provider.model if self.env_provider else None,
                "endpoint": self.settings.llm_base_url,
                "temperature": self.settings.llm_temperature,
                "max_output_tokens": self.settings.llm_max_output_tokens,
                "timeout_seconds": self.settings.llm_timeout_seconds,
            }
        record = self._llm_record(config_id)
        return provider_snapshot(record)

    def test_llm(self, config_id: str) -> LlmConfigRead:
        """Run a provider-native authenticated model access check, only on explicit request."""
        try:
            provider = self.provider_for(config_id)
        except BusinessRuleError as error:
            if error.code not in {"LLM_CREDENTIAL_MISSING", "LLM_CONFIG_DISABLED", "LLM_CONFIGURATION_INVALID"}:
                raise
            provider = None
            configuration_error = str(error)
        else:
            configuration_error = ""
        if provider is None:
            if config_id == ENV_DEFAULT_LLM:
                message = "No LLM is configured on the server (OLS_LLM_BASE_URL, OLS_LLM_MODEL)."
            else:
                message = configuration_error or "The provider is not configured."
            result = ConnectionResult(False, message)
        else:
            started = time.perf_counter()
            reachable, detail, available = provider.check_connection(timeout=10.0)
            result = ConnectionResult(
                reachable and available is not False,
                detail,
                int((time.perf_counter() - started) * 1000),
                {"model_available": available, "model_listed": available},
            )
        if config_id == ENV_DEFAULT_LLM:
            self._builtin_tests[ENV_DEFAULT_LLM] = _stamp(result)
            return self._env_llm()
        record = self._llm_record(config_id)
        record.last_test = _stamp(result)
        self.session.commit()
        return self._llm_read(record)

    # ------------------------------------------------------------------------------ graph connections

    @property
    def _allow_private(self) -> bool:
        return self.settings.graph_allow_private_networks

    def kinds(self) -> list[GraphKindRead]:
        """The provider catalogue: registrable providers in dropdown order, then built-in targets."""
        ordered = [KINDS[i] for i in REGISTRATION_ORDER if i in KINDS]
        ordered += [k for k in KINDS.values() if k.id not in REGISTRATION_ORDER]
        return [self._kind_read(k) for k in ordered]

    @staticmethod
    def _field_read(spec: Any) -> ConfigFieldRead:
        return ConfigFieldRead(
            key=spec.key, label=spec.label, required=spec.required, secret=spec.secret, placeholder=spec.placeholder,
            type=spec.type, default=spec.default, help=spec.help, minimum=spec.minimum, maximum=spec.maximum,
            options=[FieldOptionRead(value=v, label=label) for v, label in spec.options],
            visible_when=(
                VisibleWhenRead(field=spec.visible_when[0], values=list(spec.visible_when[1]))
                if spec.visible_when else None
            ),
        )

    def _kind_read(self, k: TargetKind) -> GraphKindRead:
        return GraphKindRead(
            id=k.id, label=k.label, model=k.model, builtin=k.builtin, registrable=k.registrable, available=k.available,
            description=k.description, unavailable_reason=k.unavailable_reason, protocol=k.protocol,
            connection_supported=k.available, read_supported=k.read_supported,
            deployment_supported=k.deployment_supported, live_tested=k.live_tested,
            verification_note=k.verification_note, fields=[self._field_read(f) for f in k.fields],
        )

    def _deployment_facts(self, target_id: str) -> tuple[int, bool, Any]:
        """(deployments, any verified deployment, latest verified time) recorded for a target."""
        from app.modules.kg.models import KgGraphDeployment

        rows = list(
            self.session.scalars(
                select(KgGraphDeployment).where(
                    KgGraphDeployment.target_id == target_id, KgGraphDeployment.origin != "legacy"
                )
            )
        )
        verified = [r for r in rows if r.status in ("completed", "superseded")]
        latest = max((r.completed_at for r in verified if r.completed_at), default=None)
        return len(rows), bool(verified), latest

    def _graph_view(
        self,
        *,
        connection_id: str,
        name: str,
        builtin: bool,
        kind_id: str,
        config: dict[str, Any],
        secret_env: str | None,
        description: str,
        enabled: bool,
        is_default: bool,
        last_test: dict[str, Any] | None,
        updated_by: str = "",
        updated_at: Any = None,
    ) -> GraphConnectionRead:
        kind = KINDS[kind_id]
        test = _test(last_test)
        connected = bool(test and test.ok)
        internal = kind.family in ("local", "oxigraph")
        writable = is_writable(kind_id, config)
        count, verified, latest = self._deployment_facts(connection_id)
        query_url, update_url = sparql_endpoints(kind_id, config) if kind.family == "sparql" else ("", None)
        return GraphConnectionRead(
            id=connection_id,
            name=name,
            builtin=builtin,
            kind=kind_id,
            provider=kind_id,
            kind_label=kind.label,
            model=kind.model,
            protocol=kind.protocol,
            config=display_config(kind_id, config),
            effective_endpoints=(
                {"query": query_url, "update": update_url} if kind.family == "sparql" else {}
            ),
            secret_env=secret_env,
            secret_present=secret_is_set(secret_env) if secret_env else None,
            description=description,
            enabled=enabled,
            is_default=is_default,
            status="not_tested" if test is None else "connected" if test.ok else "failed",
            capabilities=GraphCapabilities(
                connection_supported=kind.available,
                connected=connected,
                read_supported=kind.read_supported,
                deployment_supported=kind.deployment_supported,
                write_configured=writable,
                deployment_ready=enabled and kind.deployment_supported and writable and (internal or connected),
                deployment_verified=verified,
                live_tested=kind.live_tested,
                verification_note=kind.verification_note,
                last_deployment_at=latest,
            ),
            deployment_count=count,
            last_test=test,
            used_by_projects=self._projects_using("default_graph_connection_id", connection_id),
            updated_by=updated_by,
            updated_at=updated_at,
        )

    def _builtin_graph(self, connection_id: str) -> GraphConnectionRead:
        name, kind_id = BUILTIN_TARGETS[connection_id]
        kind = KINDS[kind_id]
        config = {"path": str(self.settings.oxigraph_dir)} if kind_id == "oxigraph" else {}
        default_row = self.session.scalars(select(GraphConnection.id).where(GraphConnection.is_default.is_(True))).first()
        return self._graph_view(
            connection_id=connection_id, name=name, builtin=True, kind_id=kind_id, config=config, secret_env=None,
            description=kind.description, enabled=True,
            is_default=connection_id == LOCAL_SQL and default_row is None,
            last_test=self._builtin_tests.get(connection_id),
        )

    def _graph_read(self, record: GraphConnection) -> GraphConnectionRead:
        return self._graph_view(
            connection_id=record.id, name=record.name, builtin=False, kind_id=record.kind,
            config=dict(record.config or {}), secret_env=record.secret_env, description=record.description,
            enabled=record.enabled, is_default=record.is_default, last_test=record.last_test,
            updated_by=record.updated_by, updated_at=record.updated_at,
        )

    def _graph_record(self, connection_id: str) -> GraphConnection:
        record = self.session.get(GraphConnection, connection_id)
        if record is None:
            raise NotFoundError(f"Graph connection '{connection_id}' was not found.", code="GRAPH_CONNECTION_NOT_FOUND")
        return record

    def list_graph(self) -> list[GraphConnectionRead]:
        records = self.session.scalars(select(GraphConnection).order_by(GraphConnection.name))
        return [*(self._builtin_graph(i) for i in BUILTIN_TARGETS), *(self._graph_read(r) for r in records)]

    def get_graph(self, connection_id: str) -> GraphConnectionRead:
        if connection_id in BUILTIN_TARGETS:
            return self._builtin_graph(connection_id)
        return self._graph_read(self._graph_record(connection_id))

    def workspace_default_graph_id(self) -> str:
        """The graph database preselected for new projects: the registered default, else the local SQL graph."""
        record = self.session.scalars(
            select(GraphConnection).where(GraphConnection.is_default.is_(True), GraphConnection.enabled.is_(True))
        ).first()
        return record.id if record is not None else LOCAL_SQL

    def _normalized_graph_values(self, data: GraphConnectionInput) -> tuple[dict[str, str], str | None]:
        return normalize_config(data.kind, dict(data.config), data.secret_env, allow_private=self._allow_private)

    def create_graph(self, data: GraphConnectionInput, actor: str) -> GraphConnectionRead:
        config, secret_env = self._normalized_graph_values(data)
        if self._name_taken(GraphConnection, data.name) or data.name in {n for n, _ in BUILTIN_TARGETS.values()}:
            raise ConflictError(f"A graph connection named '{data.name}' already exists.", code="GRAPH_CONNECTION_NAME_TAKEN")
        record = GraphConnection(
            name=data.name, kind=data.kind, config=config, secret_env=secret_env, description=data.description,
            data_model=KINDS[data.kind].model, enabled=data.enabled, is_default=False, updated_by=actor,
        )
        self.session.add(record)
        self.session.flush()
        _audit(event_type="settings.graph_registered",
                        summary=f"Graph connection '{record.name}' ({KINDS[record.kind].label}) registered",
                        details={"connection_id": record.id, "actor": actor})
        self.session.commit()
        return self._graph_read(record)

    def update_graph(self, connection_id: str, data: GraphConnectionInput, actor: str) -> GraphConnectionRead:
        if connection_id in BUILTIN_TARGETS:
            raise BusinessRuleError("Built-in graph targets cannot be edited.", code="BUILTIN_READ_ONLY")
        record = self._graph_record(connection_id)
        if data.kind != record.kind:
            raise BusinessRuleError("The kind of a registered connection cannot change; register a new one.",
                                    code="GRAPH_KIND_IMMUTABLE")
        config, secret_env = self._normalized_graph_values(data)
        if self._name_taken(GraphConnection, data.name, exclude=record.id):
            raise ConflictError(f"A graph connection named '{data.name}' already exists.", code="GRAPH_CONNECTION_NAME_TAKEN")
        if not data.enabled and record.enabled:
            self._require_disable_allowed(record)
        connection_changed = (record.config, record.secret_env) != (config, secret_env)
        changed = connection_changed or (record.name, record.description, record.enabled) != (
            data.name, data.description, data.enabled)
        record.name, record.config, record.secret_env, record.description = data.name, config, secret_env, data.description
        record.enabled = data.enabled
        if not data.enabled:
            record.is_default = False
        if connection_changed:
            record.last_test = None  # a changed endpoint or credential must be tested again
        if changed:
            record.updated_by = actor
            _audit(event_type="settings.graph_updated",
                            summary=f"Graph connection '{record.name}' updated", details={"connection_id": record.id, "actor": actor})
        self.session.commit()
        return self._graph_read(record)

    def _require_disable_allowed(self, record: GraphConnection) -> None:
        users = self._projects_using("default_graph_connection_id", record.id)
        if users:
            raise ConflictError(
                f"'{record.name}' is the default graph target of {', '.join(users)}. Choose another default first.",
                code="CONFIG_IN_USE",
                details={"projects": users},
            )

    def set_graph_enabled(self, connection_id: str, enabled: bool, actor: str) -> GraphConnectionRead:
        """Disabling stops new deployments and selection; historical deployments stay readable."""
        if connection_id in BUILTIN_TARGETS:
            raise BusinessRuleError("Built-in graph targets are always enabled.", code="BUILTIN_READ_ONLY")
        record = self._graph_record(connection_id)
        if record.enabled == enabled:
            return self._graph_read(record)
        if not enabled:
            self._require_disable_allowed(record)
            record.is_default = False
        record.enabled = enabled
        record.updated_by = actor
        _audit(event_type="settings.graph_enabled" if enabled else "settings.graph_disabled",
               summary=f"Graph connection '{record.name}' {'enabled' if enabled else 'disabled'}",
               details={"connection_id": record.id, "actor": actor})
        self.session.commit()
        return self._graph_read(record)

    def set_default_graph(self, connection_id: str, actor: str) -> GraphConnectionRead:
        """Choose the graph database preselected for new projects. The local SQL graph is the implicit default."""
        if connection_id == OXIGRAPH_EMBEDDED:
            raise BusinessRuleError(
                "The embedded store cannot be the workspace default; select it for a project instead.",
                code="GRAPH_DEFAULT_UNSUPPORTED",
            )
        for other in self.session.scalars(select(GraphConnection).where(GraphConnection.is_default.is_(True))):
            other.is_default = False
        if connection_id != LOCAL_SQL:
            record = self._graph_record(connection_id)
            if not record.enabled:
                raise BusinessRuleError("Enable this graph database before making it the default.", code="GRAPH_CONNECTION_DISABLED")
            if not is_writable(record.kind, record.config or {}):
                raise BusinessRuleError(
                    "A read-only connection cannot be the default: it cannot receive deployments.",
                    code="GRAPH_DEFAULT_NOT_WRITABLE",
                )
            record.is_default = True
            record.updated_by = actor
        _audit(event_type="settings.graph_default", summary=f"Default graph database set to {connection_id}",
               details={"connection_id": connection_id, "actor": actor})
        self.session.commit()
        return self.get_graph(connection_id)

    def delete_graph(self, connection_id: str, actor: str) -> None:
        if connection_id in BUILTIN_TARGETS:
            raise BusinessRuleError("Built-in graph targets cannot be deleted.", code="BUILTIN_READ_ONLY")
        record = self._graph_record(connection_id)
        users = self._projects_using("default_graph_connection_id", connection_id)
        if users:
            raise ConflictError(
                f"'{record.name}' is the default graph target of {', '.join(users)}. Choose another default first.",
                code="CONFIG_IN_USE",
                details={"projects": users},
            )
        _audit(event_type="settings.graph_deleted", summary=f"Graph connection '{record.name}' deleted",
                        details={"connection_id": record.id, "actor": actor})
        self.session.delete(record)
        self.session.commit()

    def probe_graph(self, kind_id: str, config: dict[str, Any], secret_env: str | None) -> ConnectionResult:
        """Run the provider's read-only connection test. Nothing here creates, changes or deletes graph data."""
        kind = KINDS[kind_id]
        try:
            if kind.family == "local":
                return check_local_sql(self.session)
            if kind.family == "oxigraph":
                return check_oxigraph(self.settings.oxigraph_dir)
            if kind.family == "sparql":
                return check_sparql(kind_id, config, secret_env, allow_private=self._allow_private)
            if kind.family == "neo4j":
                from app.modules.graph.targets.neo4j_store import check_neo4j

                return check_neo4j(config, secret_env, allow_private=self._allow_private)
            if kind.family == "gremlin":
                from app.modules.graph.targets.gremlin_store import check_cosmos

                return check_cosmos(config, secret_env, allow_private=self._allow_private)
        except ImportError:
            return ConnectionResult(False, f"The driver for {kind.label} is not installed on the server.")
        return ConnectionResult(False, f"No connection test exists for {kind.label}.")

    def test_graph(self, connection_id: str) -> GraphConnectionRead:
        if connection_id in BUILTIN_TARGETS:
            kind_id = BUILTIN_TARGETS[connection_id][1]
            self._builtin_tests[connection_id] = _stamp(self.probe_graph(kind_id, {}, None))
            return self._builtin_graph(connection_id)
        record = self._graph_record(connection_id)
        record.last_test = _stamp(self.probe_graph(record.kind, dict(record.config or {}), record.secret_env))
        self.session.commit()
        return self._graph_read(record)

    # ------------------------------------------------------------------------------ projects

    def require_llm_id(self, config_id: str | None) -> None:
        if config_id and config_id != ENV_DEFAULT_LLM:
            record = self._llm_record(config_id)
            if not record.enabled:
                raise BusinessRuleError(f"LLM configuration '{record.name}' is deactivated.", code="LLM_CONFIG_DISABLED")
            required_key = record.provider in {"openai", "anthropic"} or (
                record.provider == "azure-foundry"
                and (record.provider_config or {}).get("auth_method", "api_key") == "api_key"
            )
            if required_key and not secret_is_set(record.api_key_env):
                raise BusinessRuleError(
                    f"Configure environment variable {record.api_key_env or '(credential reference required)'} "
                    "before selecting this LLM.",
                    code="LLM_CREDENTIAL_MISSING",
                )

    def require_graph_id(self, connection_id: str | None) -> None:
        """A graph database selectable for a project or build must exist and be enabled."""
        if connection_id and connection_id not in BUILTIN_TARGETS:
            record = self._graph_record(connection_id)
            if not record.enabled:
                raise BusinessRuleError(
                    f"Graph database '{record.name}' is disabled. Enable it in Settings first.",
                    code="GRAPH_CONNECTION_DISABLED",
                )

    def effective_llm_id(self, project_id: str, requested: str | None = None) -> str:
        if requested:
            return requested
        project = self._require_project(project_id)
        return project.default_discovery_llm_config_id or project.default_llm_config_id or ENV_DEFAULT_LLM

    def effective_kg_llm_id(self, project_id: str, requested: str | None = None) -> str:
        if requested:
            return requested
        project = self._require_project(project_id)
        return project.default_kg_llm_config_id or project.default_llm_config_id or ENV_DEFAULT_LLM

    def effective_graph_id(self, project_id: str, requested: str | None = None) -> str:
        if requested:
            return requested
        project = self._require_project(project_id)
        return project.default_graph_connection_id or LOCAL_SQL

    def project_defaults(self, project_id: str) -> ProjectDefaults:
        project = self._require_project(project_id)
        discovery_id = project.default_discovery_llm_config_id or project.default_llm_config_id or ENV_DEFAULT_LLM
        kg_id = project.default_kg_llm_config_id or project.default_llm_config_id or ENV_DEFAULT_LLM
        graph_id = project.default_graph_connection_id or LOCAL_SQL
        return ProjectDefaults(
            project_id=project.id,
            default_llm_config_id=discovery_id,
            default_discovery_llm_config_id=discovery_id,
            default_kg_llm_config_id=kg_id,
            default_graph_connection_id=graph_id,
            data_namespace=project.data_namespace,
            effective_llm=self.get_llm(discovery_id),
            effective_discovery_llm=self.get_llm(discovery_id),
            effective_kg_llm=self.get_llm(kg_id),
            effective_graph=self.get_graph(graph_id),
        )

    def update_project_defaults(self, project_id: str, data: ProjectDefaultsUpdate, actor: str) -> ProjectDefaults:
        project = self._require_project(project_id)
        values = data.model_dump(exclude_unset=True)
        if "default_llm_config_id" in values:
            self.require_llm_id(values["default_llm_config_id"])
            value = None if values["default_llm_config_id"] in (None, ENV_DEFAULT_LLM) else values["default_llm_config_id"]
            values["default_llm_config_id"] = value
            values.setdefault("default_discovery_llm_config_id", value)
            values.setdefault("default_kg_llm_config_id", value)
        for field in ("default_discovery_llm_config_id", "default_kg_llm_config_id"):
            if field in values:
                self.require_llm_id(values[field])
                values[field] = None if values[field] in (None, ENV_DEFAULT_LLM) else values[field]
        if "default_discovery_llm_config_id" in values:
            values["default_llm_config_id"] = values["default_discovery_llm_config_id"]
        if "default_graph_connection_id" in values:
            self.require_graph_id(values["default_graph_connection_id"])
            values["default_graph_connection_id"] = None if values["default_graph_connection_id"] in (None, LOCAL_SQL) else values["default_graph_connection_id"]
        if "data_namespace" in values:
            namespace = (values["data_namespace"] or "").strip()
            if namespace and (not namespace.startswith(("http://", "https://", "urn:")) or not namespace.endswith(("/", "#", ":"))):
                raise BusinessRuleError(
                    "The data namespace must be an absolute IRI ending with '/', '#' or ':'.", code="DATA_NAMESPACE_INVALID"
                )
            values["data_namespace"] = namespace or None
        changed = sorted(k for k, v in values.items() if getattr(project, k) != v)
        for key, value in values.items():
            setattr(project, key, value)
        if changed:
            record_activity(self.session, project_id=project.id, event_type="project.defaults_updated",
                            summary=f"Project defaults updated ({', '.join(changed)})", details={"actor": actor, **values})
        self.session.commit()
        return self.project_defaults(project_id)
