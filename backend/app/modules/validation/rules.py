"""Structural ontology validation rules.

``validate_schema`` is a pure function over the canonical :class:`OntologySchema`. It has no
knowledge of persistence, UI or any specific business domain, so the same rules apply to saved
drafts, imported ontologies and (Phase 2) AI-generated change proposals.

Severity semantics:

* ``error``   - the ontology is structurally broken; publication must be blocked.
* ``warning`` - likely modelling problem that an SME should review.
* ``info``    - convention or completeness hint.
"""

import re
from collections import defaultdict, deque
from collections.abc import Iterable
from urllib.parse import urlsplit

from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
    OntologySchema,
)
from app.modules.validation.schemas import ElementKind, Severity, ValidationIssue

LOCAL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
RESERVED_PREFIXES = frozenset({"rdf", "rdfs", "owl", "xsd", "xml", "sh"})
_IRI_FORBIDDEN = re.compile(r"[\s<>\"{}|\\^`]")

_SEVERITY_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

AnyElement = ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition


class _Collector:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(
        self,
        code: str,
        severity: Severity,
        message: str,
        kind: ElementKind,
        element: AnyElement | None = None,
        field: str | None = None,
        related: Iterable[str] = (),
    ) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                severity=severity,
                message=message,
                element_kind=kind,
                element_id=element.id if element else None,
                element_label=element.label if element else None,
                field=field,
                related_element_ids=list(related),
            )
        )


def _kind(element: AnyElement) -> ElementKind:
    if isinstance(element, ClassDefinition):
        return ElementKind.CLASS
    if isinstance(element, ObjectPropertyDefinition):
        return ElementKind.OBJECT_PROPERTY
    return ElementKind.DATATYPE_PROPERTY


def _noun(element: AnyElement) -> str:
    return {
        ElementKind.CLASS: "Class",
        ElementKind.OBJECT_PROPERTY: "Relationship",
        ElementKind.DATATYPE_PROPERTY: "Attribute",
    }[_kind(element)]


def validate_schema(schema: OntologySchema) -> list[ValidationIssue]:
    out = _Collector()
    _check_ontology_header(schema, out)

    elements: list[AnyElement] = [
        *schema.classes,
        *schema.object_properties,
        *schema.datatype_properties,
    ]
    if not schema.classes:
        out.add(
            "ONTOLOGY_EMPTY",
            Severity.WARNING,
            "The ontology has no classes yet.",
            ElementKind.ONTOLOGY,
        )

    _check_identity(elements, out)
    classes_by_id = {c.id: c for c in schema.classes}
    _check_descriptions(elements, out)
    _check_class_hierarchy(schema.classes, classes_by_id, out)
    _check_class_labels_and_aliases(schema.classes, out)
    _check_object_properties(schema.object_properties, classes_by_id, out)
    _check_datatype_properties(schema.datatype_properties, schema.classes, classes_by_id, out)
    _check_orphans(schema, out)

    return sorted(
        out.issues,
        key=lambda i: (_SEVERITY_RANK[i.severity], i.element_kind.value, i.code, i.element_label or ""),
    )


# ---------------------------------------------------------------------------------- ontology


def _check_ontology_header(schema: OntologySchema, out: _Collector) -> None:
    ns = schema.namespace.strip()
    parts = urlsplit(ns)
    absolute = bool(parts.scheme) and (parts.scheme not in {"http", "https"} or bool(parts.netloc))
    if not absolute or _IRI_FORBIDDEN.search(ns):
        out.add(
            "NAMESPACE_INVALID",
            Severity.ERROR,
            f"Namespace '{ns}' is not a valid absolute IRI (e.g. https://example.com/ontology#).",
            ElementKind.ONTOLOGY,
            field="namespace",
        )
    elif not ns.endswith(("#", "/")) and not (parts.scheme == "urn" and ns.endswith(":")):
        out.add(
            "NAMESPACE_MISSING_SEPARATOR",
            Severity.ERROR,
            f"Namespace '{ns}' must end with '#' or '/' (or ':' for URNs) so that element IRIs "
            "can be formed.",
            ElementKind.ONTOLOGY,
            field="namespace",
        )

    prefix = schema.prefix.strip()
    if not PREFIX_RE.match(prefix):
        out.add(
            "PREFIX_INVALID",
            Severity.ERROR,
            f"Prefix '{prefix}' must start with a letter and contain only letters, digits, '_' or '-'.",
            ElementKind.ONTOLOGY,
            field="prefix",
        )
    elif prefix.lower() in RESERVED_PREFIXES:
        out.add(
            "PREFIX_RESERVED",
            Severity.ERROR,
            f"Prefix '{prefix}' is reserved for a standard vocabulary.",
            ElementKind.ONTOLOGY,
            field="prefix",
        )


