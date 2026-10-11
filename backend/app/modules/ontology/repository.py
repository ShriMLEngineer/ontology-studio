from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
)
from app.modules.ontology.models import (
    DatatypePropertyRecord,
    ObjectPropertyRecord,
    Ontology,
    OntologyClassRecord,
    OntologyDiagramLayout,
)
from app.modules.ontology.schemas import OntologyStats

ElementRecord = OntologyClassRecord | ObjectPropertyRecord | DatatypePropertyRecord
ELEMENT_MODELS: tuple[type[ElementRecord], ...] = (
    OntologyClassRecord,
    ObjectPropertyRecord,
    DatatypePropertyRecord,
)

CLASS_FIELDS = ("local_name", "label", "description", "aliases", "parent_ids")
OBJECT_PROPERTY_FIELDS = ("local_name", "label", "description", "aliases", "domain_id", "range_id")
DATATYPE_PROPERTY_FIELDS = (
    "local_name",
    "label",
    "description",
    "aliases",
    "domain_id",
    "datatype",
    "required",
    "multi_valued",
)


def _values(record: Any, fields: Iterable[str]) -> dict[str, Any]:
    return {f: getattr(record, f) for f in fields}


def to_class_definition(record: OntologyClassRecord) -> ClassDefinition:
    return ClassDefinition.model_validate({"id": record.id, **_values(record, CLASS_FIELDS)})


def to_object_property_definition(record: ObjectPropertyRecord) -> ObjectPropertyDefinition:
    return ObjectPropertyDefinition.model_validate(
        {"id": record.id, **_values(record, OBJECT_PROPERTY_FIELDS)}
    )


def to_datatype_property_definition(record: DatatypePropertyRecord) -> DatatypePropertyDefinition:
    return DatatypePropertyDefinition.model_validate(
        {"id": record.id, **_values(record, DATATYPE_PROPERTY_FIELDS)}
    )


class OntologyRepository:
    """Storage access for ontologies and their draft elements."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- ontologies ---------------------------------------------------------------------------

    def get(self, ontology_id: str) -> Ontology | None:
        return self.session.get(Ontology, ontology_id)

    def list_for_project(self, project_id: str) -> list[Ontology]:
        stmt = (
            select(Ontology)
            .where(Ontology.project_id == project_id)
            .order_by(Ontology.created_at, Ontology.name)
        )
        return list(self.session.scalars(stmt))

    def name_taken(self, project_id: str, name: str, exclude_id: str | None = None) -> bool:
        stmt = select(Ontology.id).where(
            Ontology.project_id == project_id, func.lower(Ontology.name) == name.lower()
        )
        if exclude_id:
            stmt = stmt.where(Ontology.id != exclude_id)
        return self.session.scalars(stmt).first() is not None

    def add(self, ontology: Ontology) -> Ontology:
        self.session.add(ontology)
        self.session.flush()
        return ontology

    def delete(self, ontology: Ontology) -> None:
        self.session.delete(ontology)

    def count_by_project(self) -> dict[str, int]:
        stmt = select(Ontology.project_id, func.count()).group_by(Ontology.project_id)
        return {project_id: count for project_id, count in self.session.execute(stmt).all()}

    def stats(self, ontology_ids: list[str]) -> dict[str, OntologyStats]:
        result = {oid: OntologyStats() for oid in ontology_ids}
        if not ontology_ids:
            return result
        for model, attr in (
            (OntologyClassRecord, "class_count"),
            (ObjectPropertyRecord, "object_property_count"),
            (DatatypePropertyRecord, "datatype_property_count"),
        ):
            stmt = (
                select(model.ontology_id, func.count())
                .where(model.ontology_id.in_(ontology_ids))
                .group_by(model.ontology_id)
            )
            for oid, count in self.session.execute(stmt).all():
                setattr(result[oid], attr, count)
        return result

    # -- elements -----------------------------------------------------------------------------

    def _list(self, model: type[ElementRecord], ontology_id: str) -> list[Any]:
        stmt = (
            select(model)
            .where(model.ontology_id == ontology_id)
            .order_by(model.sort_order, model.created_at, model.id)
        )
        return list(self.session.scalars(stmt))

    def classes(self, ontology_id: str) -> list[OntologyClassRecord]:
        return self._list(OntologyClassRecord, ontology_id)

    def object_properties(self, ontology_id: str) -> list[ObjectPropertyRecord]:
        return self._list(ObjectPropertyRecord, ontology_id)

    def datatype_properties(self, ontology_id: str) -> list[DatatypePropertyRecord]:
        return self._list(DatatypePropertyRecord, ontology_id)

    def get_class(self, ontology_id: str, class_id: str) -> OntologyClassRecord | None:
        return self.session.get(OntologyClassRecord, (ontology_id, class_id))

    def get_object_property(self, ontology_id: str, prop_id: str) -> ObjectPropertyRecord | None:
        return self.session.get(ObjectPropertyRecord, (ontology_id, prop_id))

    def get_datatype_property(
        self, ontology_id: str, prop_id: str
    ) -> DatatypePropertyRecord | None:
        return self.session.get(DatatypePropertyRecord, (ontology_id, prop_id))

    def element_ids(self, ontology_id: str) -> set[str]:
        ids: set[str] = set()
        for model in ELEMENT_MODELS:
            ids.update(self.session.scalars(select(model.id).where(model.ontology_id == ontology_id)))
        return ids

    def local_name_owner(self, ontology_id: str, local_name: str) -> str | None:
        """Return the id of the element using ``local_name`` (exact match), if any."""
        for model in ELEMENT_MODELS:
            stmt = select(model.id).where(
                model.ontology_id == ontology_id, model.local_name == local_name
            )
            owner = self.session.scalars(stmt).first()
            if owner is not None:
                return owner
        return None

    def next_sort_order(self, model: type[ElementRecord], ontology_id: str) -> int:
        stmt = select(func.max(model.sort_order)).where(model.ontology_id == ontology_id)
        current = self.session.scalar(stmt)
        return 0 if current is None else current + 1

    def add_element(self, record: ElementRecord) -> None:
        self.session.add(record)

    def delete_element(self, record: ElementRecord) -> None:
        self.session.delete(record)

    # -- layout -------------------------------------------------------------------------------

    def get_layout(self, ontology_id: str) -> OntologyDiagramLayout:
        layout = self.session.get(OntologyDiagramLayout, ontology_id)
        if layout is None:
            layout = OntologyDiagramLayout(ontology_id=ontology_id, positions={})
            self.session.add(layout)
        return layout

    # -- canonical schema ---------------------------------------------------------------------

    def load_schema(self, ontology: Ontology) -> OntologySchema:
        return OntologySchema(
            namespace=ontology.namespace,
            prefix=ontology.prefix,
            classes=[to_class_definition(r) for r in self.classes(ontology.id)],
            object_properties=[
                to_object_property_definition(r) for r in self.object_properties(ontology.id)
            ],
            datatype_properties=[
                to_datatype_property_definition(r) for r in self.datatype_properties(ontology.id)
            ],
        )
