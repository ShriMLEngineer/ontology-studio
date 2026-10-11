"""Settings use cases: LLM configurations, graph connections, project defaults and resolution.

Built-ins are virtual (not rows): the *environment default* LLM (``OLS_LLM_*``), the local SQL
property graph and the embedded Oxigraph store. Registered configurations reference secrets by
environment-variable name only; values are read when a connection is opened or tested.
"""

import logging
import os
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import utcnow
from app.modules.activity.service import record_activity
from app.modules.graph.targets import (
    BUILTIN_TARGETS,
    KINDS,
    ConnectionResult,
    check_local_sql,
    check_oxigraph,
    check_sparql_http,
)
from app.modules.llm.openai_compatible import OpenAICompatibleProvider
from app.modules.llm.provider import LLMProvider
from app.modules.projects.models import Project
from app.modules.settings.models import GraphConnection, LlmConfiguration
from app.modules.settings.schemas import (
    ConfigFieldRead,
    ConnectionTest,
    GraphConnectionInput,
    GraphConnectionRead,
    GraphKindRead,
    LlmConfigInput,
    LlmConfigRead,
    ProjectDefaults,
    ProjectDefaultsUpdate,
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
            structured_output=s.llm_structured_output,
            temperature=s.llm_temperature,
            timeout_seconds=s.llm_timeout_seconds,
            max_output_tokens=s.llm_max_output_tokens,
            description="Configured on the server with OLS_LLM_BASE_URL and OLS_LLM_MODEL (read-only here).",
            configured=configured,
            last_test=_test(self._builtin_tests.get(ENV_DEFAULT_LLM)),
            used_by_projects=self._projects_using("default_llm_config_id", ENV_DEFAULT_LLM),
        )

    def _llm_read(self, record: LlmConfiguration) -> LlmConfigRead:
        return LlmConfigRead(
            id=record.id,
            name=record.name,
            builtin=False,
            provider=record.provider,
            base_url=record.base_url,
            model=record.model,
            api_key_env=record.api_key_env,
            api_key_present=(record.api_key_env in os.environ) if record.api_key_env else None,
            structured_output=record.structured_output,
            temperature=record.temperature,
            timeout_seconds=record.timeout_seconds,
            max_output_tokens=record.max_output_tokens,
            description=record.description,
            configured=True,
            last_test=_test(record.last_test),
            used_by_projects=self._projects_using("default_llm_config_id", record.id),
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

    def create_llm(self, data: LlmConfigInput, actor: str) -> LlmConfigRead:
        if self._name_taken(LlmConfiguration, data.name):
            raise ConflictError(f"An LLM configuration named '{data.name}' already exists.", code="LLM_CONFIG_NAME_TAKEN")
        record = LlmConfiguration(**data.model_dump(), updated_by=actor)
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
        values = data.model_dump()
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

    def delete_llm(self, config_id: str, actor: str) -> None:
        if config_id == ENV_DEFAULT_LLM:
            raise BusinessRuleError("The environment default cannot be deleted.", code="BUILTIN_READ_ONLY")
        record = self._llm_record(config_id)
        users = self._projects_using("default_llm_config_id", config_id)
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
        api_key = os.environ.get(record.api_key_env) if record.api_key_env else None
        return OpenAICompatibleProvider(
            base_url=record.base_url,
            model=record.model,
            api_key=api_key,
            structured_output=record.structured_output,  # type: ignore[arg-type]
            temperature=record.temperature,
            timeout_seconds=record.timeout_seconds,
            max_output_tokens=record.max_output_tokens,
            max_repair_attempts=self.settings.llm_max_repair_attempts,
        )

    def test_llm(self, config_id: str) -> LlmConfigRead:
        """Real connection test against the OpenAI-compatible /models API (no completion is requested)."""
        provider = self.provider_for(config_id)
        if provider is None:
            result = ConnectionResult(False, "No LLM is configured on the server (OLS_LLM_BASE_URL, OLS_LLM_MODEL).")
        elif not isinstance(provider, OpenAICompatibleProvider):
            result = ConnectionResult(True, f"Configured provider '{provider.name}' does not support a connection probe.")
        else:
            record = None if config_id == ENV_DEFAULT_LLM else self._llm_record(config_id)
            if record is not None and record.api_key_env and record.api_key_env not in os.environ:
                result = ConnectionResult(False, f"Environment variable {record.api_key_env} is not set on the server.")
            else:
                started = time.perf_counter()
                reachable, detail, available = provider.check_connection(timeout=10.0)
                ok = reachable and available is not False
                result = ConnectionResult(ok, detail, int((time.perf_counter() - started) * 1000), {"model_listed": available})
        if config_id == ENV_DEFAULT_LLM:
            self._builtin_tests[ENV_DEFAULT_LLM] = _stamp(result)
            return self._env_llm()
        record = self._llm_record(config_id)
        record.last_test = _stamp(result)
        self.session.commit()
        return self._llm_read(record)

    # ------------------------------------------------------------------------------ graph connections

    def kinds(self) -> list[GraphKindRead]:
        return [
            GraphKindRead(
                id=k.id,
                label=k.label,
                model=k.model,
                builtin=k.builtin,
                registrable=k.registrable,
                available=k.available,
                description=k.description,
                unavailable_reason=k.unavailable_reason,
                fields=[ConfigFieldRead(**f.__dict__) for f in k.fields],
            )
            for k in KINDS.values()
        ]

    def _builtin_graph(self, connection_id: str) -> GraphConnectionRead:
        name, kind_id = BUILTIN_TARGETS[connection_id]
        kind = KINDS[kind_id]
        config = {"path": str(self.settings.oxigraph_dir)} if kind_id == "oxigraph" else {}
        return GraphConnectionRead(
            id=connection_id,
            name=name,
            builtin=True,
            kind=kind_id,
            kind_label=kind.label,
            model=kind.model,
            config=config,
            secret_env=None,
            secret_present=None,
            description=kind.description,
            last_test=_test(self._builtin_tests.get(connection_id)),
            used_by_projects=self._projects_using("default_graph_connection_id", connection_id),
        )

    def _graph_read(self, record: GraphConnection) -> GraphConnectionRead:
        kind = KINDS[record.kind]
        return GraphConnectionRead(
            id=record.id,
            name=record.name,
            builtin=False,
            kind=record.kind,
            kind_label=kind.label,
            model=kind.model,
            config=dict(record.config or {}),
            secret_env=record.secret_env,
            secret_present=(record.secret_env in os.environ) if record.secret_env else None,
            description=record.description,
            last_test=_test(record.last_test),
            used_by_projects=self._projects_using("default_graph_connection_id", record.id),
            updated_by=record.updated_by,
            updated_at=record.updated_at,
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

    def _validate_graph_input(self, data: GraphConnectionInput) -> dict[str, str]:
        kind = KINDS.get(data.kind)
        if kind is None:
            raise BusinessRuleError(f"Unknown graph database kind '{data.kind}'.", code="GRAPH_KIND_UNKNOWN")
        if not kind.registrable:
            reason = kind.unavailable_reason or "Built-in targets are always available and cannot be registered again."
            raise BusinessRuleError(f"{kind.label} cannot be registered: {reason}", code="GRAPH_KIND_NOT_AVAILABLE")
        allowed = {f.key for f in kind.fields if not f.secret}
        unknown = sorted(set(data.config) - allowed)
        if unknown:
            raise BusinessRuleError(f"Unknown configuration fields for {kind.label}: {', '.join(unknown)}.",
                                    code="GRAPH_CONFIG_INVALID")
        missing = [f.label for f in kind.fields if f.required and not f.secret and not data.config.get(f.key)]
        if missing:
            raise BusinessRuleError(f"Required: {', '.join(missing)}.", code="GRAPH_CONFIG_INVALID")
        for key in ("query_url", "update_url"):
            value = data.config.get(key)
            if value and not value.startswith(("http://", "https://")):
                raise BusinessRuleError(f"{key} must start with http:// or https://.", code="GRAPH_CONFIG_INVALID")
        return {k: v for k, v in data.config.items() if v}

    def create_graph(self, data: GraphConnectionInput, actor: str) -> GraphConnectionRead:
        config = self._validate_graph_input(data)
        if self._name_taken(GraphConnection, data.name) or data.name in {n for n, _ in BUILTIN_TARGETS.values()}:
            raise ConflictError(f"A graph connection named '{data.name}' already exists.", code="GRAPH_CONNECTION_NAME_TAKEN")
        record = GraphConnection(name=data.name, kind=data.kind, config=config, secret_env=data.secret_env,
                                 description=data.description, updated_by=actor)
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
        config = self._validate_graph_input(data)
        if self._name_taken(GraphConnection, data.name, exclude=record.id):
            raise ConflictError(f"A graph connection named '{data.name}' already exists.", code="GRAPH_CONNECTION_NAME_TAKEN")
        changed = (record.name, record.config, record.secret_env, record.description) != (
            data.name, config, data.secret_env, data.description)
        record.name, record.config, record.secret_env, record.description = data.name, config, data.secret_env, data.description
        if changed:
            record.last_test = None
            record.updated_by = actor
            _audit(event_type="settings.graph_updated",
                            summary=f"Graph connection '{record.name}' updated", details={"connection_id": record.id, "actor": actor})
        self.session.commit()
        return self._graph_read(record)

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

    def test_graph(self, connection_id: str) -> GraphConnectionRead:
        if connection_id == LOCAL_SQL:
            self._builtin_tests[connection_id] = _stamp(check_local_sql(self.session))
            return self._builtin_graph(connection_id)
        if connection_id == OXIGRAPH_EMBEDDED:
            self._builtin_tests[connection_id] = _stamp(check_oxigraph(self.settings.oxigraph_dir))
            return self._builtin_graph(connection_id)
        record = self._graph_record(connection_id)
        if record.kind == "sparql-http":
            result = check_sparql_http(record.config or {}, record.secret_env)
        else:  # pragma: no cover - only available kinds can be registered
            result = ConnectionResult(False, f"No adapter for {record.kind}.")
        record.last_test = _stamp(result)
        self.session.commit()
        return self._graph_read(record)

    # ------------------------------------------------------------------------------ projects

    def require_llm_id(self, config_id: str | None) -> None:
        if config_id and config_id != ENV_DEFAULT_LLM:
            self._llm_record(config_id)

    def require_graph_id(self, connection_id: str | None) -> None:
        if connection_id and connection_id not in BUILTIN_TARGETS:
            self._graph_record(connection_id)

    def effective_llm_id(self, project_id: str, requested: str | None = None) -> str:
        if requested:
            return requested
        project = self._require_project(project_id)
        return project.default_llm_config_id or ENV_DEFAULT_LLM

    def effective_graph_id(self, project_id: str, requested: str | None = None) -> str:
        if requested:
            return requested
        project = self._require_project(project_id)
        return project.default_graph_connection_id or LOCAL_SQL

    def project_defaults(self, project_id: str) -> ProjectDefaults:
        project = self._require_project(project_id)
        llm_id = project.default_llm_config_id or ENV_DEFAULT_LLM
        graph_id = project.default_graph_connection_id or LOCAL_SQL
        return ProjectDefaults(
            project_id=project.id,
            default_llm_config_id=llm_id,
            default_graph_connection_id=graph_id,
            data_namespace=project.data_namespace,
            effective_llm=self.get_llm(llm_id),
            effective_graph=self.get_graph(graph_id),
        )

    def update_project_defaults(self, project_id: str, data: ProjectDefaultsUpdate, actor: str) -> ProjectDefaults:
        project = self._require_project(project_id)
        values = data.model_dump(exclude_unset=True)
        if "default_llm_config_id" in values:
            self.require_llm_id(values["default_llm_config_id"])
            values["default_llm_config_id"] = None if values["default_llm_config_id"] in (None, ENV_DEFAULT_LLM) else values["default_llm_config_id"]
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
