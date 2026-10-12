"""Ontology authoring service.

Two write paths share the same storage and invariants:

* **Granular commands** (create/update/delete a class or property) enforce their own
  preconditions: unique element ids and local names, references to existing classes and an
  acyclic class hierarchy.
* **Draft save** atomically replaces the whole working copy, as produced by the visual
  designer, guarded by optimistic concurrency on ``draft_revision``. Drafts may contain
  work-in-progress inconsistencies; the validation module reports them.

Every semantic change increments ``draft_revision`` and is recorded in the activity log.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.ids import new_element_id, utcnow
from app.modules.activity.service import record_activity
from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
    to_class_local_name,
    to_property_local_name,
)
from app.modules.ontology.models import (
    DatatypePropertyRecord,
    ObjectPropertyRecord,
    Ontology,
    OntologyClassRecord,
)
from app.modules.ontology.repository import (
    CLASS_FIELDS,
    DATATYPE_PROPERTY_FIELDS,
    OBJECT_PROPERTY_FIELDS,
    ElementRecord,
    OntologyRepository,
    to_class_definition,
    to_datatype_property_definition,
    to_object_property_definition,
)
from app.modules.ontology.schemas import (
    ClassCreate,
    ClassDeletionResult,
    ClassUpdate,
    DatatypePropertyCreate,
    DatatypePropertyUpdate,
    DiagramLayout,
    DraftChangeSummary,
    DraftSaveRequest,
    DraftSaveResponse,
    ElementChangeCounts,
    ObjectPropertyCreate,
    ObjectPropertyUpdate,
    OntologyCreate,
    OntologyDraft,
    OntologyRead,
    OntologyStats,
    OntologyUpdate,
)
from app.modules.projects.repository import ProjectRepository
from app.modules.registry.models import OntologyVersion


def _db_value(value: Any) -> Any:
    # StrEnum values are persisted as plain strings; lists are copied so JSON changes are detected.
    # Nested models (OWL semantics) are stored compactly so default semantics == legacy "{}".
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_defaults=True)
    if isinstance(value, list):
        return list(value)
    if hasattr(value, "value"):
        return value.value
    return value


HEADER_FIELDS = ("ontology_iri", "prefixes", "imports", "require_domain_range")


class OntologyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = OntologyRepository(session)
        self.projects = ProjectRepository(session)

    # ------------------------------------------------------------------------------ helpers

    def _require_project(self, project_id: str) -> None:
        if self.projects.get(project_id) is None:
            raise NotFoundError(f"Project '{project_id}' was not found.", code="PROJECT_NOT_FOUND")

    def _require(self, ontology_id: str) -> Ontology:
        ontology = self.repo.get(ontology_id)
        if ontology is None:
            raise NotFoundError(
                f"Ontology '{ontology_id}' was not found.", code="ONTOLOGY_NOT_FOUND"
            )
        return ontology

    def _to_read(self, ontology: Ontology, stats: OntologyStats | None = None) -> OntologyRead:
        if stats is None:
            stats = self.repo.stats([ontology.id])[ontology.id]
        return OntologyRead(
            id=ontology.id,
            project_id=ontology.project_id,
            name=ontology.name,
            namespace=ontology.namespace,
            prefix=ontology.prefix,
            description=ontology.description,
            ontology_iri=ontology.ontology_iri,
            prefixes=ontology.prefixes or [],
            imports=ontology.imports or [],
            require_domain_range=ontology.require_domain_range,
            draft_revision=ontology.draft_revision,
            stats=stats,
            latest_version=self.repo.latest_versions([ontology.id]).get(ontology.id),
            created_at=ontology.created_at,
            updated_at=ontology.updated_at,
        )

    def _touch(self, ontology: Ontology) -> None:
        ontology.draft_revision += 1
        ontology.updated_at = utcnow()

    def _activity(
        self,
        ontology: Ontology,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        record_activity(
            self.session,
            project_id=ontology.project_id,
            ontology_id=ontology.id,
            event_type=event_type,
            summary=summary,
            details={"draft_revision": ontology.draft_revision, **(details or {})},
        )

    def _ensure_new_element_id(self, ontology_id: str, element_id: str) -> None:
        if element_id in self.repo.element_ids(ontology_id):
            raise ConflictError(
                f"Element id '{element_id}' is already used in this ontology.",
                code="ELEMENT_ID_TAKEN",
                details={"id": element_id},
            )

    def _ensure_local_name_available(
        self, ontology_id: str, local_name: str, exclude_id: str | None = None
    ) -> None:
        owner = self.repo.local_name_owner(ontology_id, local_name)
        if owner is not None and owner != exclude_id:
            raise ConflictError(
                f"Local name '{local_name}' is already used by another element.",
                code="LOCAL_NAME_TAKEN",
                details={"local_name": local_name, "element_id": owner},
            )

    def _ensure_classes_exist(self, ontology_id: str, field: str, class_ids: Iterable[str]) -> None:
        missing = [cid for cid in class_ids if self.repo.get_class(ontology_id, cid) is None]
        if missing:
            raise BusinessRuleError(
                f"'{field}' references unknown class id(s): {', '.join(missing)}.",
                code="UNKNOWN_CLASS_REFERENCE",
                details={"field": field, "missing_class_ids": missing},
            )

    def _ensure_acyclic(self, ontology_id: str, class_id: str, parent_ids: Sequence[str]) -> None:
        parents = {c.id: list(c.parent_ids) for c in self.repo.classes(ontology_id)}
        parents[class_id] = list(parent_ids)
        stack, seen = list(parent_ids), set()
        while stack:
            current = stack.pop()
            if current == class_id:
                raise BusinessRuleError(
                    "The requested parent classes would create a cycle in the class hierarchy.",
                    code="CLASS_HIERARCHY_CYCLE",
                    details={"class_id": class_id, "parent_ids": list(parent_ids)},
                )
            if current not in seen:
                seen.add(current)
                stack.extend(parents.get(current, []))

    # ------------------------------------------------------------------------------ ontologies

    def list_ontologies(self, project_id: str) -> list[OntologyRead]:
        self._require_project(project_id)
        ontologies = self.repo.list_for_project(project_id)
        stats = self.repo.stats([o.id for o in ontologies])
        return [self._to_read(o, stats[o.id]) for o in ontologies]

    def create_ontology(
        self, project_id: str, data: OntologyCreate, *, commit: bool = True
    ) -> OntologyRead:
        self._require_project(project_id)
        if self.repo.name_taken(project_id, data.name):
            raise ConflictError(
                f"An ontology named '{data.name}' already exists in this project.",
                code="ONTOLOGY_NAME_TAKEN",
            )
        ontology = self.repo.add(
            Ontology(
                project_id=project_id,
                name=data.name,
                namespace=data.namespace,
                prefix=data.prefix,
                description=data.description,
                ontology_iri=data.ontology_iri or None,
                prefixes=[p.model_dump() for p in data.prefixes],
                imports=list(data.imports),
                require_domain_range=data.require_domain_range,
                draft_revision=1,
            )
        )
        self.repo.get_layout(ontology.id)
        self._activity(ontology, "ontology.created", f"Ontology '{ontology.name}' created")
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return self._to_read(ontology, OntologyStats())

    def get_ontology(self, ontology_id: str) -> OntologyRead:
        return self._to_read(self._require(ontology_id))

    def update_ontology(self, ontology_id: str, data: OntologyUpdate) -> OntologyRead:
        ontology = self._require(ontology_id)
        requested = data.model_dump(exclude_unset=True, exclude_none=True)
        changed = {k: v for k, v in requested.items() if getattr(ontology, k) != v}
        if "name" in changed and self.repo.name_taken(
            ontology.project_id, changed["name"], exclude_id=ontology.id
        ):
            raise ConflictError(
                f"An ontology named '{changed['name']}' already exists in this project.",
                code="ONTOLOGY_NAME_TAKEN",
            )
        if changed:
            old_namespace = ontology.namespace
            for key, value in changed.items():
                setattr(ontology, key, value)
            if "namespace" in changed:
                self._follow_namespace(ontology, old_namespace)
            self._touch(ontology)
            self._activity(
                ontology,
                "ontology.metadata_updated",
                f"Ontology metadata updated ({', '.join(sorted(changed))})",
            )
            self.session.commit()
        return self._to_read(ontology)

    def delete_ontology(self, ontology_id: str) -> None:
        ontology = self._require(ontology_id)
        published = self.repo.version_count(ontology.id)
        if published:
            raise ConflictError(
                f"Ontology '{ontology.name}' has {published} published version(s). Published versions are "
                "immutable records and cannot be deleted.",
                code="ONTOLOGY_HAS_PUBLISHED_VERSIONS",
                details={"published_versions": published},
            )
        record_activity(
            self.session,
            project_id=ontology.project_id,
            event_type="ontology.deleted",
            summary=f"Ontology '{ontology.name}' deleted",
            details={"ontology_id": ontology.id},
        )
        self.repo.delete(ontology)
        self.session.commit()

    # ------------------------------------------------------------------------------ draft

    def get_schema(self, ontology_id: str) -> tuple[Ontology, OntologySchema]:
        ontology = self._require(ontology_id)
        return ontology, self.repo.load_schema(ontology)

    def get_draft(self, ontology_id: str) -> OntologyDraft:
        ontology, schema = self.get_schema(ontology_id)
        layout = self.repo.get_layout(ontology.id)
        return OntologyDraft(
            ontology=self._to_read(
                ontology,
                OntologyStats(
                    class_count=len(schema.classes),
                    object_property_count=len(schema.object_properties),
                    datatype_property_count=len(schema.datatype_properties),
                ),
            ),
            draft_revision=ontology.draft_revision,
            classes=schema.classes,
            object_properties=schema.object_properties,
            datatype_properties=schema.datatype_properties,
            layout=DiagramLayout.model_validate({"positions": layout.positions or {}}),
            locked_iri_ids=sorted(self.locked_iris(ontology.id)),
        )

    def save_draft(self, ontology_id: str, request: DraftSaveRequest) -> DraftSaveResponse:
        ontology = self._require(ontology_id)
        if request.base_revision != ontology.draft_revision:
            raise ConflictError(
                "The draft has changed since you loaded it. Reload the latest draft and "
                "re-apply your changes.",
                code="DRAFT_REVISION_CONFLICT",
                details={
                    "base_revision": request.base_revision,
                    "current_revision": ontology.draft_revision,
                },
            )
        self._ensure_unique_ids(request)

        changes = DraftChangeSummary()
        old_namespace = ontology.namespace
        header_sent = request.metadata.model_fields_set & set(HEADER_FIELDS)
        metadata = request.metadata.model_dump(
            mode="json", exclude={f for f in HEADER_FIELDS if f not in header_sent}
        )
        if "ontology_iri" in metadata:
            metadata["ontology_iri"] = metadata["ontology_iri"] or None
        changed_metadata = {k: v for k, v in metadata.items() if getattr(ontology, k) != v}
        if "name" in changed_metadata and self.repo.name_taken(
            ontology.project_id, changed_metadata["name"], exclude_id=ontology.id
        ):
            raise ConflictError(
                f"An ontology named '{changed_metadata['name']}' already exists in this project.",
                code="ONTOLOGY_NAME_TAKEN",
            )
        for key, value in changed_metadata.items():
            setattr(ontology, key, value)
        changes.metadata_changed = bool(changed_metadata)

        self._sync_schema(ontology, old_namespace, request.classes, request.object_properties, request.datatype_properties, changes)

        class_ids = {c.id for c in request.classes}
        positions = {
            cid: pos.model_dump() for cid, pos in request.layout.positions.items() if cid in class_ids
        }
        layout = self.repo.get_layout(ontology.id)
        if (layout.positions or {}) != positions:
            layout.positions = positions
            changes.layout_changed = True

        revision_incremented = changes.has_semantic_changes
        if revision_incremented:
            self._touch(ontology)
            self._activity(
                ontology,
                "ontology.draft_saved",
                f"Draft saved as revision {ontology.draft_revision}: {changes.describe()}",
                {"changes": changes.model_dump()},
            )
        self.session.commit()
        return DraftSaveResponse(
            draft=self.get_draft(ontology.id),
            changes=changes,
            revision_incremented=revision_incremented,
        )

    def replace_schema(
        self,
        ontology: Ontology,
        schema: OntologySchema,
        *,
        event_type: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> DraftChangeSummary:
        """Persist ``schema`` as the draft content without committing (caller owns the transaction).

        Used by governed workflows (e.g. applying approved proposals). New classes are placed below
        the existing diagram; positions of removed classes are pruned.
        """
        changes = DraftChangeSummary()
        self._sync_schema(
            ontology, ontology.namespace, schema.classes, schema.object_properties, schema.datatype_properties, changes
        )

        layout = self.repo.get_layout(ontology.id)
        class_ids = [c.id for c in schema.classes]
        positions = {k: v for k, v in (layout.positions or {}).items() if k in class_ids}
        missing = [cid for cid in class_ids if cid not in positions]
        if missing:
            xs = [p["x"] for p in positions.values()] or [0.0]
            ys = [p["y"] for p in positions.values()] or [-260.0]
            for index, cid in enumerate(missing):
                positions[cid] = {"x": min(xs) + (index % 5) * 280, "y": max(ys) + 260 + (index // 5) * 220}
        if positions != (layout.positions or {}):
            layout.positions = positions
            changes.layout_changed = True

        if changes.has_semantic_changes:
            self._touch(ontology)
            self._activity(
                ontology,
                event_type,
                f"{summary} (revision {ontology.draft_revision}): {changes.describe()}",
                {"changes": changes.model_dump(), **(details or {})},
            )
        return changes

    def locked_iris(self, ontology_id: str) -> dict[str, str]:
        """IRIs of elements in the latest published version: these can no longer change."""
        version = self.session.scalars(
            select(OntologyVersion)
            .where(OntologyVersion.ontology_id == ontology_id)
            .order_by(OntologyVersion.sequence.desc())
        ).first()
        if version is None:
            return {}
        snapshot = version.snapshot
        namespace = snapshot["metadata"]["namespace"]
        return {
            e["id"]: e.get("iri") or f"{namespace}{e['local_name']}"
            for key in ("classes", "object_properties", "datatype_properties")
            for e in snapshot.get(key, [])
        }

    def _assign_iris(
        self,
        namespace: str,
        old_namespace: str,
        elements: Sequence[Any],
        existing: Sequence[Any],
        locked: dict[str, str],
    ) -> list[Any]:
        """Mint, follow or lock element IRIs.

        * Published elements keep their IRI (``IRI_LOCKED`` if a client changes it).
        * Unpublished elements whose IRI is managed automatically follow namespace + local name.
        * Explicit IRIs (for example imported ones) are kept; a client that omits the IRI of an
          existing element keeps the stored IRI.
        """
        by_id = {record.id: record for record in existing}
        result = []
        for element in elements:
            record = by_id.get(element.id)
            if element.id in locked:
                # A draft IRI that already diverged before IRIs were persisted (namespace changed after the last
                # publication) is kept rather than silently rewritten; the publish diff flags it.
                stored = record.iri if record is not None else None
                iri = element.iri or stored or locked[element.id]
                if iri not in (locked[element.id], stored):
                    raise BusinessRuleError(
                        f"The IRI of '{element.label}' is locked because the element is published "
                        f"({locked[element.id]}).",
                        code="IRI_LOCKED",
                        details={"element_id": element.id, "iri": locked[element.id]},
                    )
            else:
                if record is None:
                    iri = element.iri or f"{namespace}{element.local_name}"
                else:
                    stored = record.iri or f"{old_namespace}{record.local_name}"
                    requested = element.iri or stored
                    automatic = requested == stored and stored == f"{old_namespace}{record.local_name}"
                    iri = f"{namespace}{element.local_name}" if automatic else requested
            result.append(element if element.iri == iri else element.model_copy(update={"iri": iri}))
        return result

    def _follow_namespace(self, ontology: Ontology, old_namespace: str) -> None:
        """After a namespace change, move automatically managed, unpublished IRIs to the new namespace."""
        locked = self.locked_iris(ontology.id)
        for records in (
            self.repo.classes(ontology.id),
            self.repo.object_properties(ontology.id),
            self.repo.datatype_properties(ontology.id),
        ):
            for record in records:
                if record.id not in locked and record.iri in (None, f"{old_namespace}{record.local_name}"):
                    record.iri = f"{ontology.namespace}{record.local_name}"

    def _sync_schema(
        self,
        ontology: Ontology,
        old_namespace: str,
        classes: Sequence[Any],
        object_properties: Sequence[Any],
        datatype_properties: Sequence[Any],
        changes: DraftChangeSummary,
    ) -> None:
        locked = self.locked_iris(ontology.id)
        for attr, model, existing, incoming, fields in (
            ("classes", OntologyClassRecord, self.repo.classes(ontology.id), classes, CLASS_FIELDS),
            ("object_properties", ObjectPropertyRecord, self.repo.object_properties(ontology.id), object_properties,
             OBJECT_PROPERTY_FIELDS),
            ("datatype_properties", DatatypePropertyRecord, self.repo.datatype_properties(ontology.id),
             datatype_properties, DATATYPE_PROPERTY_FIELDS),
        ):
            assigned = self._assign_iris(ontology.namespace, old_namespace, incoming, existing, locked)
            setattr(changes, attr, self._sync_elements(model, ontology.id, existing, assigned, fields))

    def _ensure_unique_ids(self, request: DraftSaveRequest) -> None:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for element in (*request.classes, *request.object_properties, *request.datatype_properties):
            if element.id in seen:
                duplicates.add(element.id)
            seen.add(element.id)
        if duplicates:
            raise BusinessRuleError(
                "Element ids must be unique within an ontology draft.",
                code="DUPLICATE_ELEMENT_ID",
                details={"duplicate_ids": sorted(duplicates)},
            )

    def _sync_elements(
        self,
        model: type[ElementRecord],
        ontology_id: str,
        existing: Sequence[ElementRecord],
        incoming: Sequence[BaseModel],
        fields: Sequence[str],
    ) -> ElementChangeCounts:
        counts = ElementChangeCounts()
        by_id = {record.id: record for record in existing}
        for index, element in enumerate(incoming):
            values = {f: _db_value(getattr(element, f)) for f in fields}
            record = by_id.pop(element.id, None)  # type: ignore[attr-defined]
            if record is not None and "semantics" in values and "semantics" not in element.model_fields_set:
                # Clients unaware of OWL semantics (older payloads) must not erase them.
                values["semantics"] = record.semantics
            if record is None:
                self.repo.add_element(
                    model(ontology_id=ontology_id, id=element.id, sort_order=index, **values)  # type: ignore[attr-defined]
                )
                counts.added += 1
                continue
            if any(getattr(record, f) != v for f, v in values.items()):
                for f, v in values.items():
                    setattr(record, f, v)
                counts.updated += 1
            if record.sort_order != index:
                record.sort_order = index
        for record in by_id.values():
            self.repo.delete_element(record)
            counts.removed += 1
        return counts

    # ------------------------------------------------------------------------------ classes

    def _require_class(self, ontology_id: str, class_id: str) -> OntologyClassRecord:
        record = self.repo.get_class(ontology_id, class_id)
        if record is None:
            raise NotFoundError(f"Class '{class_id}' was not found.", code="CLASS_NOT_FOUND")
        return record

    def list_classes(self, ontology_id: str) -> list[ClassDefinition]:
        self._require(ontology_id)
        return [to_class_definition(r) for r in self.repo.classes(ontology_id)]

    def get_class(self, ontology_id: str, class_id: str) -> ClassDefinition:
        self._require(ontology_id)
        return to_class_definition(self._require_class(ontology_id, class_id))

    def create_class(self, ontology_id: str, data: ClassCreate) -> ClassDefinition:
        ontology = self._require(ontology_id)
        element_id = data.id or new_element_id("cls")
        local_name = data.local_name or to_class_local_name(data.label)
        self._ensure_new_element_id(ontology_id, element_id)
        self._ensure_local_name_available(ontology_id, local_name)
        self._ensure_classes_exist(ontology_id, "parent_ids", data.parent_ids)
        definition = ClassDefinition(
            id=element_id,
            local_name=local_name,
            iri=f"{ontology.namespace}{local_name}",
            label=data.label,
            description=data.description,
            aliases=data.aliases,
            parent_ids=data.parent_ids,
        )
        self.repo.add_element(
            OntologyClassRecord(
                ontology_id=ontology_id,
                id=element_id,
                sort_order=self.repo.next_sort_order(OntologyClassRecord, ontology_id),
                **{f: _db_value(getattr(definition, f)) for f in CLASS_FIELDS},
            )
        )
        if data.position is not None:
            layout = self.repo.get_layout(ontology_id)
            layout.positions = {**(layout.positions or {}), element_id: data.position.model_dump()}
        self._touch(ontology)
        self._activity(ontology, "ontology.class_created", f"Class '{definition.label}' added")
        self.session.commit()
        return definition

    def update_class(self, ontology_id: str, class_id: str, data: ClassUpdate) -> ClassDefinition:
        ontology = self._require(ontology_id)
        record = self._require_class(ontology_id, class_id)
        requested = data.model_dump(exclude_unset=True, exclude_none=True)
        if "local_name" in requested:
            self._ensure_local_name_available(ontology_id, requested["local_name"], class_id)
        if "parent_ids" in requested:
            self._ensure_classes_exist(ontology_id, "parent_ids", requested["parent_ids"])
            self._ensure_acyclic(ontology_id, class_id, requested["parent_ids"])
        return self._apply_update(
            ontology, record, requested, to_class_definition, "ontology.class_updated", "Class"
        )

    def delete_class(self, ontology_id: str, class_id: str, cascade: bool = False) -> ClassDeletionResult:
        ontology = self._require(ontology_id)
        record = self._require_class(ontology_id, class_id)
        object_props = [
            p
            for p in self.repo.object_properties(ontology_id)
            if class_id in (p.domain_id, p.range_id)
        ]
        datatype_props = [p for p in self.repo.datatype_properties(ontology_id) if p.domain_id == class_id]
        children = [c for c in self.repo.classes(ontology_id) if class_id in (c.parent_ids or [])]
        if (object_props or datatype_props or children) and not cascade:
            raise ConflictError(
                f"Class '{record.label}' is referenced by other elements. Retry with cascade=true "
                "to remove dependent properties and detach subclasses.",
                code="CLASS_HAS_DEPENDENTS",
                details={
                    "object_property_ids": [p.id for p in object_props],
                    "datatype_property_ids": [p.id for p in datatype_props],
                    "child_class_ids": [c.id for c in children],
                },
            )
        for prop in (*object_props, *datatype_props):
            self.repo.delete_element(prop)
        for child in children:
            child.parent_ids = [pid for pid in child.parent_ids if pid != class_id]
        self._strip_semantic_references(ontology_id, {class_id, *(p.id for p in (*object_props, *datatype_props))})
        layout = self.repo.get_layout(ontology_id)
        if class_id in (layout.positions or {}):
            layout.positions = {k: v for k, v in layout.positions.items() if k != class_id}
        self.repo.delete_element(record)
        self._touch(ontology)
        self._activity(
            ontology,
            "ontology.class_deleted",
            f"Class '{record.label}' deleted"
            + (f" with {len(object_props) + len(datatype_props)} dependent properties" if cascade else ""),
        )
        self.session.commit()
        return ClassDeletionResult(
            deleted_class_id=class_id,
            removed_object_property_ids=[p.id for p in object_props],
            removed_datatype_property_ids=[p.id for p in datatype_props],
            detached_child_class_ids=[c.id for c in children],
            draft_revision=ontology.draft_revision,
        )

    # ------------------------------------------------------------------------------ object properties

    def _require_object_property(self, ontology_id: str, prop_id: str) -> ObjectPropertyRecord:
        record = self.repo.get_object_property(ontology_id, prop_id)
        if record is None:
            raise NotFoundError(
                f"Object property '{prop_id}' was not found.", code="OBJECT_PROPERTY_NOT_FOUND"
            )
        return record

    def list_object_properties(self, ontology_id: str) -> list[ObjectPropertyDefinition]:
        self._require(ontology_id)
        return [to_object_property_definition(r) for r in self.repo.object_properties(ontology_id)]

    def get_object_property(self, ontology_id: str, prop_id: str) -> ObjectPropertyDefinition:
        self._require(ontology_id)
        return to_object_property_definition(self._require_object_property(ontology_id, prop_id))

    def create_object_property(
        self, ontology_id: str, data: ObjectPropertyCreate
    ) -> ObjectPropertyDefinition:
        ontology = self._require(ontology_id)
        element_id = data.id or new_element_id("op")
        local_name = data.local_name or to_property_local_name(data.label)
        self._ensure_new_element_id(ontology_id, element_id)
        self._ensure_local_name_available(ontology_id, local_name)
        self._ensure_classes_exist(ontology_id, "domain_id", [data.domain_id])
        self._ensure_classes_exist(ontology_id, "range_id", [data.range_id])
        definition = ObjectPropertyDefinition(
            id=element_id,
            local_name=local_name,
            iri=f"{ontology.namespace}{local_name}",
            label=data.label,
            description=data.description,
            aliases=data.aliases,
            domain_id=data.domain_id,
            range_id=data.range_id,
        )
        self.repo.add_element(
            ObjectPropertyRecord(
                ontology_id=ontology_id,
                id=element_id,
                sort_order=self.repo.next_sort_order(ObjectPropertyRecord, ontology_id),
                **{f: _db_value(getattr(definition, f)) for f in OBJECT_PROPERTY_FIELDS},
            )
        )
        self._touch(ontology)
        self._activity(
            ontology, "ontology.relationship_created", f"Relationship '{definition.label}' added"
        )
        self.session.commit()
        return definition

    def update_object_property(
        self, ontology_id: str, prop_id: str, data: ObjectPropertyUpdate
    ) -> ObjectPropertyDefinition:
        ontology = self._require(ontology_id)
        record = self._require_object_property(ontology_id, prop_id)
        requested = data.model_dump(exclude_unset=True, exclude_none=True)
        if "local_name" in requested:
            self._ensure_local_name_available(ontology_id, requested["local_name"], prop_id)
        for field in ("domain_id", "range_id"):
            if field in requested:
                self._ensure_classes_exist(ontology_id, field, [requested[field]])
        return self._apply_update(
            ontology,
            record,
            requested,
            to_object_property_definition,
            "ontology.relationship_updated",
            "Relationship",
        )

    def delete_object_property(self, ontology_id: str, prop_id: str) -> None:
        ontology = self._require(ontology_id)
        record = self._require_object_property(ontology_id, prop_id)
        self.repo.delete_element(record)
        self._strip_semantic_references(ontology_id, {prop_id})
        self._touch(ontology)
        self._activity(
            ontology, "ontology.relationship_deleted", f"Relationship '{record.label}' deleted"
        )
        self.session.commit()

    # ------------------------------------------------------------------------------ datatype properties

    def _require_datatype_property(self, ontology_id: str, prop_id: str) -> DatatypePropertyRecord:
        record = self.repo.get_datatype_property(ontology_id, prop_id)
        if record is None:
            raise NotFoundError(
                f"Datatype property '{prop_id}' was not found.", code="DATATYPE_PROPERTY_NOT_FOUND"
            )
        return record

    def list_datatype_properties(self, ontology_id: str) -> list[DatatypePropertyDefinition]:
        self._require(ontology_id)
        return [to_datatype_property_definition(r) for r in self.repo.datatype_properties(ontology_id)]

    def get_datatype_property(self, ontology_id: str, prop_id: str) -> DatatypePropertyDefinition:
        self._require(ontology_id)
        return to_datatype_property_definition(self._require_datatype_property(ontology_id, prop_id))

    def create_datatype_property(
        self, ontology_id: str, data: DatatypePropertyCreate
    ) -> DatatypePropertyDefinition:
        ontology = self._require(ontology_id)
        element_id = data.id or new_element_id("dp")
        local_name = data.local_name or to_property_local_name(data.label)
        self._ensure_new_element_id(ontology_id, element_id)
        self._ensure_local_name_available(ontology_id, local_name)
        self._ensure_classes_exist(ontology_id, "domain_id", [data.domain_id])
        definition = DatatypePropertyDefinition(
            id=element_id,
            local_name=local_name,
            iri=f"{ontology.namespace}{local_name}",
            label=data.label,
            description=data.description,
            aliases=data.aliases,
            domain_id=data.domain_id,
            datatype=data.datatype,
            required=data.required,
            multi_valued=data.multi_valued,
        )
        self.repo.add_element(
            DatatypePropertyRecord(
                ontology_id=ontology_id,
                id=element_id,
                sort_order=self.repo.next_sort_order(DatatypePropertyRecord, ontology_id),
                **{f: _db_value(getattr(definition, f)) for f in DATATYPE_PROPERTY_FIELDS},
            )
        )
        self._touch(ontology)
        self._activity(
            ontology, "ontology.attribute_created", f"Attribute '{definition.label}' added"
        )
        self.session.commit()
        return definition

    def update_datatype_property(
        self, ontology_id: str, prop_id: str, data: DatatypePropertyUpdate
    ) -> DatatypePropertyDefinition:
        ontology = self._require(ontology_id)
        record = self._require_datatype_property(ontology_id, prop_id)
        requested = data.model_dump(exclude_unset=True, exclude_none=True)
        if "local_name" in requested:
            self._ensure_local_name_available(ontology_id, requested["local_name"], prop_id)
        if "domain_id" in requested:
            self._ensure_classes_exist(ontology_id, "domain_id", [requested["domain_id"]])
        return self._apply_update(
            ontology,
            record,
            requested,
            to_datatype_property_definition,
            "ontology.attribute_updated",
            "Attribute",
        )

    def delete_datatype_property(self, ontology_id: str, prop_id: str) -> None:
        ontology = self._require(ontology_id)
        record = self._require_datatype_property(ontology_id, prop_id)
        self.repo.delete_element(record)
        self._strip_semantic_references(ontology_id, {prop_id})
        self._touch(ontology)
        self._activity(ontology, "ontology.attribute_deleted", f"Attribute '{record.label}' deleted")
        self.session.commit()

    # ------------------------------------------------------------------------------ shared

    def _strip_semantic_references(self, ontology_id: str, removed: set[str]) -> None:
        """Drop OWL semantics (equivalence, disjointness, restrictions, inverse, super-properties) that
        refer to deleted elements, mirroring the cascade applied to domains, ranges and parents."""
        for records in (
            self.repo.classes(ontology_id),
            self.repo.object_properties(ontology_id),
            self.repo.datatype_properties(ontology_id),
        ):
            for record in records:
                if record.id in removed or not record.semantics:
                    continue
                semantics = dict(record.semantics)
                for key in ("equivalent_ids", "disjoint_ids", "parent_ids"):
                    if key in semantics:
                        kept = [i for i in semantics[key] if i not in removed]
                        if kept:
                            semantics[key] = kept
                        else:
                            del semantics[key]
                if semantics.get("inverse_id") in removed:
                    del semantics["inverse_id"]
                if "restrictions" in semantics:
                    kept_restrictions = [
                        r
                        for r in semantics["restrictions"]
                        if r.get("property_id") not in removed and r.get("class_id") not in removed
                    ]
                    if kept_restrictions:
                        semantics["restrictions"] = kept_restrictions
                    else:
                        del semantics["restrictions"]
                if semantics != record.semantics:
                    record.semantics = semantics

    def _apply_update(
        self,
        ontology: Ontology,
        record: Any,
        requested: dict[str, Any],
        to_definition: Any,
        event_type: str,
        noun: str,
    ) -> Any:
        values = {k: _db_value(v) for k, v in requested.items()}
        changed = {k: v for k, v in values.items() if getattr(record, k) != v}
        if (
            "local_name" in changed
            and record.id not in self.locked_iris(ontology.id)
            and record.iri in (None, f"{ontology.namespace}{record.local_name}")
        ):
            changed["iri"] = f"{ontology.namespace}{changed['local_name']}"
        if changed:
            for key, value in changed.items():
                setattr(record, key, value)
            self._touch(ontology)
            self._activity(
                ontology,
                event_type,
                f"{noun} '{record.label}' updated ({', '.join(sorted(changed))})",
            )
            self.session.commit()
        return to_definition(record)
