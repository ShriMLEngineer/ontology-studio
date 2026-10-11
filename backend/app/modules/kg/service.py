"""Knowledge-graph configuration: source preview, mappings, published-version selection and the
build lifecycle (configure -> start -> run in background -> completed/failed; rebuild)."""

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, UnavailableError
from app.modules.activity.service import record_activity
from app.modules.kg.connectors import CsvDocumentSource, SourceReadError, infer_datatype, is_structured
from app.modules.kg.extraction import PROMPT_VERSION
from app.modules.kg.mapping import MappingSpec, suggest_mapping, validate_mapping
from app.modules.kg.models import KgBuild, KgBuildLog, KgOntologyGap, KgSourceMapping
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.orchestrator import ACTIVE_STATUSES, STAGES, initial_stages
from app.modules.kg.policy import get_policy
from app.modules.kg.schemas import (
    BuildCreate,
    BuildDetail,
    BuildLogRead,
    BuildReadiness,
    BuildSettings,
    BuildSourceRead,
    BuildStage,
    BuildSummary,
    BuildUpdate,
    ColumnProfile,
    MappingCreate,
    MappingIssueRead,
    MappingRead,
    MappingSuggestion,
    MappingUpdate,
    MappingValidateRequest,
    MappingValidation,
    PreviewRow,
    PublishedVersionOption,
    ReadinessIssue,
    RebuildRequest,
    SourcePreview,
)
from app.modules.llm.provider import LLMNotConfiguredError, LLMProvider
from app.modules.ontology.models import Ontology
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.models import Project
from app.modules.registry.models import OntologyVersion
from app.modules.semantics.owl import ontology_iri_of
from app.modules.registry.snapshot import OntologySnapshot
from app.modules.sources.models import SourceDocument


def view_of(version: OntologyVersion) -> OntologyView:
    return OntologyView(OntologySnapshot.model_validate(version.snapshot), version_id=version.id, version=version.version)


def _issues(items: list[Any]) -> list[MappingIssueRead]:
    return [MappingIssueRead(**i.as_dict()) for i in items]