# ---------------------------------------------------------------------------------- identity


def _check_identity(elements: list[AnyElement], out: _Collector) -> None:
    by_id: dict[str, list[AnyElement]] = defaultdict(list)
    by_name: dict[str, list[AnyElement]] = defaultdict(list)
    by_folded: dict[str, list[AnyElement]] = defaultdict(list)
    for element in elements:
        by_id[element.id].append(element)
        by_name[element.local_name].append(element)
        by_folded[element.local_name.casefold()].append(element)

        if not LOCAL_NAME_RE.match(element.local_name):
            out.add(
                "LOCAL_NAME_INVALID",
                Severity.ERROR,
                f"{_noun(element)} '{element.label}' has local name '{element.local_name}', which "
                "must start with a letter or '_' and contain only letters, digits, '_' or '-'.",
                _kind(element),
                element,
                "local_name",
            )
        elif isinstance(element, ClassDefinition) and not element.local_name[0].isupper():
            out.add(
                "LOCAL_NAME_CONVENTION",
                Severity.INFO,
                f"Class local name '{element.local_name}' should use UpperCamelCase.",
                ElementKind.CLASS,
                element,
                "local_name",
            )
        elif not isinstance(element, ClassDefinition) and not element.local_name[0].islower():
            out.add(
                "LOCAL_NAME_CONVENTION",
                Severity.INFO,
                f"Property local name '{element.local_name}' should use lowerCamelCase.",
                _kind(element),
                element,
                "local_name",
            )

    for element_id, group in by_id.items():
        if len(group) > 1:
            for element in group:
                out.add(
                    "DUPLICATE_ELEMENT_ID",
                    Severity.ERROR,
                    f"Element id '{element_id}' is used by {len(group)} elements.",
                    _kind(element),
                    element,
                    "id",
                )

    for name, group in by_name.items():
        if len(group) > 1:
            for element in group:
                others = [e.id for e in group if e is not element]
                out.add(
                    "DUPLICATE_LOCAL_NAME",
                    Severity.ERROR,
                    f"Local name '{name}' is used by {len(group)} elements; IRIs must be unique.",
                    _kind(element),
                    element,
                    "local_name",
                    others,
                )

    for group in by_folded.values():
        if len({e.local_name for e in group}) > 1:
            for element in group:
                others = [e.id for e in group if e.local_name != element.local_name]
                out.add(
                    "LOCAL_NAME_CASE_COLLISION",
                    Severity.WARNING,
                    f"Local name '{element.local_name}' differs from another element only by letter case.",
                    _kind(element),
                    element,
                    "local_name",
                    others,
                )


def _check_descriptions(elements: list[AnyElement], out: _Collector) -> None:
    for element in elements:
        if element.description.strip():
            continue
        severity = (
            Severity.INFO if isinstance(element, DatatypePropertyDefinition) else Severity.WARNING
        )
        out.add(
            "DESCRIPTION_MISSING",
            severity,
            f"{_noun(element)} '{element.label}' has no definition. SMEs need definitions to "
            "govern meaning.",
            _kind(element),
            element,
            "description",
        )


# ---------------------------------------------------------------------------------- classes


