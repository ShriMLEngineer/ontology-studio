from datetime import datetime

from pydantic import BaseModel

from app.modules.ontology.schemas import OntologyRead
from app.modules.semantics.rdf_import import ImportReport


class ExtensionAxiomRead(BaseModel):
    id: str
    scope: str
    kind: str
    summary: str
    ntriples: str
    anchor_ids: list[str]
    missing_anchor_ids: list[str]
    orphaned: bool
    import_id: str | None
    created_at: datetime


class OntologyImportRead(BaseModel):
    id: str
    project_id: str
    ontology_id: str
    filename: str
    rdf_format: str
    sha256: str
    imported_by: str
    created_at: datetime
    report: ImportReport


class ImportResponse(BaseModel):
    ontology: OntologyRead
    import_record: OntologyImportRead
