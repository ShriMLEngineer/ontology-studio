"""Read-only view over a published ontology snapshot: the schema authority for a KG build.

Resolves class and property references (id, label, local name or alias) and answers subclass
questions used by domain/range validation. Nothing outside the snapshot is ever resolved.
"""

from app.modules.discovery.alignment import normalize_term
from app.modules.kg.normalization import ValueSpec, value_spec_for
from app.modules.ontology.domain import (
    ClassDefinition,
    DatatypePropertyDefinition,
    ObjectPropertyDefinition,
)
from app.modules.registry.snapshot import OntologySnapshot

Element = ClassDefinition | ObjectPropertyDefinition | DatatypePropertyDefinition


def _names(element: Element) -> set[str]:
    names = {normalize_term(element.label), normalize_term(element.local_name)}
    names |= {normalize_term(a) for a in element.aliases}
    return {n for n in names if n}


class OntologyView:
    def __init__(self, snapshot: OntologySnapshot, *, version_id: str, version: str) -> None:
        self.snapshot = snapshot
        self.version_id = version_id
        self.version = version
        self.name = snapshot.metadata.name
        self.classes = {c.id: c for c in snapshot.classes}
        self.object_properties = {p.id: p for p in snapshot.object_properties}
        self.datatype_properties = {p.id: p for p in snapshot.datatype_properties}
        self._index: dict[str, dict[str, set[str]]] = {"class": {}, "object_property": {}, "datatype_property": {}}
        for kind, elements in (
            ("class", self.classes.values()),
            ("object_property", self.object_properties.values()),
            ("datatype_property", self.datatype_properties.values()),
        ):
            for element in elements:
                for name in _names(element):
                    self._index[kind].setdefault(name, set()).add(element.id)
        self._ancestors: dict[str, set[str]] = {}
        self._value_specs: dict[str, ValueSpec] = {}

    # ------------------------------------------------------------------ attribute values

    def value_spec(self, property_id: str | None) -> ValueSpec | None:
        """The datatype and unit of an attribute's values, as defined by this immutable published version."""
        prop = self.datatype_properties.get(property_id or "")
        if prop is None:
            return None
        if prop.id not in self._value_specs:
            self._value_specs[prop.id] = value_spec_for(prop)
        return self._value_specs[prop.id]

    # ------------------------------------------------------------------ resolution

    def _resolve(self, kind: str, ref: str | None, by_id: dict[str, Element]) -> str | None:  # type: ignore[type-arg]
        if not ref or not ref.strip():
            return None
        ref = ref.strip()
        if ref in by_id:
            return ref
        matches = self._index[kind].get(normalize_term(ref), set())
        return next(iter(matches)) if len(matches) == 1 else None

    def resolve_class(self, ref: str | None) -> str | None:
        return self._resolve("class", ref, self.classes)  # type: ignore[arg-type]

    def resolve_object_property(self, ref: str | None) -> str | None:
        return self._resolve("object_property", ref, self.object_properties)  # type: ignore[arg-type]

    def resolve_datatype_property(self, ref: str | None) -> str | None:
        return self._resolve("datatype_property", ref, self.datatype_properties)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ hierarchy

    def ancestors(self, class_id: str) -> set[str]:
        """The class itself and all of its (transitive) superclasses; cycle-safe."""
        if class_id in self._ancestors:
            return self._ancestors[class_id]
        seen: set[str] = set()
        stack = [class_id]
        while stack:
            current = stack.pop()
            if current in seen or current not in self.classes:
                continue
            seen.add(current)
            stack.extend(self.classes[current].parent_ids)
        self._ancestors[class_id] = seen
        return seen

    def is_a(self, class_id: str | None, target_id: str | None) -> bool:
        if not class_id or not target_id:
            return False
        return target_id in self.ancestors(class_id)

    def satisfies(self, class_id: str | None, constraint_id: str | None) -> bool:
        """Domain/range check. An undeclared domain or range (open signature, e.g. imported ontologies) admits
        every class; a declared one requires the class or a subclass."""
        if not constraint_id:
            return bool(class_id)
        return self.is_a(class_id, constraint_id)

    def constraint_label(self, constraint_id: str | None) -> str:
        return self.class_label(constraint_id, "?") if constraint_id else "any class (open)"

    def compatible(self, a: str | None, b: str | None) -> bool:
        return self.is_a(a, b) or self.is_a(b, a)

    # ------------------------------------------------------------------ labels

    def class_label(self, class_id: str | None, fallback: str = "") -> str:
        cls = self.classes.get(class_id or "")
        return cls.label if cls else fallback

    def property_label(self, property_id: str | None, fallback: str = "") -> str:
        prop = self.object_properties.get(property_id or "") or self.datatype_properties.get(property_id or "")
        return prop.label if prop else fallback

    def required_attributes(self, class_id: str) -> list[DatatypePropertyDefinition]:
        ancestors = self.ancestors(class_id)
        return [p for p in self.datatype_properties.values() if p.required and p.domain_id in ancestors]
