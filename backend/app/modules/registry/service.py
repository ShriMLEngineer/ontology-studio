"""Ontology registry: immutable publication, version history, comparison and export."""

import json
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, DomainError, NotFoundError
from app.core.ids import new_id, utcnow
from app.modules.activity.service import record_activity
from app.modules.governance.service import GovernanceService
from app.modules.ontology.models import Ontology
from app.modules.ontology.service import OntologyService
from app.modules.registry.artifacts import ArtifactIntegrityError, OntologyArtifactRepository, StoredArtifact
from app.modules.registry.diff import SchemaDiff, bump_version, diff_snapshots, parse_semver
from app.modules.registry.models import OntologyVersion
from app.modules.registry.rdf import to_turtle
from app.modules.registry.schemas import (
    PublishPreview,
    PublishRequest,
    PublishValidation,
    VersionArtifactRead,
    VersionDetail,
    VersionSummary,
)
from app.modules.registry.snapshot import OntologySnapshot, SnapshotMetadata, build_snapshot, content_hash
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity
from app.modules.validation.service import ValidationService

ExportFormat = Literal["turtle", "json"]
DRAFT = "draft"


class ArtifactUnavailableError(DomainError):
    status_code = 500
    code = "ARTIFACT_INTEGRITY_ERROR"


