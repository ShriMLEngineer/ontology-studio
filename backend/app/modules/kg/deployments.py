"""Graph deployments of knowledge-graph builds (Phase 4.4).

The canonical graph of a build is always the local SQL property graph written by the build. A
*deployment* writes the same accepted facts, through a versioned mapping profile, to a graph
database target (embedded Oxigraph or any SPARQL 1.1 endpoint), verifies what the target holds
afterwards and records the outcome together with the compatibility report. Builds deploy to
their selected target automatically; completed builds can be deployed again at any time.
"""

import logging
import time
from pathlib import Path
from threading import Lock
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import utcnow
from app.core.secrets import get_secret
from app.modules.graph.capabilities import (
    MAPPING_PROFILES,
    PROFILES,
    CapabilityProfile,
    MappingProfile,
    default_mapping_profile,
)
from app.modules.graph.compatibility import CompatibilityReport, analyze
from app.modules.graph.memory_store import MemoryGraphStore
from app.modules.graph.projection import (
    PropertyGraphProjection,
    project_property_graph,
    project_rdf,
)
from app.modules.graph.rdf_reader import ReadStats, read_rdf_projection
from app.modules.graph.sparql import SparqlResult, check_read_only
from app.modules.graph.store import GraphStore
from app.modules.graph.targets import KINDS
from app.modules.graph.targets.adapters import (
    DeploymentError,
    TargetSpec,
    property_graph_adapter,
    rdf_adapter,
)
from app.modules.graph.targets.property_graph import PropertyTarget, property_graph_store
from app.modules.kg.models import KgBuild, KgCandidateFact, KgEntity, KgGraphDeployment
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.schemas import (
    CapabilityProfileRead,
    CompatibilityRead,
    DeploymentCreate,
    DeploymentRead,
    GraphCapabilitiesRead,
    MappingProfileRead,
    SparqlQueryRequest,
)
from app.modules.kg.validation import ACCEPTED
from app.modules.registry.models import OntologyVersion
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.semantics.owl import ontology_iri_of
from app.modules.settings.service import SettingsService

def view_of(version: OntologyVersion) -> OntologyView:
    # Same as kg.service.view_of; imported there by the orchestrator, so not imported from it here.
    return OntologyView(OntologySnapshot.model_validate(version.snapshot), version_id=version.id, version=version.version)


LOCAL_SQL_SPEC = TargetSpec(id="local-sql", name="Local SQL property graph", kind="local-sql")
READ_CACHE_SECONDS = 15.0

logger = logging.getLogger(__name__)

_read_cache: dict[str, tuple[float, MemoryGraphStore, ReadStats]] = {}
_read_cache_lock = Lock()


def load_projection(session: Session, build: KgBuild) -> tuple[OntologySnapshot, PropertyGraphProjection]:
    version = session.get(OntologyVersion, build.ontology_version_id)
    assert version is not None
    view = view_of(version)
    facts = session.scalars(
        select(KgCandidateFact)
        .where(KgCandidateFact.build_id == build.id, KgCandidateFact.status == ACCEPTED)
        .order_by(KgCandidateFact.sequence)
    )
    entities = {e.id: e for e in session.scalars(select(KgEntity).where(KgEntity.build_id == build.id))}
    return view.snapshot, project_property_graph(view, facts, entities)


def data_namespace_of(build: KgBuild, snapshot: OntologySnapshot) -> str:
    """The namespace frozen on the build; builds that predate it use the derivation the build would have used."""
    return (build.config_snapshot or {}).get("data_namespace") or f"{ontology_iri_of(snapshot.with_iris())}/data/"


def resolve_mapping(profile: CapabilityProfile, mapping_id: str | None) -> MappingProfile:
    if not mapping_id:
        return default_mapping_profile(profile.data_model)
    mapping = MAPPING_PROFILES.get(mapping_id)
    if mapping is None:
        raise BusinessRuleError(f"Unknown mapping profile '{mapping_id}'.", code="MAPPING_PROFILE_UNKNOWN")
    if mapping.data_model != profile.data_model:
        raise BusinessRuleError(
            f"Mapping profile {mapping.id} produces a {mapping.data_model} graph; {profile.label} stores {profile.data_model}.",
            code="MAPPING_PROFILE_INCOMPATIBLE",
        )
    return mapping


