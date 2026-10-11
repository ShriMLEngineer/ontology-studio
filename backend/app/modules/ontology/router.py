from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
)
from app.modules.ontology.schemas import (
    ClassCreate,
    ClassDeletionResult,
    ClassUpdate,
    DatatypePropertyCreate,
    DatatypePropertyUpdate,
    DraftSaveRequest,
    DraftSaveResponse,
    ObjectPropertyCreate,
    ObjectPropertyUpdate,
    OntologyCreate,
    OntologyDraft,
    OntologyRead,
    OntologyUpdate,
)
from app.modules.ontology.service import OntologyService

router = APIRouter(tags=["ontologies"])


def get_ontology_service(session: Annotated[Session, Depends(get_session)]) -> OntologyService:
    return OntologyService(session)


Service = Annotated[OntologyService, Depends(get_ontology_service)]


# ------------------------------------------------------------------------------ ontologies


@router.get("/projects/{project_id}/ontologies", response_model=list[OntologyRead])
def list_ontologies(project_id: str, service: Service) -> list[OntologyRead]:
    return service.list_ontologies(project_id)


@router.post(
    "/projects/{project_id}/ontologies",
    response_model=OntologyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_ontology(project_id: str, data: OntologyCreate, service: Service) -> OntologyRead:
    return service.create_ontology(project_id, data)


@router.get("/ontologies/{ontology_id}", response_model=OntologyRead)
def get_ontology(ontology_id: str, service: Service) -> OntologyRead:
    return service.get_ontology(ontology_id)


@router.patch("/ontologies/{ontology_id}", response_model=OntologyRead)
def update_ontology(ontology_id: str, data: OntologyUpdate, service: Service) -> OntologyRead:
    return service.update_ontology(ontology_id, data)


@router.delete("/ontologies/{ontology_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ontology(ontology_id: str, service: Service) -> Response:
    service.delete_ontology(ontology_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------ draft


@router.get("/ontologies/{ontology_id}/draft", response_model=OntologyDraft)
def get_draft(ontology_id: str, service: Service) -> OntologyDraft:
    return service.get_draft(ontology_id)


@router.put(
    "/ontologies/{ontology_id}/draft",
    response_model=DraftSaveResponse,
    responses={409: {"description": "Draft revision conflict (optimistic lock)"}},
)
def save_draft(ontology_id: str, data: DraftSaveRequest, service: Service) -> DraftSaveResponse:
    return service.save_draft(ontology_id, data)


# ------------------------------------------------------------------------------ classes


@router.get("/ontologies/{ontology_id}/classes", response_model=list[ClassDefinition])
def list_classes(ontology_id: str, service: Service) -> list[ClassDefinition]:
    return service.list_classes(ontology_id)


@router.post(
    "/ontologies/{ontology_id}/classes",
    response_model=ClassDefinition,
    status_code=status.HTTP_201_CREATED,
)
def create_class(ontology_id: str, data: ClassCreate, service: Service) -> ClassDefinition:
    return service.create_class(ontology_id, data)


@router.get("/ontologies/{ontology_id}/classes/{class_id}", response_model=ClassDefinition)
def get_class(ontology_id: str, class_id: str, service: Service) -> ClassDefinition:
    return service.get_class(ontology_id, class_id)


@router.patch("/ontologies/{ontology_id}/classes/{class_id}", response_model=ClassDefinition)
def update_class(
    ontology_id: str, class_id: str, data: ClassUpdate, service: Service
) -> ClassDefinition:
    return service.update_class(ontology_id, class_id, data)


@router.delete(
    "/ontologies/{ontology_id}/classes/{class_id}",
    response_model=ClassDeletionResult,
    responses={409: {"description": "Class has dependents and cascade=false"}},
)
def delete_class(
    ontology_id: str,
    class_id: str,
    service: Service,
    cascade: Annotated[bool, Query(description="Also remove dependent properties")] = False,
) -> ClassDeletionResult:
    return service.delete_class(ontology_id, class_id, cascade)


# ------------------------------------------------------------------------------ object properties


@router.get(
    "/ontologies/{ontology_id}/object-properties", response_model=list[ObjectPropertyDefinition]
)
def list_object_properties(ontology_id: str, service: Service) -> list[ObjectPropertyDefinition]:
    return service.list_object_properties(ontology_id)


@router.post(
    "/ontologies/{ontology_id}/object-properties",
    response_model=ObjectPropertyDefinition,
    status_code=status.HTTP_201_CREATED,
)
def create_object_property(
    ontology_id: str, data: ObjectPropertyCreate, service: Service
) -> ObjectPropertyDefinition:
    return service.create_object_property(ontology_id, data)


@router.get(
    "/ontologies/{ontology_id}/object-properties/{prop_id}",
    response_model=ObjectPropertyDefinition,
)
def get_object_property(ontology_id: str, prop_id: str, service: Service) -> ObjectPropertyDefinition:
    return service.get_object_property(ontology_id, prop_id)


@router.patch(
    "/ontologies/{ontology_id}/object-properties/{prop_id}",
    response_model=ObjectPropertyDefinition,
)
def update_object_property(
    ontology_id: str, prop_id: str, data: ObjectPropertyUpdate, service: Service
) -> ObjectPropertyDefinition:
    return service.update_object_property(ontology_id, prop_id, data)


@router.delete(
    "/ontologies/{ontology_id}/object-properties/{prop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_object_property(ontology_id: str, prop_id: str, service: Service) -> Response:
    service.delete_object_property(ontology_id, prop_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------ datatype properties


@router.get(
    "/ontologies/{ontology_id}/datatype-properties",
    response_model=list[DatatypePropertyDefinition],
)
def list_datatype_properties(
    ontology_id: str, service: Service
) -> list[DatatypePropertyDefinition]:
    return service.list_datatype_properties(ontology_id)


@router.post(
    "/ontologies/{ontology_id}/datatype-properties",
    response_model=DatatypePropertyDefinition,
    status_code=status.HTTP_201_CREATED,
)
def create_datatype_property(
    ontology_id: str, data: DatatypePropertyCreate, service: Service
) -> DatatypePropertyDefinition:
    return service.create_datatype_property(ontology_id, data)


@router.get(
    "/ontologies/{ontology_id}/datatype-properties/{prop_id}",
    response_model=DatatypePropertyDefinition,
)
def get_datatype_property(
    ontology_id: str, prop_id: str, service: Service
) -> DatatypePropertyDefinition:
    return service.get_datatype_property(ontology_id, prop_id)


@router.patch(
    "/ontologies/{ontology_id}/datatype-properties/{prop_id}",
    response_model=DatatypePropertyDefinition,
)
def update_datatype_property(
    ontology_id: str, prop_id: str, data: DatatypePropertyUpdate, service: Service
) -> DatatypePropertyDefinition:
    return service.update_datatype_property(ontology_id, prop_id, data)


@router.delete(
    "/ontologies/{ontology_id}/datatype-properties/{prop_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_datatype_property(ontology_id: str, prop_id: str, service: Service) -> Response:
    service.delete_datatype_property(ontology_id, prop_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
