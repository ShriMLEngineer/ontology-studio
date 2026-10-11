from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.session import get_session
from app.modules.semantics.graphs import RdfFormat
from app.modules.semantics.reasoning import EntailmentReport
from app.modules.semantics.schemas import ExtensionAxiomRead, ImportResponse, OntologyImportRead
from app.modules.semantics.service import SemanticsService

router = APIRouter(tags=["semantics"])

MAX_RDF_UPLOAD_BYTES = 10 * 1024 * 1024


class RdfTooLargeError(DomainError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "RDF_TOO_LARGE"


def get_semantics_service(session: Annotated[Session, Depends(get_session)]) -> SemanticsService:
    return SemanticsService(session)


Service = Annotated[SemanticsService, Depends(get_semantics_service)]


@router.get("/ontologies/{ontology_id}/rdf", response_class=Response)
def export_draft_rdf(
    ontology_id: str,
    service: Service,
    fmt: Annotated[RdfFormat, Query(alias="format")] = "turtle",
    download: bool = False,
) -> Response:
    """The current draft as OWL 2 (OLS Semantic Profile + preserved axioms)."""
    content, info, filename = service.export_draft(ontology_id, fmt)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
    return Response(content=content, media_type=info.media_type, headers=headers)


@router.get("/ontologies/{ontology_id}/entailments", response_model=EntailmentReport)
def entailments(ontology_id: str, service: Service) -> EntailmentReport:
    """OWL 2 RL entailment preview. Informational: nothing is written back."""
    return service.entailments(ontology_id)


@router.get("/ontologies/{ontology_id}/axioms", response_model=list[ExtensionAxiomRead])
def list_axioms(ontology_id: str, service: Service) -> list[ExtensionAxiomRead]:
    return service.list_axioms(ontology_id)


@router.delete("/ontologies/{ontology_id}/axioms/{axiom_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_axiom(ontology_id: str, axiom_id: str, service: Service, deleted_by: str = "") -> Response:
    service.delete_axiom(ontology_id, axiom_id, deleted_by)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/ontologies/{ontology_id}/imports", response_model=list[OntologyImportRead])
def list_imports(ontology_id: str, service: Service) -> list[OntologyImportRead]:
    return service.list_imports(ontology_id)


@router.post(
    "/projects/{project_id}/ontologies/import",
    response_model=ImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_rdf(
    project_id: str,
    request: Request,
    file: UploadFile,
    service: Service,
    rdf_format: Annotated[RdfFormat | None, Form()] = None,
    name: Annotated[str, Form()] = "",
    namespace: Annotated[str, Form()] = "",
    prefix: Annotated[str, Form()] = "",
    imported_by: Annotated[str, Form()] = "",
    ontology_id: Annotated[str, Form()] = "",
) -> ImportResponse:
    """Import Turtle, RDF/XML, JSON-LD or N-Triples into a new ontology (or an empty draft).

    Constructs outside the OLS Semantic Profile are preserved as extension axioms; the response
    contains the import report (modelled, preserved, superseded and added triples).
    """
    content = await file.read(MAX_RDF_UPLOAD_BYTES + 1)
    if len(content) > MAX_RDF_UPLOAD_BYTES:
        raise RdfTooLargeError(f"RDF documents are limited to {MAX_RDF_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return service.import_rdf(
        project_id,
        filename=file.filename or "ontology.ttl",
        data=content,
        rdf_format=rdf_format,
        name=name.strip() or None,
        namespace=namespace.strip() or None,
        prefix=prefix.strip() or None,
        imported_by=imported_by.strip(),
        ontology_id=ontology_id.strip() or None,
    )