def _check_class_hierarchy(
    classes: list[ClassDefinition], classes_by_id: dict[str, ClassDefinition], out: _Collector
) -> None:
    for cls in classes:
        for parent_id in cls.parent_ids:
            if parent_id == cls.id:
                out.add(
                    "CLASS_PARENT_SELF",
                    Severity.ERROR,
                    f"Class '{cls.label}' cannot be a subclass of itself.",
                    ElementKind.CLASS,
                    cls,
                    "parent_ids",
                )
            elif parent_id not in classes_by_id:
                out.add(
                    "CLASS_PARENT_UNKNOWN",
                    Severity.ERROR,
                    f"Class '{cls.label}' declares unknown parent class id '{parent_id}'.",
                    ElementKind.CLASS,
                    cls,
                    "parent_ids",
                    [parent_id],
                )

    parents = {
        c.id: [p for p in c.parent_ids if p in classes_by_id and p != c.id] for c in classes
    }
    reported: set[frozenset[str]] = set()
    for cls in classes:
        path = _find_cycle(cls.id, parents)
        if not path:
            continue
        key = frozenset(path)
        if key in reported:
            continue
        reported.add(key)
        labels = " → ".join(classes_by_id[cid].label for cid in [*path, path[0]])
        out.add(
            "CLASS_HIERARCHY_CYCLE",
            Severity.ERROR,
            f"Subclass hierarchy contains a cycle: {labels}.",
            ElementKind.CLASS,
            cls,
            "parent_ids",
            [cid for cid in path if cid != cls.id],
        )


def _find_cycle(start: str, parents: dict[str, list[str]]) -> list[str] | None:
    """Return a path start -> ... -> (back to start) via parent links, if one exists."""
    previous: dict[str, str] = {}
    queue: deque[str] = deque()
    for parent in parents.get(start, []):
        if parent not in previous:
            previous[parent] = start
            queue.append(parent)
    while queue:
        node = queue.popleft()
        if node == start:
            path = [start]
            cursor = previous[start]
            while cursor != start:
                path.append(cursor)
                cursor = previous[cursor]
            return [path[0], *reversed(path[1:])]
        for parent in parents.get(node, []):
            if parent not in previous:
                previous[parent] = node
                queue.append(parent)
    return None


def _check_class_labels_and_aliases(classes: list[ClassDefinition], out: _Collector) -> None:
    by_label: dict[str, list[ClassDefinition]] = defaultdict(list)
    for cls in classes:
        by_label[cls.label.casefold()].append(cls)
    for group in by_label.values():
        if len(group) > 1:
            for cls in group:
                out.add(
                    "DUPLICATE_CLASS_LABEL",
                    Severity.WARNING,
                    f"Class label '{cls.label}' is used by {len(group)} classes; these may be duplicate concepts.",
                    ElementKind.CLASS,
                    cls,
                    "label",
                    [c.id for c in group if c is not cls],
                )

    terms: dict[str, set[str]] = defaultdict(set)
    for cls in classes:
        terms[cls.label.casefold()].add(cls.id)
        for alias in cls.aliases:
            terms[alias.casefold()].add(cls.id)
    for cls in classes:
        for alias in cls.aliases:
            owners = terms[alias.casefold()] - {cls.id}
            if owners:
                out.add(
                    "ALIAS_CONFLICT",
                    Severity.WARNING,
                    f"Alias '{alias}' of class '{cls.label}' is also a label or alias of another class.",
                    ElementKind.CLASS,
                    cls,
                    "aliases",
                    sorted(owners),
                )


# ---------------------------------------------------------------------------------- properties


def _check_domain(
    prop: ObjectPropertyDefinition | DatatypePropertyDefinition,
    classes_by_id: dict[str, ClassDefinition],
    out: _Collector,
) -> None:
    if not prop.domain_id:
        out.add(
            "PROPERTY_DOMAIN_MISSING",
            Severity.ERROR,
            f"{_noun(prop)} '{prop.label}' has no domain class.",
            _kind(prop),
            prop,
            "domain_id",
        )
    elif prop.domain_id not in classes_by_id:
        out.add(
            "PROPERTY_DOMAIN_UNKNOWN",
            Severity.ERROR,
            f"{_noun(prop)} '{prop.label}' references unknown domain class id '{prop.domain_id}'.",
            _kind(prop),
            prop,
            "domain_id",
            [prop.domain_id],
        )