def require_profile(kind: str) -> CapabilityProfile:
    profile = PROFILES.get(kind)
    if profile is None:
        raise BusinessRuleError(f"No capability profile for target kind '{kind}'.", code="GRAPH_KIND_UNKNOWN")
    return profile


def _invalidate(build_id: str) -> None:
    with _read_cache_lock:
        for key in [k for k in _read_cache if k.startswith(f"{build_id}|")]:
            _read_cache.pop(key, None)


def deploy(
    session: Session,
    *,
    build: KgBuild,
    spec: TargetSpec,
    snapshot: OntologySnapshot,
    projection: PropertyGraphProjection,
    data_namespace: str,
    oxigraph_dir: Path,
    sql_store: GraphStore,
    mapping_id: str | None = None,
    origin: str = "manual",
    requested_by: str = "",
    acknowledged_loss_by: str | None = None,
) -> KgGraphDeployment:
    """Deploy, verify and record. Target failures are recorded on the deployment (status ``failed``),
    configuration errors (unknown kind, incompatible profile, unacknowledged semantic loss) raise."""
    kind = KINDS.get(spec.kind)
    profile = require_profile(spec.kind)
    if kind is None or not kind.available or not kind.deployment_supported:
        reason = kind.unavailable_reason if kind and kind.unavailable_reason else "the provider adapter cannot write graphs"
        raise BusinessRuleError(f"{profile.label} has no deployment adapter: {reason}", code="GRAPH_KIND_NOT_AVAILABLE")
    mapping = resolve_mapping(profile, mapping_id)
    report = analyze(snapshot, projection, profile, mapping)
    if report.has_semantic_loss and not acknowledged_loss_by:
        raise BusinessRuleError(
            f"Deploying to {spec.name} loses semantics ({report.summary}) and must be acknowledged.",
            code="SEMANTIC_LOSS_NOT_ACKNOWLEDGED",
            details={"compatibility": report.model_dump(mode="json")},
        )
    row = KgGraphDeployment(
        build_id=build.id,
        project_id=build.project_id,
        target_id=spec.id,
        target_name=spec.name,
        target_kind=spec.kind,
        data_model=profile.data_model,
        mapping_profile=mapping.id,
        capability_profile=f"{profile.id}/{profile.version}",
        data_namespace=data_namespace if profile.data_model == "rdf" else None,
        graphs={},
        compatibility=report.model_dump(mode="json"),
        acknowledged_loss_by=acknowledged_loss_by if report.has_semantic_loss else None,
        status="running",
        stats={},
        origin=origin,
        requested_by=requested_by,
        target_snapshot=snapshot_of(spec),
    )
    session.add(row)
    session.flush()
    started = time.perf_counter()
    stats: dict[str, Any] = {"vertices": len(projection.vertices), "edges": len(projection.edges)}
    try:
        if profile.data_model == "rdf":
            rdf = project_rdf(projection, snapshot, data_namespace, build.id)
            result = rdf_adapter(spec, oxigraph_dir).deploy_rdf(rdf, include_ontology=mapping.include_ontology)
            stats["triples"] = sum(result.expected.values())
        else:
            result = property_graph_adapter(spec, sql_store).deploy_property_graph(build.id, projection)
    except DeploymentError as error:
        row.status, row.error = "failed", redact(str(error), spec)
    except Exception as error:  # noqa: BLE001 - recorded on the deployment; the canonical graph is unaffected
        logger.exception("Deployment %s to %s failed", row.id, spec.name)
        row.status = "failed"
        row.error = redact(f"Unexpected error: {error.__class__.__name__}: {error}", spec)[:2000]
    else:
        row.graphs = result.graphs
        stats.update(expected=result.expected, verified=result.verified)
        if result.ok:
            row.status = "completed"
        else:
            row.status = "failed"
            row.error = f"Verification failed: expected {result.expected}, the target holds {result.verified}."
    stats["duration_ms"] = int((time.perf_counter() - started) * 1000)
    row.stats = stats
    row.completed_at = utcnow()
    if row.status == "completed":
        for previous in session.scalars(
            select(KgGraphDeployment).where(
                KgGraphDeployment.build_id == build.id,
                KgGraphDeployment.target_id == spec.id,
                KgGraphDeployment.status == "completed",
                KgGraphDeployment.id != row.id,
            )
        ):
            previous.status = "superseded"
    _invalidate(build.id)
    return row