class RegistryService:
    def __init__(self, session: Session, artifacts: OntologyArtifactRepository) -> None:
        self.session = session
        self.artifacts = artifacts
        self.ontologies = OntologyService(session)

    # ------------------------------------------------------------------------------ helpers

    def _draft_snapshot(self, ontology_id: str) -> tuple[Ontology, OntologySnapshot]:
        ontology, schema = self.ontologies.get_schema(ontology_id)
        metadata = SnapshotMetadata(
            name=ontology.name, namespace=ontology.namespace, prefix=ontology.prefix, description=ontology.description
        )
        return ontology, build_snapshot(metadata, schema)

    def _versions(self, ontology_id: str) -> list[OntologyVersion]:
        stmt = (
            select(OntologyVersion)
            .where(OntologyVersion.ontology_id == ontology_id)
            .order_by(OntologyVersion.sequence.desc())
        )
        return list(self.session.scalars(stmt))

    def _latest(self, ontology_id: str) -> OntologyVersion | None:
        versions = self._versions(ontology_id)
        return versions[0] if versions else None

    def _require_version(self, ontology_id: str, version_id: str) -> OntologyVersion:
        version = self.session.get(OntologyVersion, version_id)
        if version is None or version.ontology_id != ontology_id:
            raise NotFoundError(f"Version '{version_id}' was not found.", code="VERSION_NOT_FOUND")
        return version

    @staticmethod
    def _summary(version: OntologyVersion) -> VersionSummary:
        return VersionSummary(
            id=version.id,
            ontology_id=version.ontology_id,
            version=version.version,
            sequence=version.sequence,
            draft_revision=version.draft_revision,
            content_hash=version.content_hash,
            class_count=version.class_count,
            object_property_count=version.object_property_count,
            datatype_property_count=version.datatype_property_count,
            change_summary=version.change_summary,
            validation_summary=version.validation_summary,
            previous_version_id=version.previous_version_id,
            release_notes=version.release_notes,
            published_by=version.published_by,
            published_at=version.published_at,
            artifacts=[
                VersionArtifactRead(
                    format=a["format"], filename=a["filename"], media_type=a["media_type"], sha256=a["sha256"], size=a["size"]
                )
                for a in version.artifacts.values()
            ],
        )

    def _snapshot_of(self, ontology_id: str, ref: str) -> tuple[str, OntologySnapshot]:
        if ref == DRAFT:
            ontology, snapshot = self._draft_snapshot(ontology_id)
            return f"Draft r{ontology.draft_revision}", snapshot
        version = self._require_version(ontology_id, ref)
        return f"v{version.version}", OntologySnapshot.model_validate(version.snapshot)

    # ------------------------------------------------------------------------------ queries

    def list_versions(self, ontology_id: str) -> list[VersionSummary]:
        self.ontologies._require(ontology_id)
        return [self._summary(v) for v in self._versions(ontology_id)]

    def get_version(self, ontology_id: str, version_id: str) -> VersionDetail:
        version = self._require_version(ontology_id, version_id)
        return VersionDetail(
            **self._summary(version).model_dump(), snapshot=OntologySnapshot.model_validate(version.snapshot)
        )

    def compare(self, ontology_id: str, base: str, target: str) -> SchemaDiff:
        self.ontologies._require(ontology_id)
        base_label, base_snapshot = self._snapshot_of(ontology_id, base)
        target_label, target_snapshot = self._snapshot_of(ontology_id, target)
        return diff_snapshots(base_snapshot, target_snapshot, from_label=base_label, to_label=target_label)

    def preview(self, ontology_id: str, bump: str | None = None) -> PublishPreview:
        ontology, snapshot = self._draft_snapshot(ontology_id)
        issues = validate_schema(snapshot.to_schema())
        errors = [i for i in issues if i.severity == Severity.ERROR]
        latest = self._latest(ontology_id)
        latest_snapshot = OntologySnapshot.model_validate(latest.snapshot) if latest else None
        diff = diff_snapshots(
            latest_snapshot,
            snapshot,
            from_label=f"v{latest.version}" if latest else "nothing published",
            to_label=f"Draft r{ontology.draft_revision}",
        )
        blockers: list[str] = []
        if errors:
            blockers.append(f"{len(errors)} blocking validation error(s) must be fixed.")
        if latest and latest.content_hash == content_hash(snapshot):
            blockers.append(f"The draft is identical to the latest published version v{latest.version}.")
        stats = GovernanceService(self.session).stats(ontology_id)
        suggested_bump = bump or (diff.suggested_bump if diff.suggested_bump != "none" else "patch")
        return PublishPreview(
            ontology_id=ontology_id,
            draft_revision=ontology.draft_revision,
            latest_version=self._summary(latest) if latest else None,
            validation=PublishValidation(
                is_valid=not errors,
                error_count=len(errors),
                warning_count=sum(1 for i in issues if i.severity == Severity.WARNING),
                info_count=sum(1 for i in issues if i.severity == Severity.INFO),
                blocking_issues=errors,
            ),
            diff=diff,
            suggested_version=bump_version(latest.version if latest else None, suggested_bump),  # type: ignore[arg-type]
            can_publish=not blockers,
            blockers=blockers,
            proposals_awaiting_review=stats.awaiting_review,
            proposals_approved_not_applied=stats.approved_not_applied,
        )

    # ------------------------------------------------------------------------------ commands

    def publish(self, ontology_id: str, request: PublishRequest) -> VersionDetail:
        ontology, snapshot = self._draft_snapshot(ontology_id)
        if request.expected_draft_revision is not None and request.expected_draft_revision != ontology.draft_revision:
            raise ConflictError(
                "The draft changed after you reviewed it. Review the publication preview again.",
                code="DRAFT_REVISION_CONFLICT",
                details={"expected": request.expected_draft_revision, "current": ontology.draft_revision},
            )

        report = ValidationService(self.session).run(ontology_id)
        if not report.is_valid:
            raise BusinessRuleError(
                f"Publication blocked: the draft has {report.error_count} validation error(s).",
                code="PUBLISH_BLOCKED_BY_VALIDATION",
                details={"issues": [i.model_dump(mode="json") for i in report.issues if i.severity == Severity.ERROR]},
            )

        digest = content_hash(snapshot)
        latest = self._latest(ontology_id)
        if latest and latest.content_hash == digest:
            raise ConflictError(
                f"Nothing to publish: the draft is identical to v{latest.version}.", code="NOTHING_TO_PUBLISH"
            )
        latest_snapshot = OntologySnapshot.model_validate(latest.snapshot) if latest else None
        diff = diff_snapshots(
            latest_snapshot,
            snapshot,
            from_label=f"v{latest.version}" if latest else "nothing published",
            to_label=f"Draft r{ontology.draft_revision}",
        )
        if request.version:
            version_label = request.version
        else:
            bump = request.bump or (diff.suggested_bump if diff.suggested_bump != "none" else "patch")
            version_label = bump_version(latest.version if latest else None, bump)  # type: ignore[arg-type]
        parsed = parse_semver(version_label)
        if parsed is None:
            raise BusinessRuleError(
                f"'{version_label}' is not a semantic version (MAJOR.MINOR.PATCH).", code="INVALID_VERSION"
            )
        if latest and parsed <= (parse_semver(latest.version) or (0, 0, 0)):
            raise BusinessRuleError(
                f"Version {version_label} must be greater than the latest version {latest.version}.",
                code="VERSION_NOT_INCREASING",
            )

        version_id = new_id()
        published_at = utcnow()
        stem = f"{snapshot.metadata.prefix}-{version_label}"
        try:
            json_artifact = self.artifacts.store(
                ontology_id,
                version_id,
                fmt="json",
                filename=f"{stem}.json",
                media_type="application/json",
                content=json.dumps(
                    {
                        "ontology_id": ontology_id,
                        "version": version_label,
                        "published_at": published_at.isoformat(),
                        "published_by": request.published_by,
                        "content_hash": digest,
                        "snapshot": snapshot.model_dump(mode="json"),
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
            turtle_artifact = self.artifacts.store(
                ontology_id,
                version_id,
                fmt="turtle",
                filename=f"{stem}.ttl",
                media_type="text/turtle",
                content=to_turtle(
                    snapshot, version=version_label, published_at=published_at, release_notes=request.release_notes
                ),
            )
            version = OntologyVersion(
                id=version_id,
                ontology_id=ontology_id,
                version=version_label,
                sequence=(latest.sequence + 1) if latest else 1,
                draft_revision=ontology.draft_revision,
                snapshot=snapshot.model_dump(mode="json"),
                content_hash=digest,
                class_count=len(snapshot.classes),
                object_property_count=len(snapshot.object_properties),
                datatype_property_count=len(snapshot.datatype_properties),
                validation_run_id=report.id,
                validation_summary={
                    "is_valid": report.is_valid,
                    "error_count": report.error_count,
                    "warning_count": report.warning_count,
                    "info_count": report.info_count,
                },
                change_summary={k: v.model_dump() for k, v in diff.summary.items()}
                | {"suggested_bump": diff.suggested_bump, "breaking_changes": diff.breaking_changes},
                previous_version_id=latest.id if latest else None,
                artifacts={"json": json_artifact.as_dict(), "turtle": turtle_artifact.as_dict()},
                release_notes=request.release_notes,
                published_by=request.published_by,
                published_at=published_at,
            )
            self.session.add(version)
            record_activity(
                self.session,
                project_id=ontology.project_id,
                ontology_id=ontology.id,
                event_type="ontology.published",
                summary=f"{request.published_by} published v{version_label} from draft revision "
                f"{ontology.draft_revision}",
                details={"version_id": version_id, "version": version_label},
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            self.artifacts.discard(ontology_id, version_id)
            raise
        return self.get_version(ontology_id, version_id)

    def export(self, ontology_id: str, version_id: str, fmt: ExportFormat) -> tuple[bytes, StoredArtifact]:
        version = self._require_version(ontology_id, version_id)
        stored = version.artifacts.get(fmt)
        if stored is None:
            raise NotFoundError(f"No '{fmt}' artifact exists for this version.", code="EXPORT_FORMAT_NOT_AVAILABLE")
        artifact = StoredArtifact(**stored)
        try:
            return self.artifacts.read(artifact), artifact
        except ArtifactIntegrityError as error:
            raise ArtifactUnavailableError(str(error)) from error
