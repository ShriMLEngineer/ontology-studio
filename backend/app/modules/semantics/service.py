"""Draft RDF export, RDF import, preserved-axiom management and entailment preview."""

import hashlib

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import new_id
from app.modules.activity.service import record_activity
from app.modules.ontology.models import Ontology, OntologyExtensionAxiomRecord, OntologyImportRecord
from app.modules.ontology.schemas import OntologyCreate
from app.modules.ontology.service import OntologyService
from app.modules.registry.snapshot import OntologySnapshot, build_snapshot, metadata_from_ontology
from app.modules.semantics.graphs import FORMATS, FormatInfo, detect_format, parse_rdf, serialize
from app.modules.semantics.owl import snapshot_to_owl
from app.modules.semantics.rdf_import import ImportReport, import_graph
from app.modules.semantics.reasoning import EntailmentReport, entailment_preview
from app.modules.semantics.schemas import ExtensionAxiomRead, ImportResponse, OntologyImportRead


class SemanticsService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.ontologies = OntologyService(session)

    # ------------------------------------------------------------------------------ draft graph

    def draft_snapshot(self, ontology_id: str) -> tuple[Ontology, OntologySnapshot]:
        ontology, schema = self.ontologies.get_schema(ontology_id)
        return ontology, build_snapshot(metadata_from_ontology(ontology), schema)

    def export_draft(self, ontology_id: str, rdf_format: str) -> tuple[bytes, FormatInfo, str]:
        ontology, snapshot = self.draft_snapshot(ontology_id)
        info = FORMATS[rdf_format]
        content = serialize(snapshot_to_owl(snapshot), rdf_format)
        return content, info, f"{ontology.prefix}-draft-r{ontology.draft_revision}.{info.extension}"

    def entailments(self, ontology_id: str) -> EntailmentReport:
        _, snapshot = self.draft_snapshot(ontology_id)
        return entailment_preview(snapshot_to_owl(snapshot))

    # ------------------------------------------------------------------------------ axioms

    def list_axioms(self, ontology_id: str) -> list[ExtensionAxiomRead]:
        self.ontologies._require(ontology_id)
        element_ids = self.ontologies.repo.element_ids(ontology_id)
        result = []
        for record in self.ontologies.repo.extension_axioms(ontology_id):
            missing = [a for a in record.anchor_ids or [] if a not in element_ids]
            result.append(
                ExtensionAxiomRead(
                    id=record.id,
                    scope=record.scope,
                    kind=record.kind,
                    summary=record.summary,
                    ntriples=record.ntriples,
                    anchor_ids=record.anchor_ids or [],
                    missing_anchor_ids=missing,
                    orphaned=bool(missing),
                    import_id=record.import_id,
                    created_at=record.created_at,
                )
            )
        return result

    def delete_axiom(self, ontology_id: str, axiom_id: str, deleted_by: str = "") -> None:
        ontology = self.ontologies._require(ontology_id)
        record = self.session.get(OntologyExtensionAxiomRecord, axiom_id)
        if record is None or record.ontology_id != ontology_id:
            raise NotFoundError(f"Preserved axiom '{axiom_id}' was not found.", code="AXIOM_NOT_FOUND")
        self.session.delete(record)
        self.ontologies._touch(ontology)
        self.ontologies._activity(
            ontology,
            "ontology.axiom_removed",
            f"Preserved axiom removed: {record.summary}",
            {"axiom_id": record.id, "kind": record.kind, "ntriples": record.ntriples, "removed_by": deleted_by},
        )
        self.session.commit()

    # ------------------------------------------------------------------------------ import

    def list_imports(self, ontology_id: str) -> list[OntologyImportRead]:
        self.ontologies._require(ontology_id)
        stmt = (
            select(OntologyImportRecord)
            .where(OntologyImportRecord.ontology_id == ontology_id)
            .order_by(OntologyImportRecord.created_at.desc())
        )
        return [self._import_read(r) for r in self.session.scalars(stmt)]

    @staticmethod
    def _import_read(record: OntologyImportRecord) -> OntologyImportRead:
        return OntologyImportRead(
            id=record.id,
            project_id=record.project_id,
            ontology_id=record.ontology_id,
            filename=record.filename,
            rdf_format=record.rdf_format,
            sha256=record.sha256,
            imported_by=record.imported_by,
            created_at=record.created_at,
            report=ImportReport.model_validate(record.report),
        )

    def import_rdf(
        self,
        project_id: str,
        *,
        filename: str,
        data: bytes,
        rdf_format: str | None = None,
        name: str | None = None,
        namespace: str | None = None,
        prefix: str | None = None,
        imported_by: str = "",
        ontology_id: str | None = None,
    ) -> ImportResponse:
        """Import an RDF document into a new ontology, or into an existing *empty* draft (D10)."""
        fmt = detect_format(filename, rdf_format)
        target: Ontology | None = None
        if ontology_id:
            target = self.ontologies._require(ontology_id)
            if target.project_id != project_id:
                raise NotFoundError("The ontology does not belong to this project.", code="ONTOLOGY_NOT_FOUND")
            if self.ontologies.repo.element_ids(target.id) or self.ontologies.repo.extension_axioms(target.id):
                raise ConflictError(
                    "RDF can only be imported into a new ontology or an empty draft. Create a new ontology, or "
                    "clear this draft first.",
                    code="IMPORT_TARGET_NOT_EMPTY",
                )
        else:
            self.ontologies._require_project(project_id)

        graph = parse_rdf(data, fmt)
        result = import_graph(
            graph,
            rdf_format=fmt,
            name=name or (target.name if target else None),
            namespace=namespace,
            prefix=prefix,
            filename=filename,
        )
        metadata = result.metadata

        if target is None:
            final_name = metadata.name
            if not name:
                n = 2
                while self.ontologies.repo.name_taken(project_id, final_name):
                    final_name, n = f"{metadata.name} ({n})", n + 1
            try:
                payload = OntologyCreate(
                    name=final_name,
                    namespace=metadata.namespace,
                    prefix=metadata.prefix,
                    description=metadata.description,
                    ontology_iri=metadata.ontology_iri,
                    prefixes=metadata.prefixes,
                    imports=metadata.imports,
                )
            except PydanticValidationError as exc:
                raise BusinessRuleError(
                    "The imported ontology header is not valid. Provide a name, namespace and prefix explicitly.",
                    code="IMPORT_HEADER_INVALID",
                    details={"errors": exc.errors(include_url=False, include_context=False)},
                ) from exc
            created = self.ontologies.create_ontology(project_id, payload, commit=False)
            ontology = self.ontologies._require(created.id)
        else:
            ontology = target
            old_namespace = ontology.namespace
            ontology.namespace = metadata.namespace
            ontology.prefix = metadata.prefix
            ontology.description = metadata.description or ontology.description
            ontology.ontology_iri = metadata.ontology_iri
            ontology.prefixes = [p.model_dump() for p in metadata.prefixes]
            ontology.imports = list(metadata.imports)
            if old_namespace != ontology.namespace:
                self.ontologies._follow_namespace(ontology, old_namespace)

        record = OntologyImportRecord(
            id=new_id(),
            project_id=project_id,
            ontology_id=ontology.id,
            filename=filename[:255],
            rdf_format=fmt,
            sha256=hashlib.sha256(data).hexdigest(),
            report=result.report.model_dump(mode="json"),
            imported_by=imported_by[:200],
        )
        self.session.add(record)

        schema = result.schema_
        for index, axiom in enumerate(schema.extension_axioms):
            self.session.add(
                OntologyExtensionAxiomRecord(
                    id=new_id(),
                    ontology_id=ontology.id,
                    scope=axiom.scope,
                    kind=axiom.kind,
                    summary=axiom.summary,
                    ntriples=axiom.ntriples,
                    anchor_ids=list(axiom.anchor_ids),
                    import_id=record.id,
                    sort_order=index,
                )
            )
        report = result.report
        self.ontologies.replace_schema(
            ontology,
            schema,
            event_type="ontology.imported",
            summary=f"Imported {filename} ({fmt}): {report.consumed_triples} triples modelled, "
            f"{report.preserved_triples} preserved as {report.preserved_axioms} axiom(s)",
            details={"import_id": record.id},
        )
        if not schema.classes and not schema.object_properties and not schema.datatype_properties:
            self.ontologies._touch(ontology)
        record_activity(
            self.session,
            project_id=project_id,
            ontology_id=ontology.id,
            event_type="ontology.rdf_imported",
            summary=f"RDF document '{filename}' imported into '{ontology.name}'",
            details={"import_id": record.id, "lossless": report.lossless, "imported_by": imported_by},
        )
        self.session.commit()
        return ImportResponse(ontology=self.ontologies.get_ontology(ontology.id), import_record=self._import_read(record))