def spec_from_snapshot(target: dict[str, Any], allow_private: bool = True) -> TargetSpec:
    return TargetSpec(
        id=target["id"], name=target.get("name", target["id"]), kind=target["kind"],
        config=dict(target.get("config") or {}), secret_env=target.get("secret_env"),
        allow_private=allow_private,
    )


def snapshot_of(spec: TargetSpec) -> dict[str, Any] | None:
    """Non-secret connection settings recorded with a deployment (the credential is referenced by name only)."""
    if spec.kind in ("local-sql", "oxigraph") and not spec.config:
        return None
    return {"provider": spec.kind, "config": dict(spec.config), "secret_env": spec.secret_env}


def redact(message: str, spec: TargetSpec) -> str:
    """Remove the credential value, should a driver or server echo it, from a message that is persisted."""
    secret = get_secret(spec.secret_env)
    return message.replace(secret, "***") if secret and len(secret) >= 4 else message


class _GuardedStore:
    """Wraps an external graph store so read failures surface as API errors, not server errors."""

    def __init__(self, store: Any, target_name: str) -> None:
        self._store = store
        self._target = target_name

    def __getattr__(self, attribute: str) -> Any:
        value = getattr(self._store, attribute)
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return value(*args, **kwargs)
            except DeploymentError as error:
                raise ConflictError(
                    f"Could not read the deployment from {self._target}: {error}", code="GRAPH_TARGET_UNREACHABLE"
                ) from error

        return call


