"""Pure application of change proposals to the canonical ontology schema.

``apply_change`` never mutates its input and raises :class:`ApplyError` when a proposal's
preconditions no longer hold (missing target, unknown references, drift since the proposal was
created, duplicate identifiers or hierarchy cycles).
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
)
from app.modules.validation.rules import validate_schema
from app.modules.validation.schemas import Severity, ValidationIssue

DEFINITION_MODELS: dict[str, type[ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition]] = {
    "class": ClassDefinition,
    "object_property": ObjectPropertyDefinition,
    "datatype_property": DatatypePropertyDefinition,
}
COLLECTIONS = {"class": "classes", "object_property": "object_properties", "datatype_property": "datatype_properties"}
EDITABLE_FIELDS: dict[str, set[str]] = {
    "class": {"label", "local_name", "description", "aliases", "parent_ids"},
    "object_property": {"label", "local_name", "description", "aliases", "domain_id", "range_id"},
    "datatype_property": {
        "label", "local_name", "description", "aliases", "domain_id", "datatype", "required", "multi_valued",
    },
}
LIST_FIELDS = {"aliases", "parent_ids"}


class ApplyError(Exception):
    pass


@dataclass(frozen=True)
class ChangeSpec:
    proposal_type: str
    element_kind: str
    target_element_id: str | None = None
    new_element: dict[str, Any] | None = None
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)


def _plain(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _find(schema: OntologySchema, kind: str, element_id: str | None) -> Any:
    return next((e for e in getattr(schema, COLLECTIONS[kind]) if e.id == element_id), None)


def _check_references(schema: OntologySchema, kind: str, element: Any) -> None:
    class_ids = {c.id for c in schema.classes}
    if kind == "class":
        missing = [p for p in element.parent_ids if p not in class_ids]
        if missing:
            raise ApplyError(f"Parent class(es) {', '.join(missing)} do not exist in the draft.")
        if element.id in element.parent_ids:
            raise ApplyError("A class cannot be its own parent.")
        _check_acyclic(schema, element)
        return
    for role in ("domain_id", "range_id") if kind == "object_property" else ("domain_id",):
        value = getattr(element, role)
        if not value:
            raise ApplyError(f"The {role.removesuffix('_id')} class is not set.")
        if value not in class_ids:
            raise ApplyError(f"The {role.removesuffix('_id')} class '{value}' does not exist in the draft.")


def _check_acyclic(schema: OntologySchema, element: ClassDefinition) -> None:
    parents = {c.id: list(c.parent_ids) for c in schema.classes}
    parents[element.id] = list(element.parent_ids)
    stack, seen = list(element.parent_ids), set()
    while stack:
        current = stack.pop()
        if current == element.id:
            raise ApplyError("The change would create a cycle in the class hierarchy.")
        if current not in seen:
            seen.add(current)
            stack.extend(parents.get(current, []))


def _check_local_name(schema: OntologySchema, local_name: str, own_id: str) -> None:
    for element in (*schema.classes, *schema.object_properties, *schema.datatype_properties):
        if element.local_name == local_name and element.id != own_id:
            raise ApplyError(f"Local name '{local_name}' is already used by '{element.label}'.")


def _validated(kind: str, data: dict[str, Any]) -> Any:
    try:
        return DEFINITION_MODELS[kind].model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        raise ApplyError(f"Invalid {kind} definition: {'.'.join(map(str, first['loc']))} {first['msg']}.") from error


def apply_change(schema: OntologySchema, spec: ChangeSpec) -> OntologySchema:
    result = schema.model_copy(deep=True)
    kind = spec.element_kind
    collection: list[Any] = getattr(result, COLLECTIONS[kind])

    if spec.proposal_type == "add":
        if not spec.new_element:
            raise ApplyError("The proposal does not define the element to add.")
        element = _validated(kind, spec.new_element)
        all_ids = {e.id for e in (*result.classes, *result.object_properties, *result.datatype_properties)}
        if element.id in all_ids:
            raise ApplyError(f"An element with id '{element.id}' already exists.")
        _check_local_name(result, element.local_name, element.id)
        _check_references(result, kind, element)
        collection.append(element)
        return result

    target = _find(result, kind, spec.target_element_id)
    if target is None:
        raise ApplyError(f"The target element '{spec.target_element_id}' no longer exists in the draft.")
    if spec.proposal_type == "reuse" or not spec.changes:
        return result

    unknown = set(spec.changes) - EDITABLE_FIELDS[kind]
    if unknown:
        raise ApplyError(f"Field(s) {', '.join(sorted(unknown))} cannot be changed on a {kind}.")
    data = target.model_dump(mode="json")
    for name, change in spec.changes.items():
        current, before, after = data[name], _plain(change.get("before")), _plain(change.get("after"))
        if name in LIST_FIELDS:
            before_set, after_list = list(before or []), list(after or [])
            removed = [v for v in before_set if v not in after_list]
            added = [v for v in after_list if v not in before_set]
            merged = [v for v in current if v not in removed]
            data[name] = merged + [v for v in added if v not in merged]
            continue
        if current == after:
            continue
        if current != before:
            raise ApplyError(
                f"'{name}' changed in the draft since this proposal was created "
                f"(expected {before!r}, found {current!r}). Edit the proposal to rebase it."
            )
        data[name] = after
    updated = _validated(kind, data)
    if updated.local_name != target.local_name:
        _check_local_name(result, updated.local_name, updated.id)
    _check_references(result, kind, updated)
    collection[collection.index(target)] = updated
    return result


def _issue_key(issue: ValidationIssue) -> tuple[str, str | None, str | None]:
    return (issue.code, issue.element_id, issue.field)


@dataclass(frozen=True)
class Impact:
    applicable: bool
    reason: str | None
    introduced: list[ValidationIssue]
    resolved: list[ValidationIssue]

    @property
    def blocking(self) -> bool:
        return not self.applicable or any(i.severity == Severity.ERROR for i in self.introduced)


def assess_impact(schema: OntologySchema, specs: list[ChangeSpec]) -> Impact:
    """Validation delta of applying ``specs`` (dependencies first, the proposal last) to ``schema``."""
    candidate = schema
    try:
        for spec in specs:
            candidate = apply_change(candidate, spec)
    except ApplyError as error:
        return Impact(applicable=False, reason=str(error), introduced=[], resolved=[])
    before = validate_schema(schema)
    after = validate_schema(candidate)
    before_keys = {_issue_key(i) for i in before}
    after_keys = {_issue_key(i) for i in after}
    return Impact(
        applicable=True,
        reason=None,
        introduced=[i for i in after if _issue_key(i) not in before_keys],
        resolved=[i for i in before if _issue_key(i) not in after_keys],
    )
