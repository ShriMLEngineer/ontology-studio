"""Ontology registry: immutable publication, version history, comparison and export."""

import hashlib
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
from app.modules.semantics.graphs import FORMATS, parse_rdf, serialize
from app.modules.semantics.owl import ontology_iri_of, snapshot_to_owl
from app.modules.shacl.engine import check_shapes
from app.modules.shacl.shapes import build_shapes_graph
from app.modules.registry.schemas import (
    PublishPreview,
    PublishRequest,
    PublishValidation,
    VersionArtifactRead,
    VersionDetail,
    VersionSummary,
)
from app.modules.registry.snapshot import (
    OntologySnapshot,
    build_snapshot,
    content_hash,
    metadata_from_ontology,
)
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity
from app.modules.validation.service import ValidationService

ExportFormat = Literal["turtle", "json", "rdfxml", "jsonld", "ntriples", "shapes", "manifest"]


def shapes_problem(snapshot: OntologySnapshot) -> str | None:
    """SHACL-SHACL meta-validation of the shapes graph the version package would contain."""
    check = check_shapes(build_shapes_graph(snapshot)[0])
    return None if check.well_formed else check.message or "the shapes graph does not conform to SHACL-SHACL"
RDF_EXPORT_FORMATS = ("turtle", "rdfxml", "jsonld", "ntriples")
DRAFT = "draft"
PACKAGE_FORMAT = "ols-semantic/2"
SEMANTIC_PROFILE = "ols-semantic-profile/1"
GENERATOR = "Ontology Lifecycle Studio (Phase 4)"


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
        return ontology, build_snapshot(metadata_from_ontology(ontology), schema)

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
            snapshot_format=version.snapshot.get("format", "ols.ontology-snapshot/1"),
            package_format=PACKAGE_FORMAT if "manifest" in version.artifacts else "ols-semantic/1 (legacy)",
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
        problem = shapes_problem(snapshot)
        if problem:
            blockers.append(f"The SHACL shapes are not well-formed: {problem}")
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
        problem = shapes_problem(snapshot)
        if problem:
            raise BusinessRuleError(
                f"Publication blocked: the SHACL shapes are not well-formed ({problem}).",
                code="PUBLISH_BLOCKED_BY_SHAPES",
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
            stored = self._store_package(
                ontology_id,
                version_id,
                snapshot,
                stem=stem,
                version_label=version_label,
                published_at=published_at,
                published_by=request.published_by,
                release_notes=request.release_notes,
                digest=digest,
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
                | {
                    "suggested_bump": diff.suggested_bump,
                    "breaking_changes": diff.breaking_changes,
                    "notes": diff.notes,
                    "axiom_changes": len(diff.axiom_changes),
                },
                previous_version_id=latest.id if latest else None,
                artifacts={fmt: artifact.as_dict() for fmt, artifact in stored.items()},
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

    def _store_package(
        self,
        ontology_id: str,
        version_id: str,
        snapshot: OntologySnapshot,
        *,
        stem: str,
        version_label: str,
        published_at: object,
        published_by: str,
        release_notes: str,
        digest: str,
    ) -> dict[str, StoredArtifact]:
        """Write the immutable version package: snapshot JSON, OWL in four RDF syntaxes and a manifest."""
        stored: dict[str, StoredArtifact] = {}
        stored["json"] = self.artifacts.store(
            ontology_id,
            version_id,
            fmt="json",
            filename=f"{stem}.json",
            media_type="application/json",
            content=json.dumps(
                {
                    "ontology_id": ontology_id,
                    "version": version_label,
                    "published_at": published_at.isoformat(),  # type: ignore[attr-defined]
                    "published_by": published_by,
                    "content_hash": digest,
                    "snapshot": snapshot.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        graph = snapshot_to_owl(
            snapshot, version=version_label, published_at=published_at, release_notes=release_notes  # type: ignore[arg-type]
        )
        for fmt in RDF_EXPORT_FORMATS:
            info = FORMATS[fmt]
            stored[fmt] = self.artifacts.store(
                ontology_id,
                version_id,
                fmt=fmt,
                filename=f"{stem}.{info.extension}",
                media_type=info.media_type,
                content=serialize(graph, fmt),
            )
        shapes_graph, shape_index = build_shapes_graph(snapshot)
        stored["shapes"] = self.artifacts.store(
            ontology_id,
            version_id,
            fmt="shapes",
            filename=f"{stem}.shapes.ttl",
            media_type="text/turtle",
            content=serialize(shapes_graph, "turtle"),
        )
        onto = str(ontology_iri_of(snapshot))
        manifest = {
            "package_format": PACKAGE_FORMAT,
            "snapshot_format": snapshot.format,
            "semantic_profile": SEMANTIC_PROFILE,
            "ontology_id": ontology_id,
            "version_id": version_id,
            "version": version_label,
            "ontology_iri": onto,
            "version_iri": f"{onto}/{version_label}",
            "prefixes": {snapshot.metadata.prefix: snapshot.metadata.namespace}
            | {p.prefix: p.namespace for p in snapshot.metadata.prefixes},
            "imports": snapshot.metadata.imports,
            "content_hash": digest,
            "preserved_axioms": len(snapshot.extension_axioms),
            "shapes": shape_index.counts(),
            "artifacts": {
                fmt: {"filename": a.filename, "media_type": a.media_type, "sha256": a.sha256, "size": a.size}
                for fmt, a in stored.items()
            },
            "generator": GENERATOR,
            "published_by": published_by,
            "published_at": published_at.isoformat(),  # type: ignore[attr-defined]
        }
        stored["manifest"] = self.artifacts.store(
            ontology_id,
            version_id,
            fmt="manifest",
            filename=f"{stem}.manifest.json",
            media_type="application/json",
            content=json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        )
        return stored

    def export(self, ontology_id: str, version_id: str, fmt: ExportFormat) -> tuple[bytes, StoredArtifact, bool]:
        """Return (content, artifact, derived). Stored artifacts are verified by SHA-256.

        Legacy (pre-Phase 4) versions only stored Turtle and JSON; other RDF syntaxes are *derived*
        from the stored Turtle (same graph, different syntax) and labelled as such. Nothing is written.
        """
        version = self._require_version(ontology_id, version_id)
        stored = version.artifacts.get(fmt)
        if stored is not None:
            artifact = StoredArtifact(**stored)
            try:
                return self.artifacts.read(artifact), artifact, False
            except ArtifactIntegrityError as error:
                raise ArtifactUnavailableError(str(error)) from error
        if fmt == "shapes":
            # Legacy versions predate SHACL: shapes are generated from the immutable snapshot on request.
            content = serialize(build_shapes_graph(OntologySnapshot.model_validate(version.snapshot).with_iris())[0], "turtle")
            derived = StoredArtifact(
                format="shapes",
                filename=f"{version.snapshot['metadata']['prefix']}-{version.version}.shapes.derived.ttl",
                path="",
                media_type="text/turtle",
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )
            return content, derived, True
        if fmt in RDF_EXPORT_FORMATS and "turtle" in version.artifacts:
            source = StoredArtifact(**version.artifacts["turtle"])
            try:
                turtle = self.artifacts.read(source)
            except ArtifactIntegrityError as error:
                raise ArtifactUnavailableError(str(error)) from error
            info = FORMATS[fmt]
            content = serialize(parse_rdf(turtle, "turtle"), fmt)
            derived = StoredArtifact(
                format=fmt,
                filename=f"{source.filename.rsplit('.', 1)[0]}.{info.extension}",
                path="",
                media_type=info.media_type,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )
            return content, derived, True
        raise NotFoundError(f"No '{fmt}' artifact exists for this version.", code="EXPORT_FORMAT_NOT_AVAILABLE")