class KgDeploymentService:
    def __init__(
        self, session: Session, settings: Settings, settings_service: SettingsService, sql_store: GraphStore
    ) -> None:
        self.session = session
        self.settings = settings
        self.settings_service = settings_service
        self.sql_store = sql_store

    # ------------------------------------------------------------------ lookups

    def _build(self, build_id: str) -> KgBuild:
        build = self.session.get(KgBuild, build_id)
        if build is None:
            raise NotFoundError(f"Knowledge graph build '{build_id}' was not found.", code="KG_BUILD_NOT_FOUND")
        return build

    def _completed(self, build_id: str) -> KgBuild:
        build = self._build(build_id)
        if build.status != "completed":
            raise ConflictError(
                f"Build #{build.number} is {build.status}; only completed builds can be deployed.", code="KG_BUILD_NOT_COMPLETED"
            )
        return build

    def _deployment(self, deployment_id: str) -> KgGraphDeployment:
        row = self.session.get(KgGraphDeployment, deployment_id)
        if row is None:
            raise NotFoundError(f"Deployment '{deployment_id}' was not found.", code="DEPLOYMENT_NOT_FOUND")
        return row

    def _spec(self, target_id: str) -> TargetSpec:
        target = self.settings_service.get_graph(target_id)
        return TargetSpec(id=target.id, name=target.name, kind=target.kind, config=dict(target.config),
                          secret_env=target.secret_env, allow_private=self.settings.graph_allow_private_networks)

    def _write_spec(self, target_id: str) -> TargetSpec:
        """A target that can receive a new deployment: it must exist and be enabled."""
        self.settings_service.require_graph_id(target_id)
        return self._spec(target_id)

    def read(self, row: KgGraphDeployment, build_number: int | None = None) -> DeploymentRead:
        if build_number is None:
            build = self.session.get(KgBuild, row.build_id)
            build_number = build.number if build else 0
        kind = KINDS.get(row.target_kind)
        available = bool(kind and kind.available and kind.read_supported)
        return DeploymentRead(
            id=row.id,
            build_id=row.build_id,
            build_number=build_number,
            project_id=row.project_id,
            target_id=row.target_id,
            target_name=row.target_name,
            target_kind=row.target_kind,
            data_model=row.data_model,
            mapping_profile=row.mapping_profile,
            capability_profile=row.capability_profile,
            data_namespace=row.data_namespace,
            graphs=dict(row.graphs or {}),
            compatibility=CompatibilityReport.model_validate(row.compatibility) if row.compatibility else None,
            acknowledged_loss_by=row.acknowledged_loss_by,
            status=row.status,  # type: ignore[arg-type]
            stats=dict(row.stats or {}),
            error=row.error,
            origin=row.origin,  # type: ignore[arg-type]
            requested_by=row.requested_by,
            created_at=row.created_at,
            completed_at=row.completed_at,
            explorable=row.status == "completed" and available,
            queryable=row.status == "completed" and available and row.data_model == "rdf",
        )

    # ------------------------------------------------------------------ catalogue & compatibility

    def capabilities(self) -> GraphCapabilitiesRead:
        return GraphCapabilitiesRead(
            profiles=[
                CapabilityProfileRead(
                    **{**p.as_dict(), "query_languages": list(p.query_languages), "notes": list(p.notes)},
                    adapter_available=bool(KINDS.get(p.target_kind) and KINDS[p.target_kind].available),
                )
                for p in PROFILES.values()
            ],
            mapping_profiles=[MappingProfileRead(**m.as_dict()) for m in MAPPING_PROFILES.values()],
        )

    def compatibility(
        self, build_id: str, *, target_id: str | None = None, kind: str | None = None, mapping_profile: str | None = None
    ) -> CompatibilityRead:
        build = self._completed(build_id)
        if target_id:
            spec = self._spec(target_id)
        elif kind:
            profile = require_profile(kind)
            spec = TargetSpec(id="", name=profile.label, kind=kind)
        else:
            raise BusinessRuleError("Choose a graph target or a target kind.", code="GRAPH_TARGET_REQUIRED")
        profile = require_profile(spec.kind)
        snapshot, projection = load_projection(self.session, build)
        report = analyze(snapshot, projection, profile, resolve_mapping(profile, mapping_profile))
        return CompatibilityRead(
            build_id=build.id,
            target_id=spec.id or None,
            target_name=spec.name,
            target_kind=spec.kind,
            adapter_available=bool(KINDS.get(spec.kind) and KINDS[spec.kind].available),
            report=report,
        )

    # ------------------------------------------------------------------ deployments

    def list_for_build(self, build_id: str) -> list[DeploymentRead]:
        build = self._build(build_id)
        rows = self.session.scalars(
            select(KgGraphDeployment)
            .where(KgGraphDeployment.build_id == build_id)
            .order_by(KgGraphDeployment.created_at.desc())
        )
        return [self.read(r, build.number) for r in rows]

    def get(self, deployment_id: str) -> DeploymentRead:
        return self.read(self._deployment(deployment_id))

    def create(self, build_id: str, data: DeploymentCreate) -> DeploymentRead:
        build = self._completed(build_id)
        spec = self._write_spec(data.target_id)
        snapshot, projection = load_projection(self.session, build)
        row = deploy(
            self.session,
            build=build,
            spec=spec,
            snapshot=snapshot,
            projection=projection,
            data_namespace=data_namespace_of(build, snapshot),
            oxigraph_dir=self.settings.oxigraph_dir,
            sql_store=self.sql_store,
            mapping_id=data.mapping_profile,
            origin="manual",
            requested_by=data.requested_by,
            acknowledged_loss_by=data.requested_by if data.acknowledge_semantic_loss else None,
        )
        self.session.commit()
        return self.read(row, build.number)

    # ------------------------------------------------------------------ reads from targets

    def _usable(self, row: KgGraphDeployment, build_id: str | None = None) -> None:
        if build_id is not None and row.build_id != build_id:
            raise NotFoundError("The deployment does not belong to this build.", code="DEPLOYMENT_NOT_FOUND")
        if row.status != "completed":
            raise ConflictError(f"The deployment is {row.status}; only completed deployments can be read.",
                                code="DEPLOYMENT_NOT_READABLE")
        kind = KINDS.get(row.target_kind)
        if not (kind and kind.available and kind.read_supported):
            raise ConflictError(f"No adapter for {row.target_kind}.", code="GRAPH_KIND_NOT_AVAILABLE")

    def _read_spec(self, row: KgGraphDeployment) -> TargetSpec:
        """The connection a deployment was written with. Reads use the recorded settings, so editing or
        re-pointing a registration never redirects reads of a historical deployment; deployments recorded
        before snapshots existed fall back to the current registration."""
        allow_private = self.settings.graph_allow_private_networks
        if row.target_kind == "oxigraph":
            return TargetSpec(id=row.target_id, name=row.target_name, kind="oxigraph")
        if row.target_kind == "local-sql":
            return TargetSpec(id=row.target_id, name=row.target_name, kind="local-sql")
        snapshot = row.target_snapshot
        if snapshot:
            return TargetSpec(
                id=row.target_id, name=row.target_name, kind=snapshot.get("provider") or row.target_kind,
                config=dict(snapshot.get("config") or {}), secret_env=snapshot.get("secret_env"),
                allow_private=allow_private,
            )
        try:
            return self._spec(row.target_id)
        except NotFoundError as error:
            raise ConflictError(
                f"The graph connection '{row.target_name}' of this deployment no longer exists.", code="GRAPH_CONNECTION_GONE"
            ) from error

    def reader(self, build_id: str, deployment_id: str) -> tuple[GraphStore, list[str]]:
        """A read-only graph store over what the target actually holds for this deployment."""
        row = self._deployment(deployment_id)
        self._usable(row, build_id)
        if row.data_model != "rdf":
            if row.target_kind == "local-sql":
                return self.sql_store, []
            spec = self._read_spec(row)
            try:
                store = property_graph_store(PropertyTarget(spec.kind, spec.config, spec.secret_env, spec.allow_private))
            except DeploymentError as error:
                raise ConflictError(f"Could not read the deployment from {row.target_name}: {error}",
                                    code="GRAPH_TARGET_UNREACHABLE") from error
            return cast(GraphStore, _GuardedStore(store, row.target_name)), []
        key = f"{row.build_id}|{row.id}"
        with _read_cache_lock:
            cached = _read_cache.get(key)
        if cached and time.monotonic() - cached[0] < READ_CACHE_SECONDS:
            return cached[1], cached[2].warnings
        build = self._build(row.build_id)
        version = self.session.get(OntologyVersion, build.ontology_version_id)
        assert version is not None
        adapter = rdf_adapter(self._read_spec(row), self.settings.oxigraph_dir)
        graphs = row.graphs or {}
        try:
            data, provenance = adapter.fetch(graphs["data"]), adapter.fetch(graphs["provenance"])
        except DeploymentError as error:
            raise ConflictError(f"Could not read the deployment from {row.target_name}: {error}",
                                code="GRAPH_TARGET_UNREACHABLE") from error
        store, stats = read_rdf_projection(
            data, provenance, view_of(version).snapshot, row.data_namespace or "", name=row.target_kind, graph_id=build.id
        )
        with _read_cache_lock:
            _read_cache[key] = (time.monotonic(), store, stats)
        return store, stats.warnings

    def query(self, deployment_id: str, data: SparqlQueryRequest) -> SparqlResult:
        row = self._deployment(deployment_id)
        self._usable(row)
        if row.data_model != "rdf":
            raise BusinessRuleError(
                f"{row.target_name} is a property graph without a query language here; use the graph explorer.",
                code="QUERY_NOT_SUPPORTED",
            )
        form = check_read_only(data.query)
        graphs = row.graphs or {}
        adapter = rdf_adapter(self._read_spec(row), self.settings.oxigraph_dir)
        started = time.perf_counter()
        result = adapter.run_query(data.query, form, graphs["data"], [g for g in graphs.values() if g])
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        result.target = row.target_name
        result.default_graph = graphs["data"]
        return result