def _check_object_properties(
    props: list[ObjectPropertyDefinition],
    classes_by_id: dict[str, ClassDefinition],
    out: _Collector,
) -> None:
    signatures: dict[tuple[str | None, str | None, str], list[ObjectPropertyDefinition]] = defaultdict(list)
    for prop in props:
        _check_domain(prop, classes_by_id, out)
        if not prop.range_id:
            out.add(
                "PROPERTY_RANGE_MISSING",
                Severity.ERROR,
                f"Relationship '{prop.label}' has no range class.",
                ElementKind.OBJECT_PROPERTY,
                prop,
                "range_id",
            )
        elif prop.range_id not in classes_by_id:
            out.add(
                "PROPERTY_RANGE_UNKNOWN",
                Severity.ERROR,
                f"Relationship '{prop.label}' references unknown range class id '{prop.range_id}'.",
                ElementKind.OBJECT_PROPERTY,
                prop,
                "range_id",
                [prop.range_id],
            )
        signatures[(prop.domain_id, prop.range_id, prop.label.casefold())].append(prop)

    for group in signatures.values():
        if len(group) > 1:
            for prop in group:
                out.add(
                    "DUPLICATE_RELATIONSHIP",
                    Severity.WARNING,
                    f"Relationship '{prop.label}' is declared {len(group)} times between the same classes.",
                    ElementKind.OBJECT_PROPERTY,
                    prop,
                    "label",
                    [p.id for p in group if p is not prop],
                )


def _ancestors(class_id: str, classes_by_id: dict[str, ClassDefinition]) -> set[str]:
    seen: set[str] = set()
    stack = list(classes_by_id[class_id].parent_ids) if class_id in classes_by_id else []
    while stack:
        current = stack.pop()
        if current in seen or current not in classes_by_id:
            continue
        seen.add(current)
        stack.extend(classes_by_id[current].parent_ids)
    seen.discard(class_id)
    return seen


def _check_datatype_properties(
    props: list[DatatypePropertyDefinition],
    classes: list[ClassDefinition],
    classes_by_id: dict[str, ClassDefinition],
    out: _Collector,
) -> None:
    by_domain_label: dict[tuple[str | None, str], list[DatatypePropertyDefinition]] = defaultdict(list)
    for prop in props:
        _check_domain(prop, classes_by_id, out)
        by_domain_label[(prop.domain_id, prop.label.casefold())].append(prop)

    for group in by_domain_label.values():
        if len(group) > 1:
            for prop in group:
                out.add(
                    "DUPLICATE_ATTRIBUTE",
                    Severity.WARNING,
                    f"Attribute '{prop.label}' is declared {len(group)} times on the same class.",
                    ElementKind.DATATYPE_PROPERTY,
                    prop,
                    "label",
                    [p.id for p in group if p is not prop],
                )

    labels_by_class: dict[str, dict[str, str]] = defaultdict(dict)
    for prop in props:
        if prop.domain_id in classes_by_id:
            labels_by_class[prop.domain_id].setdefault(prop.label.casefold(), prop.id)
    for prop in props:
        if prop.domain_id not in classes_by_id:
            continue
        for ancestor_id in _ancestors(prop.domain_id, classes_by_id):
            inherited = labels_by_class.get(ancestor_id, {}).get(prop.label.casefold())
            if inherited:
                out.add(
                    "INHERITED_ATTRIBUTE_REDECLARED",
                    Severity.INFO,
                    f"Attribute '{prop.label}' on '{classes_by_id[prop.domain_id].label}' is already "
                    f"inherited from '{classes_by_id[ancestor_id].label}'.",
                    ElementKind.DATATYPE_PROPERTY,
                    prop,
                    "label",
                    [inherited],
                )
                break


def _check_orphans(schema: OntologySchema, out: _Collector) -> None:
    connected: set[str] = set()
    for cls in schema.classes:
        if cls.parent_ids:
            connected.add(cls.id)
            connected.update(cls.parent_ids)
    for op in schema.object_properties:
        connected.update(x for x in (op.domain_id, op.range_id) if x)
    for dp in schema.datatype_properties:
        if dp.domain_id:
            connected.add(dp.domain_id)
    for cls in schema.classes:
        if cls.id not in connected:
            out.add(
                "ORPHAN_CLASS",
                Severity.INFO,
                f"Class '{cls.label}' has no relationships, attributes, parents or subclasses.",
                ElementKind.CLASS,
                cls,
            )
