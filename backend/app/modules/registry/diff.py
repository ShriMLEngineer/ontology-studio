"""Structural comparison of ontology snapshots and semantic-version bump suggestions."""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.ontology.domain import default_ontology_iri
from app.modules.registry.snapshot import OntologySnapshot

Bump = Literal["major", "minor", "patch", "none"]
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_KINDS = (("class", "classes"), ("object_property", "object_properties"), ("datatype_property", "datatype_properties"))
# Since Phase 4 the persisted IRI identifies an element; local_name changes only break consumers
# when the IRI changes too (legacy snapshots derive the IRI from the local name).
_BREAKING_FIELDS = {"iri", "domain_id", "range_id", "datatype"}
_MINOR_FIELDS = {"required", "multi_valued", "semantics"}
_RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


class FieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class ElementChange(BaseModel):
    element_id: str
    element_kind: str
    label: str
    change: Literal["added", "removed", "modified"]
    fields: list[FieldChange] = Field(default_factory=list)


class ChangeCounts(BaseModel):
    added: int = 0
    removed: int = 0
    modified: int = 0


class AxiomChange(BaseModel):
    axiom_id: str
    kind: str
    summary: str
    change: Literal["added", "removed"]


class SchemaDiff(BaseModel):
    from_label: str
    to_label: str
    metadata_changes: list[FieldChange]
    elements: list[ElementChange]
    summary: dict[str, ChangeCounts]
    breaking_changes: list[str]
    suggested_bump: Bump
    has_changes: bool
    axiom_changes: list[AxiomChange] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def parse_semver(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.match(version.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def bump_version(previous: str | None, bump: Bump) -> str:
    if previous is None:
        return "1.0.0"
    major, minor, patch = parse_semver(previous) or (1, 0, 0)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _max_bump(current: Bump, candidate: Bump) -> Bump:
    return candidate if _RANK[candidate] > _RANK[current] else current


def diff_snapshots(
    base: OntologySnapshot | None, target: OntologySnapshot, *, from_label: str, to_label: str
) -> SchemaDiff:
    bump: Bump = "none"
    breaking: list[str] = []
    notes: list[str] = []
    metadata_changes: list[FieldChange] = []
    base = base.with_iris() if base is not None else None
    target = target.with_iris()
    if base is not None:
        before_meta, after_meta = _metadata(base), _metadata(target)
        for name, before in before_meta.items():
            after = after_meta[name]
            if before != after:
                metadata_changes.append(FieldChange(field=name, before=before, after=after))
                if name in {"namespace", "prefix", "ontology_iri"}:
                    bump = "major"
                    breaking.append(f"Ontology {name} changed from '{before}' to '{after}'.")
                else:
                    bump = _max_bump(bump, "patch")

    elements: list[ElementChange] = []
    summary: dict[str, ChangeCounts] = {}
    for kind, attr in _KINDS:
        counts = ChangeCounts()
        before_items = {e.id: e.model_dump(mode="json") for e in (getattr(base, attr) if base else [])}
        after_items = {e.id: e.model_dump(mode="json") for e in getattr(target, attr)}
        for element_id, after in after_items.items():
            before = before_items.get(element_id)
            if before is None:
                elements.append(ElementChange(element_id=element_id, element_kind=kind, label=after["label"], change="added"))
                counts.added += 1
                bump = _max_bump(bump, "minor")
                continue
            fields = [
                FieldChange(field=name, before=before[name], after=after[name])
                for name in after
                if name != "id" and before.get(name) != after[name]
            ]
            if not fields:
                continue
            counts.modified += 1
            elements.append(
                ElementChange(element_id=element_id, element_kind=kind, label=after["label"], change="modified", fields=fields)
            )
            for change in fields:
                removed_parents = change.field == "parent_ids" and set(change.before or []) - set(change.after or [])
                if change.field in _BREAKING_FIELDS or removed_parents:
                    if change.field == "iri":
                        breaking.append(f"{after['label']}: IRI changed from <{change.before}> to <{change.after}>.")
                        bump = "major"
                        continue
                    bump = "major"
                    breaking.append(f"{after['label']}: {change.field} changed.")
                elif change.field in _MINOR_FIELDS or change.field == "parent_ids":
                    bump = _max_bump(bump, "minor")
                else:
                    bump = _max_bump(bump, "patch")
        for element_id, before in before_items.items():
            if element_id not in after_items:
                elements.append(ElementChange(element_id=element_id, element_kind=kind, label=before["label"], change="removed"))
                counts.removed += 1
                bump = "major"
                breaking.append(f"{before['label']} was removed.")
        summary[kind] = counts

    axiom_changes = _axiom_changes(base, target)
    for change in axiom_changes:
        if change.change == "added":
            bump = _max_bump(bump, "minor")
        else:
            bump = "major"
            breaking.append(f"Preserved axiom removed: {change.summary}")

    if base is not None and base.is_legacy and not target.is_legacy:
        functional = sum(1 for p in base.datatype_properties if not p.multi_valued)
        restrictions = sum(1 for p in base.datatype_properties if p.required and p.domain_id)
        explicit = sum(1 for p in target.datatype_properties if p.semantics.functional)
        notes.append(
            "Semantic profile change (ols.ontology-snapshot/1 -> /2): the earlier OWL artifact asserted "
            f"{functional} owl:FunctionalProperty and {restrictions} owl:minCardinality axiom(s) derived from the "
            "'single value' and 'required' switches. From this version those switches are data constraints "
            "published as SHACL (sh:maxCount / sh:minCount); OWL characteristics are asserted only where set "
            f"explicitly ({explicit} datatype propert(y/ies) marked functional). Earlier artifacts are unchanged."
        )
        bump = _max_bump(bump, "minor")

    order = {"removed": 0, "modified": 1, "added": 2}
    elements.sort(key=lambda e: (order[e.change], e.element_kind, e.label.lower()))
    return SchemaDiff(
        from_label=from_label,
        to_label=to_label,
        metadata_changes=metadata_changes,
        elements=elements,
        summary=summary,
        breaking_changes=breaking,
        suggested_bump=bump if base is not None else "major",
        has_changes=bool(metadata_changes or elements or axiom_changes or notes),
        axiom_changes=axiom_changes,
        notes=notes,
    )


def _metadata(snapshot: OntologySnapshot) -> dict[str, Any]:
    data = snapshot.metadata.model_dump(mode="json")
    data["ontology_iri"] = data["ontology_iri"] or default_ontology_iri(snapshot.metadata.namespace)
    return data


def _axiom_key(ntriples: str, scope: str) -> tuple[str, str]:
    from app.modules.semantics.graphs import canonical_ntriples

    return scope, canonical_ntriples(ntriples)


def _axiom_changes(base: OntologySnapshot | None, target: OntologySnapshot) -> list[AxiomChange]:
    before = {_axiom_key(a.ntriples, a.scope): a for a in (base.extension_axioms if base else [])}
    after = {_axiom_key(a.ntriples, a.scope): a for a in target.extension_axioms}
    changes = [
        AxiomChange(axiom_id=a.id, kind=a.kind, summary=a.summary, change="added")
        for key, a in after.items()
        if key not in before
    ]
    changes += [
        AxiomChange(axiom_id=a.id, kind=a.kind, summary=a.summary, change="removed")
        for key, a in before.items()
        if key not in after
    ]
    return sorted(changes, key=lambda c: (c.change, c.kind, c.summary))