class KgService:
    def __init__(self, session: Session, *, max_records: int = 10_000) -> None:
        self.session = session
        self.max_records = max_records

    # ------------------------------------------------------------------ lookups

    def _require_project(self, project_id: str) -> None:
        if ProjectRepository(self.session).get(project_id) is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")

    def _require_document(self, document_id: str) -> SourceDocument:
        document = self.session.get(SourceDocument, document_id)
        if document is None:
            raise NotFoundError(f"Source document '{document_id}' was not found.", code="SOURCE_NOT_FOUND")
        return document

    def require_build(self, build_id: str) -> KgBuild:
        build = self.session.get(KgBuild, build_id)
        if build is None:
            raise NotFoundError(f"Knowledge graph build '{build_id}' was not found.", code="KG_BUILD_NOT_FOUND")
        return build

    def _require_mapping(self, mapping_id: str) -> KgSourceMapping:
        mapping = self.session.get(KgSourceMapping, mapping_id)
        if mapping is None:
            raise NotFoundError(f"Mapping '{mapping_id}' was not found.", code="MAPPING_NOT_FOUND")
        return mapping

    def require_published_version(self, project_id: str, version_id: str) -> OntologyVersion:
        """Only immutable published versions can be selected; drafts are never accepted."""
        version = self.session.get(OntologyVersion, version_id)
        if version is None:
            if self.session.get(Ontology, version_id) is not None:
                raise BusinessRuleError(
                    "A draft ontology cannot be used to build a knowledge graph. Publish a version in Ontology "
                    "Studio and select it.",
                    code="PUBLISHED_VERSION_REQUIRED",
                )
            raise NotFoundError(
                f"Published ontology version '{version_id}' was not found.", code="ONTOLOGY_VERSION_NOT_FOUND"
            )
        ontology = self.session.get(Ontology, version.ontology_id)
        if ontology is None or ontology.project_id != project_id:
            raise BusinessRuleError(
                "The ontology version does not belong to this project.", code="ONTOLOGY_VERSION_NOT_IN_PROJECT"
            )
        return version

    # ------------------------------------------------------------------ published versions

    def list_published_versions(self, project_id: str) -> list[PublishedVersionOption]:
        self._require_project(project_id)
        rows = self.session.execute(
            select(OntologyVersion, Ontology.name)
            .join(Ontology, Ontology.id == OntologyVersion.ontology_id)
            .where(Ontology.project_id == project_id)
            .order_by(Ontology.name, OntologyVersion.sequence.desc())
        ).all()
        latest: dict[str, int] = {}
        for version, _ in rows:
            latest[version.ontology_id] = max(latest.get(version.ontology_id, 0), version.sequence)
        return [
            PublishedVersionOption(
                version_id=version.id,
                ontology_id=version.ontology_id,
                ontology_name=name,
                version=version.version,
                published_at=version.published_at,
                published_by=version.published_by,
                class_count=version.class_count,
                object_property_count=version.object_property_count,
                datatype_property_count=version.datatype_property_count,
                is_latest=version.sequence == latest[version.ontology_id],
            )
            for version, name in rows
        ]

    # ------------------------------------------------------------------ source preview

    def preview(self, document_id: str, rows: int = 20) -> SourcePreview:
        document = self._require_document(document_id)
        if not is_structured(document):
            return SourcePreview(
                document_id=document.id,
                filename=document.filename,
                media_type=document.media_type,
                kind="text",
                page_count=document.page_count,
                chunk_count=document.chunk_count,
                text_excerpt=document.text[:2000],
            )
        try:
            source = CsvDocumentSource(self.session, document)
        except SourceReadError as error:
            raise BusinessRuleError(str(error), code="SOURCE_NOT_TABULAR") from error
        columns = source.columns()
        values: dict[str, list[str]] = {c: [] for c in columns}
        preview: list[PreviewRow] = []
        total = 0
        for record in source.records(self.max_records):
            total += 1
            if len(preview) < rows:
                preview.append(PreviewRow(row_number=record.row_number, values=record.values))
            for column in columns:
                if record.values.get(column):
                    values[column].append(record.values[column])
        profiles = [
            ColumnProfile(
                name=column,
                non_empty=len(values[column]),
                distinct_values=len(set(values[column])),
                sample_values=list(dict.fromkeys(values[column]))[:5],
                inferred_datatype=infer_datatype(values[column]),
            )
            for column in columns
        ]
        return SourcePreview(
            document_id=document.id,
            filename=document.filename,
            media_type=document.media_type,
            kind="table",
            columns=profiles,
            rows=preview,
            total_rows=total,
            chunk_count=document.chunk_count,
        )

    def _columns(self, document: SourceDocument) -> list[str]:
        if not is_structured(document):
            raise BusinessRuleError(
                f"'{document.filename}' is not a structured source; mappings apply to CSV/TSV sources only. "
                "Documents are processed by ontology-guided extraction.",
                code="SOURCE_NOT_TABULAR",
            )
        try:
            return CsvDocumentSource(self.session, document).columns()
        except SourceReadError as error:
            raise BusinessRuleError(str(error), code="SOURCE_NOT_TABULAR") from error

    # ------------------------------------------------------------------ mappings

    def _mapping_read(self, mapping: KgSourceMapping) -> MappingRead:
        document = self.session.get(SourceDocument, mapping.document_id)
        version = self.session.get(OntologyVersion, mapping.ontology_version_id) if mapping.ontology_version_id else None
        spec = MappingSpec.model_validate(mapping.spec)
        issues: list[MappingIssueRead] = []
        if document is not None and version is not None:
            issues = _issues(validate_mapping(spec, self._columns(document), view_of(version)))
        return MappingRead(
            id=mapping.id,
            project_id=mapping.project_id,
            document_id=mapping.document_id,
            document_name=document.filename if document else "(deleted)",
            ontology_id=mapping.ontology_id,
            ontology_version_id=mapping.ontology_version_id,
            ontology_version=version.version if version else None,
            name=mapping.name,
            description=mapping.description,
            spec=spec,
            updated_by=mapping.updated_by,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
            issues=issues,
        )

    def list_mappings(self, project_id: str, document_id: str | None = None) -> list[MappingRead]:
        self._require_project(project_id)
        stmt = select(KgSourceMapping).where(KgSourceMapping.project_id == project_id)
        if document_id:
            stmt = stmt.where(KgSourceMapping.document_id == document_id)
        return [self._mapping_read(m) for m in self.session.scalars(stmt.order_by(KgSourceMapping.name))]

    def get_mapping(self, mapping_id: str) -> MappingRead:
        return self._mapping_read(self._require_mapping(mapping_id))

    def _check_mapping(
        self, project_id: str, document: SourceDocument, version: OntologyVersion, spec: MappingSpec
    ) -> list[MappingIssueRead]:
        if document.project_id != project_id:
            raise BusinessRuleError("The source document is not part of this project.", code="SOURCE_NOT_IN_PROJECT")
        issues = _issues(validate_mapping(spec, self._columns(document), view_of(version)))
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise BusinessRuleError(
                f"The mapping is not valid: {errors[0].message}",
                code="MAPPING_INVALID",
                details={"issues": [i.model_dump() for i in issues]},
            )
        return issues

    def _ensure_unique_name(self, document_id: str, name: str, exclude: str | None = None) -> None:
        stmt = select(KgSourceMapping.id).where(KgSourceMapping.document_id == document_id, KgSourceMapping.name == name)
        existing = self.session.scalars(stmt).first()
        if existing and existing != exclude:
            raise ConflictError(f"A mapping named '{name}' already exists for this source.", code="MAPPING_NAME_TAKEN")

    def create_mapping(self, project_id: str, data: MappingCreate) -> MappingRead:
        self._require_project(project_id)
        document = self._require_document(data.document_id)
        version = self.require_published_version(project_id, data.ontology_version_id)
        self._check_mapping(project_id, document, version, data.spec)
        self._ensure_unique_name(document.id, data.name)
        mapping = KgSourceMapping(
            project_id=project_id,
            document_id=document.id,
            ontology_id=version.ontology_id,
            ontology_version_id=version.id,
            name=data.name,
            description=data.description,
            spec=data.spec.model_dump(mode="json"),
            updated_by=data.updated_by,
        )
        self.session.add(mapping)
        record_activity(
            self.session,
            project_id=project_id,
            ontology_id=version.ontology_id,
            event_type="kg.mapping_saved",
            summary=f"Source mapping '{data.name}' saved for {document.filename}",
            details={"mapping_id": mapping.id},
        )
        self.session.commit()
        return self._mapping_read(mapping)

    def update_mapping(self, mapping_id: str, data: MappingUpdate) -> MappingRead:
        mapping = self._require_mapping(mapping_id)
        document = self._require_document(mapping.document_id)
        version_id = data.ontology_version_id or mapping.ontology_version_id
        if not version_id:
            raise BusinessRuleError("Select a published ontology version.", code="PUBLISHED_VERSION_REQUIRED")
        version = self.require_published_version(mapping.project_id, version_id)
        if version.ontology_id != mapping.ontology_id:
            raise BusinessRuleError("A mapping cannot be moved to a different ontology.", code="MAPPING_ONTOLOGY_MISMATCH")
        spec = data.spec or MappingSpec.model_validate(mapping.spec)
        self._check_mapping(mapping.project_id, document, version, spec)
        if data.name and data.name != mapping.name:
            self._ensure_unique_name(document.id, data.name, exclude=mapping.id)
            mapping.name = data.name
        if data.description is not None:
            mapping.description = data.description
        mapping.spec = spec.model_dump(mode="json")
        mapping.ontology_version_id = version.id
        mapping.updated_by = data.updated_by
        record_activity(
            self.session,
            project_id=mapping.project_id,
            ontology_id=mapping.ontology_id,
            event_type="kg.mapping_saved",
            summary=f"Source mapping '{mapping.name}' updated for {document.filename}",
            details={"mapping_id": mapping.id},
        )
        self.session.commit()
        return self._mapping_read(mapping)

    def delete_mapping(self, mapping_id: str) -> None:
        mapping = self._require_mapping(mapping_id)
        configured = self.session.scalars(
            select(KgBuild).where(KgBuild.project_id == mapping.project_id, KgBuild.status == "configured")
        )
        users = [b for b in configured if mapping.id in (b.mapping_ids or [])]
        if users:
            raise ConflictError(
                f"The mapping is used by configured build #{users[0].number}.",
                code="MAPPING_IN_USE",
                details={"build_ids": [b.id for b in users]},
            )
        self.session.delete(mapping)
        self.session.commit()

    def validate_mapping(self, project_id: str, data: MappingValidateRequest) -> MappingValidation:
        document = self._require_document(data.document_id)
        version = self.require_published_version(project_id, data.ontology_version_id)
        issues = _issues(validate_mapping(data.spec, self._columns(document), view_of(version)))
        return MappingValidation(valid=not any(i.severity == "error" for i in issues), issues=issues)

    def suggest(self, document_id: str, version_id: str) -> MappingSuggestion:
        document = self._require_document(document_id)
        version = self.require_published_version(document.project_id, version_id)
        columns = self._columns(document)
        view = view_of(version)
        spec, notes = suggest_mapping(columns, view)
        issues = _issues(validate_mapping(spec, columns, view)) if spec else []
        return MappingSuggestion(spec=spec, notes=notes, issues=issues)

    # ------------------------------------------------------------------ builds: reads

    def _summary(self, build: KgBuild) -> BuildSummary:
        duration = None
        if build.started_at and build.completed_at:
            duration = int((build.completed_at - build.started_at).total_seconds() * 1000)
        return BuildSummary(
            id=build.id,
            project_id=build.project_id,
            number=build.number,
            name=build.name,
            status=build.status,  # type: ignore[arg-type]
            ontology_id=build.ontology_id,
            ontology_name=build.ontology_name,
            ontology_version_id=build.ontology_version_id,
            ontology_version=build.ontology_version,
            parent_build_id=build.parent_build_id,
            current_stage=build.current_stage,
            stages_completed=sum(1 for s in build.stages or [] if s["status"] == "completed"),
            stage_count=len(build.stages) or len(STAGES),
            stats=build.stats or {},
            graph_store=build.graph_store,
            provider=build.provider,
            model=build.model,
            requested_by=build.requested_by,
            error=build.error,
            created_at=build.created_at,
            started_at=build.started_at,
            completed_at=build.completed_at,
            duration_ms=duration,
        )

    def detail(self, build: KgBuild, provider: LLMProvider | None = None) -> BuildDetail:
        snapshot_sources = {s["id"]: s for s in (build.config_snapshot or {}).get("sources", [])}
        snapshot_mappings = {m["document_id"]: m for m in (build.config_snapshot or {}).get("mappings", [])}
        mappings = {
            m.document_id: m
            for m in self.session.scalars(select(KgSourceMapping).where(KgSourceMapping.id.in_(build.mapping_ids or [])))
        }
        sources: list[BuildSourceRead] = []
        for document_id in build.source_document_ids:
            document = self.session.get(SourceDocument, document_id)
            frozen = snapshot_sources.get(document_id, {})
            mapping = snapshot_mappings.get(document_id) or (
                {"id": mappings[document_id].id, "name": mappings[document_id].name} if document_id in mappings else None
            )
            media_type = document.media_type if document else frozen.get("media_type", "")
            sources.append(
                BuildSourceRead(
                    id=document_id,
                    filename=document.filename if document else frozen.get("filename", "(deleted)"),
                    media_type=media_type,
                    kind="table" if media_type in ("text/csv", "text/tab-separated-values") else "text",
                    available=document is not None,
                    mapping_id=mapping["id"] if mapping else None,
                    mapping_name=mapping["name"] if mapping else None,
                )
            )
        gap_count = self.session.scalar(
            select(func.count()).select_from(KgOntologyGap).where(KgOntologyGap.build_id == build.id)
        ) or 0
        return BuildDetail(
            **self._summary(build).model_dump(),
            sources=sources,
            mapping_ids=list(build.mapping_ids or []),
            settings=BuildSettings.model_validate(build.settings or {}),
            stages=[BuildStage.model_validate(s) for s in build.stages or []],
            readiness=self.readiness(build, provider) if build.status == "configured" else None,
            prompt_version=build.prompt_version,
            gap_count=gap_count,
        )

    def list_builds(self, project_id: str) -> list[BuildSummary]:
        self._require_project(project_id)
        stmt = select(KgBuild).where(KgBuild.project_id == project_id).order_by(KgBuild.number.desc())
        return [self._summary(b) for b in self.session.scalars(stmt)]

    def get_build(self, build_id: str, provider: LLMProvider | None = None) -> BuildDetail:
        return self.detail(self.require_build(build_id), provider)

    def list_logs(self, build_id: str, after: int = 0) -> list[BuildLogRead]:
        self.require_build(build_id)
        stmt = (
            select(KgBuildLog)
            .where(KgBuildLog.build_id == build_id, KgBuildLog.id > after)
            .order_by(KgBuildLog.id)
            .limit(1000)
        )
        return [BuildLogRead.model_validate(log) for log in self.session.scalars(stmt)]

    # ------------------------------------------------------------------ builds: configuration

    def readiness(self, build: KgBuild, provider: LLMProvider | None) -> BuildReadiness:
        issues: list[ReadinessIssue] = []

        def error(code: str, message: str, **details: Any) -> None:
            issues.append(ReadinessIssue(severity="error", code=code, message=message, details=details))

        version = self.session.get(OntologyVersion, build.ontology_version_id)
        if version is None:
            error("ONTOLOGY_VERSION_NOT_FOUND", "The selected ontology version no longer exists.")
        if not build.source_document_ids:
            error("SOURCES_REQUIRED", "Select at least one data source.")
        mappings = {
            m.id: m
            for m in self.session.scalars(select(KgSourceMapping).where(KgSourceMapping.id.in_(build.mapping_ids or [])))
        }
        for missing in set(build.mapping_ids or []) - set(mappings):
            error("MAPPING_NOT_FOUND", "A selected mapping no longer exists.", mapping_id=missing)
        by_document = Counter(m.document_id for m in mappings.values())
        has_text = False
        for document_id in build.source_document_ids:
            document = self.session.get(SourceDocument, document_id)
            if document is None or document.project_id != build.project_id:
                error("SOURCE_NOT_FOUND", "A selected source no longer exists in this project.", document_id=document_id)
                continue
            if not is_structured(document):
                has_text = True
                if document.chunk_count == 0:
                    issues.append(
                        ReadinessIssue(severity="warning", code="EMPTY_DOCUMENT", message=f"'{document.filename}' has no text.")
                    )
                continue
            count = by_document.get(document_id, 0)
            if count == 0:
                error(
                    "MAPPING_REQUIRED",
                    f"Structured source '{document.filename}' needs a saved mapping.",
                    document_id=document_id,
                )
            elif count > 1:
                error("MAPPING_AMBIGUOUS", f"Select only one mapping for '{document.filename}'.", document_id=document_id)
        for mapping in mappings.values():
            if mapping.document_id not in build.source_document_ids:
                error(
                    "MAPPING_SOURCE_NOT_SELECTED",
                    f"Mapping '{mapping.name}' belongs to a source that is not selected.",
                    mapping_id=mapping.id,
                )
                continue
            if mapping.ontology_id != build.ontology_id:
                error(
                    "MAPPING_ONTOLOGY_MISMATCH",
                    f"Mapping '{mapping.name}' was written for a different ontology.",
                    mapping_id=mapping.id,
                )
                continue
            document = self.session.get(SourceDocument, mapping.document_id)
            if version is None or document is None:
                continue
            for issue in validate_mapping(MappingSpec.model_validate(mapping.spec), self._columns(document), view_of(version)):
                issues.append(
                    ReadinessIssue(
                        severity=issue.severity,  # type: ignore[arg-type]
                        code="MAPPING_INCOMPATIBLE" if issue.severity == "error" else issue.code,
                        message=f"Mapping '{mapping.name}' with {version.version}: {issue.message}",
                        details={"mapping_id": mapping.id, "path": issue.path},
                    )
                )
        if has_text and provider is None:
            error(
                LLMNotConfiguredError.code,
                "Document sources need an LLM, but none is available for this build. Select a registered LLM "
                "configuration (Settings) or configure the environment default (OLS_LLM_BASE_URL, OLS_LLM_MODEL).",
            )
        return BuildReadiness(ready=not any(i.severity == "error" for i in issues), issues=issues)

    def _validate_selection(self, project_id: str, source_ids: list[str], mapping_ids: list[str]) -> None:
        documents = set(
            self.session.scalars(
                select(SourceDocument.id).where(SourceDocument.id.in_(source_ids), SourceDocument.project_id == project_id)
            )
        )
        missing = [d for d in source_ids if d not in documents]
        if missing:
            raise BusinessRuleError(
                "Some sources do not exist in this project.", code="SOURCE_NOT_IN_PROJECT", details={"document_ids": missing}
            )
        found = set(
            self.session.scalars(
                select(KgSourceMapping.id).where(
                    KgSourceMapping.id.in_(mapping_ids), KgSourceMapping.project_id == project_id
                )
            )
        )
        unknown = [m for m in mapping_ids if m not in found]
        if unknown:
            raise BusinessRuleError(
                "Some mappings do not exist in this project.", code="MAPPING_NOT_FOUND", details={"mapping_ids": unknown}
            )

    def _next_number(self, project_id: str) -> int:
        return (self.session.scalar(select(func.max(KgBuild.number)).where(KgBuild.project_id == project_id)) or 0) + 1

    def create_build(self, project_id: str, data: BuildCreate, provider: LLMProvider | None) -> KgBuild:
        self._require_project(project_id)
        version = self.require_published_version(project_id, data.ontology_version_id)
        source_ids = list(dict.fromkeys(data.source_document_ids))
        mapping_ids = list(dict.fromkeys(data.mapping_ids))
        self._validate_selection(project_id, source_ids, mapping_ids)
        ontology = self.session.get(Ontology, version.ontology_id)
        assert ontology is not None
        number = self._next_number(project_id)
        build = KgBuild(
            project_id=project_id,
            number=number,
            name=data.name or f"Build #{number}",
            ontology_id=version.ontology_id,
            ontology_version_id=version.id,
            ontology_version=version.version,
            ontology_name=ontology.name,
            status="configured",
            source_document_ids=source_ids,
            mapping_ids=mapping_ids,
            settings=data.settings.model_dump(),
            stages=initial_stages(),
            stats={},
            llm_outputs=[],
            requested_by=data.requested_by,
        )
        self.session.add(build)
        record_activity(
            self.session,
            project_id=project_id,
            ontology_id=version.ontology_id,
            event_type="kg.build_configured",
            summary=f"Knowledge graph build #{number} configured with {ontology.name} {version.version} "
            f"and {len(source_ids)} source(s)",
            details={"build_id": build.id},
        )
        self.session.commit()
        return build

    def update_build(self, build_id: str, data: BuildUpdate) -> KgBuild:
        build = self.require_build(build_id)
        if build.status != "configured":
            raise ConflictError(
                "Only builds that have not been started can be edited; use Rebuild instead.", code="KG_BUILD_NOT_EDITABLE"
            )
        if data.ontology_version_id:
            version = self.require_published_version(build.project_id, data.ontology_version_id)
            ontology = self.session.get(Ontology, version.ontology_id)
            assert ontology is not None
            build.ontology_id = version.ontology_id
            build.ontology_version_id = version.id
            build.ontology_version = version.version
            build.ontology_name = ontology.name
        source_ids = list(dict.fromkeys(data.source_document_ids)) if data.source_document_ids is not None else build.source_document_ids
        mapping_ids = list(dict.fromkeys(data.mapping_ids)) if data.mapping_ids is not None else build.mapping_ids
        self._validate_selection(build.project_id, source_ids, mapping_ids)
        build.source_document_ids = source_ids
        build.mapping_ids = mapping_ids
        if data.name:
            build.name = data.name
        if data.settings is not None:
            build.settings = data.settings.model_dump()
        self.session.commit()
        return build

    def delete_build(self, build_id: str) -> None:
        build = self.require_build(build_id)
        if build.status != "configured":
            raise ConflictError(
                "Executed builds are kept for traceability and cannot be deleted.", code="KG_BUILD_NOT_DELETABLE"
            )
        self.session.delete(build)
        self.session.commit()

    def _data_namespace(self, project_id: str, version: OntologyVersion) -> str:
        """Base of instance IRIs, frozen per build: the project's data namespace, or one derived from
        the ontology IRI of the selected version."""
        project = self.session.get(Project, project_id)
        if project is not None and project.data_namespace:
            return project.data_namespace
        snapshot = OntologySnapshot.model_validate(version.snapshot)
        return f"{ontology_iri_of(snapshot)}/data/"

    def start_build(
        self, build_id: str, requested_by: str, provider: LLMProvider | None, selection: dict[str, Any] | None = None
    ) -> KgBuild:
        build = self.require_build(build_id)
        if build.status != "configured":
            raise ConflictError(f"Build #{build.number} has already been started.", code="KG_BUILD_ALREADY_STARTED")
        active = self.session.scalars(
            select(KgBuild.id).where(KgBuild.project_id == build.project_id, KgBuild.status.in_(ACTIVE_STATUSES))
        ).first()
        if active:
            raise ConflictError(
                "Another knowledge graph build is in progress for this project.",
                code="KG_BUILD_IN_PROGRESS",
                details={"build_id": active},
            )
        readiness = self.readiness(build, provider)
        if not readiness.ready:
            errors = [i for i in readiness.issues if i.severity == "error"]
            if any(i.code == LLMNotConfiguredError.code for i in errors):
                raise UnavailableError(errors[0].message, code=LLMNotConfiguredError.code)
            raise BusinessRuleError(
                f"The build is not ready: {errors[0].message}",
                code="KG_BUILD_NOT_READY",
                details={"issues": [i.model_dump() for i in readiness.issues]},
            )
        version = self.session.get(OntologyVersion, build.ontology_version_id)
        assert version is not None
        documents = [self.session.get(SourceDocument, d) for d in build.source_document_ids]
        mappings = list(self.session.scalars(select(KgSourceMapping).where(KgSourceMapping.id.in_(build.mapping_ids))))
        has_text = any(d is not None and not is_structured(d) for d in documents)
        build.config_snapshot = {
            "ontology": {
                "ontology_id": version.ontology_id,
                "version_id": version.id,
                "version": version.version,
                "content_hash": version.content_hash,
            },
            "sources": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "media_type": d.media_type,
                    "sha256": d.sha256,
                    "kind": "table" if is_structured(d) else "text",
                }
                for d in documents
                if d is not None
            ],
            "mappings": [
                {"id": m.id, "name": m.name, "document_id": m.document_id, "spec": m.spec} for m in mappings
            ],
            "settings": dict(build.settings or {}),
            "validation_policy": get_policy((build.settings or {}).get("validation_policy")).config(),
            # Effective LLM configuration and graph target (Settings), frozen at start.
            **(selection or {}),
            "data_namespace": self._data_namespace(build.project_id, version),
            "llm": {"provider": provider.name, "model": provider.model, "prompt_version": PROMPT_VERSION}
            if has_text and provider
            else None,
        }
        if has_text and provider is not None:
            build.provider, build.model, build.prompt_version = provider.name, provider.model, PROMPT_VERSION
        build.status = "queued"
        build.requested_by = requested_by
        build.stages = initial_stages()
        record_activity(
            self.session,
            project_id=build.project_id,
            ontology_id=build.ontology_id,
            event_type="kg.build_started",
            summary=f"Knowledge graph build #{build.number} started with {build.ontology_name} {build.ontology_version}",
            details={"build_id": build.id},
        )
        self.session.commit()
        return build

    def rebuild(self, build_id: str, data: RebuildRequest) -> KgBuild:
        parent = self.require_build(build_id)
        if parent.status == "configured":
            raise ConflictError("Start or edit this build instead of rebuilding it.", code="KG_BUILD_NOT_STARTED")
        version = self.require_published_version(parent.project_id, data.ontology_version_id)
        available = set(
            self.session.scalars(
                select(SourceDocument.id).where(SourceDocument.id.in_(parent.source_document_ids))
            )
        )
        mapping_ids = list(
            self.session.scalars(
                select(KgSourceMapping.id).where(
                    KgSourceMapping.id.in_(parent.mapping_ids), KgSourceMapping.ontology_id == version.ontology_id
                )
            )
        )
        build = self.create_build(
            parent.project_id,
            BuildCreate(
                name=data.name or f"Rebuild of #{parent.number} with {version.version}",
                ontology_version_id=version.id,
                source_document_ids=[d for d in parent.source_document_ids if d in available] or parent.source_document_ids,
                mapping_ids=mapping_ids,
                settings=BuildSettings.model_validate(parent.settings or {}),
                requested_by=data.requested_by,
            ),
            None,
        )
        build.parent_build_id = parent.id
        self.session.commit()
        return build
