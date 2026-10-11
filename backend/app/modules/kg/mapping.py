"""Structured source-to-ontology mappings and the deterministic record-to-graph transformation.

A mapping is generic: it names columns and ontology element ids, never business concepts. Each
record yields entity mentions (one per entity mapping), attribute facts and relationship facts.
Class and predicate values may come from a column (edge lists); such values are resolved against
the selected published version and unknown values become ontology gap candidates.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.discovery.alignment import conventional_label, normalize_term
from app.modules.kg.canonical import STRUCTURED, ExtractionResult, FactCandidate, GapCandidate, Mention, SourceRef
from app.modules.kg.connectors import StructuredSource, infer_datatype
from app.modules.kg.ontology_view import OntologyView
from app.modules.ontology.domain import ElementId

Column = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EntityKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,31}$")]


class AttributeMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: Column
    property_id: ElementId


class EntityMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: EntityKey
    class_id: ElementId | None = None
    class_column: Column | None = None
    id_column: Column
    label_column: Column | None = None
    alias_columns: list[Column] = Field(default_factory=list, max_length=10)
    alias_separator: Annotated[str, StringConstraints(min_length=1, max_length=3)] = "|"
    key_namespace: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] = ""
    reference_only: bool = Field(
        default=False,
        description="The row only references the entity by key; it does not establish the entity.",
    )
    attributes: list[AttributeMapping] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _one_class_source(self) -> "EntityMapping":
        if bool(self.class_id) == bool(self.class_column):
            raise ValueError("Set exactly one of class_id (fixed class) or class_column (class per row).")
        return self


class RelationshipMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: EntityKey
    object: EntityKey
    predicate_id: ElementId | None = None
    predicate_column: Column | None = None

    @model_validator(mode="after")
    def _one_predicate_source(self) -> "RelationshipMapping":
        if bool(self.predicate_id) == bool(self.predicate_column):
            raise ValueError("Set exactly one of predicate_id (fixed) or predicate_column (predicate per row).")
        return self


class MappingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[EntityMapping] = Field(min_length=1, max_length=20)
    relationships: list[RelationshipMapping] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _references(self) -> "MappingSpec":
        keys = [e.key for e in self.entities]
        duplicates = sorted(k for k, n in Counter(keys).items() if n > 1)
        if duplicates:
            raise ValueError(f"Entity keys must be unique: {', '.join(duplicates)}")
        for rel in self.relationships:
            for role in ("subject", "object"):
                if getattr(rel, role) not in keys:
                    raise ValueError(f"Relationship {role} '{getattr(rel, role)}' is not a defined entity key.")
        return self

    def used_columns(self) -> set[str]:
        used: set[str] = set()
        for entity in self.entities:
            used |= {entity.id_column, *entity.alias_columns, *(a.column for a in entity.attributes)}
            used |= {c for c in (entity.class_column, entity.label_column) if c}
        used |= {r.predicate_column for r in self.relationships if r.predicate_column}
        return used


@dataclass(frozen=True)
class MappingIssue:
    severity: str  # error | warning
    code: str
    message: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message, "path": self.path}


def validate_mapping(spec: MappingSpec, columns: list[str], view: OntologyView) -> list[MappingIssue]:
    """Check a mapping against the source columns and a published ontology version."""
    issues: list[MappingIssue] = []
    known = set(columns)

    def column(path: str, name: str | None) -> None:
        if name and name not in known:
            issues.append(MappingIssue("error", "UNKNOWN_COLUMN", f"Column '{name}' does not exist in the source.", path))

    entity_class: dict[str, str | None] = {}
    for i, entity in enumerate(spec.entities):
        base = f"entities[{i}]"
        for field_name in ("id_column", "label_column", "class_column"):
            column(f"{base}.{field_name}", getattr(entity, field_name))
        for j, alias in enumerate(entity.alias_columns):
            column(f"{base}.alias_columns[{j}]", alias)
        entity_class[entity.key] = entity.class_id
        if entity.class_id and entity.class_id not in view.classes:
            issues.append(
                MappingIssue(
                    "error",
                    "UNKNOWN_CLASS",
                    f"Class '{entity.class_id}' is not defined in {view.name} {view.version}.",
                    f"{base}.class_id",
                )
            )
        if entity.reference_only and entity.attributes:
            issues.append(
                MappingIssue(
                    "error",
                    "REFERENCE_WITH_ATTRIBUTES",
                    "A reference-only entity cannot carry attributes; the row does not establish it.",
                    f"{base}.attributes",
                )
            )
        for j, attribute in enumerate(entity.attributes):
            path = f"{base}.attributes[{j}]"
            column(f"{path}.column", attribute.column)
            prop = view.datatype_properties.get(attribute.property_id)
            if prop is None:
                kind = "a relationship" if attribute.property_id in view.object_properties else "not defined"
                issues.append(
                    MappingIssue(
                        "error",
                        "UNKNOWN_PROPERTY",
                        f"Attribute '{attribute.property_id}' is {kind} in {view.name} {view.version}.",
                        f"{path}.property_id",
                    )
                )
            elif entity.class_id and entity.class_id in view.classes and not view.is_a(entity.class_id, prop.domain_id):
                issues.append(
                    MappingIssue(
                        "warning",
                        "DOMAIN_MISMATCH",
                        f"'{prop.label}' applies to {view.class_label(prop.domain_id, '?')}, not "
                        f"{view.class_label(entity.class_id)}; these values will be rejected by structural validation.",
                        f"{path}.property_id",
                    )
                )
    for i, rel in enumerate(spec.relationships):
        path = f"relationships[{i}]"
        column(f"{path}.predicate_column", rel.predicate_column)
        if not rel.predicate_id:
            continue
        prop = view.object_properties.get(rel.predicate_id)
        if prop is None:
            kind = "an attribute" if rel.predicate_id in view.datatype_properties else "not defined"
            issues.append(
                MappingIssue(
                    "error",
                    "UNKNOWN_PREDICATE",
                    f"Relationship '{rel.predicate_id}' is {kind} in {view.name} {view.version}.",
                    f"{path}.predicate_id",
                )
            )
            continue
        subject_cls, object_cls = entity_class.get(rel.subject), entity_class.get(rel.object)
        if subject_cls in view.classes and object_cls in view.classes:
            forward = view.is_a(subject_cls, prop.domain_id) and view.is_a(object_cls, prop.range_id)
            reverse = view.is_a(object_cls, prop.domain_id) and view.is_a(subject_cls, prop.range_id)
            if not forward:
                hint = " The direction appears reversed." if reverse else ""
                issues.append(
                    MappingIssue(
                        "warning",
                        "DOMAIN_RANGE_MISMATCH",
                        f"'{prop.label}' is defined as {view.class_label(prop.domain_id, '?')} → "
                        f"{view.class_label(prop.range_id, '?')}, but this mapping states "
                        f"{view.class_label(subject_cls)} → {view.class_label(object_cls)}.{hint} "
                        "These facts will be rejected by structural validation.",
                        path,
                    )
                )
    return issues


# ---------------------------------------------------------------------------------- transform


def _split_aliases(values: dict[str, str], columns: list[str], separator: str) -> list[str]:
    aliases: list[str] = []
    for name in columns:
        aliases += [a.strip() for a in values.get(name, "").split(separator) if a.strip()]
    return list(dict.fromkeys(aliases))


def humanize(column: str) -> str:
    return " ".join(re.findall(r"[A-Za-z0-9]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", column))).lower()


def transform_records(
    *,
    mapping_id: str,
    mapping_name: str,
    spec: MappingSpec,
    source: StructuredSource,
    view: OntologyView,
    limit: int | None = None,
) -> tuple[ExtractionResult, dict[str, int]]:
    """Deterministically convert records into mentions, facts and gap candidates (no LLM)."""
    result = ExtractionResult()
    stats = {"records": 0, "mentions": 0, "relationships": 0, "attributes": 0, "skipped_empty": 0}
    used = spec.used_columns()
    unmapped: dict[str, list[tuple[str, SourceRef]]] = {}
    prefix = mapping_id[:8]
    columns = source.columns()

    for record in source.records(limit):
        stats["records"] += 1
        values = record.values

        def ref(_record: Any = record, _values: dict[str, str] = values) -> SourceRef:
            return SourceRef(
                kind="record",
                document_id=source.source_id,
                document_name=source.source_name,
                mapping_id=mapping_id,
                mapping_name=mapping_name,
                row_number=_record.row_number,
                line_number=_record.line_number,
                record=dict(_values),
                raw=_record.raw,
                chunk_id=_record.chunk_id,
            )

        row_mentions: dict[str, Mention] = {}
        for entity in spec.entities:
            identifier = values.get(entity.id_column, "").strip()
            class_ref = entity.class_id or values.get(entity.class_column or "", "").strip()
            if entity.reference_only and not identifier:
                stats["skipped_empty"] += 1
                continue
            if not class_ref and not identifier:
                stats["skipped_empty"] += 1
                continue
            class_id = entity.class_id if entity.class_id in view.classes else view.resolve_class(class_ref)
            mention = Mention(
                key=f"{prefix}:r{record.row_number}:{entity.key}",
                origin=STRUCTURED,
                class_ref=class_ref,
                class_id=class_id,
                identifier=identifier or None,
                key_namespace=entity.key_namespace,
                label=(values.get(entity.label_column or "", "").strip() or None),
                aliases=_split_aliases(values, entity.alias_columns, entity.alias_separator),
                reference_only=entity.reference_only,
                source=ref(),
                id_column=entity.id_column,
            )
            row_mentions[entity.key] = mention
            result.mentions.append(mention)
            stats["mentions"] += 1
            if class_id is None and class_ref:
                result.gaps.append(
                    GapCandidate(
                        gap_type="unknown_class",
                        term=class_ref,
                        label=conventional_label("class", class_ref),
                        origin=STRUCTURED,
                        evidence=ref(),
                        description=f"Entity type '{class_ref}' used in column '{entity.class_column}' of "
                        f"{source.source_name} is not defined in the ontology.",
                    )
                )
            if entity.reference_only:
                continue
            for attribute in entity.attributes:
                value = values.get(attribute.column, "").strip()
                if not value:
                    continue
                in_dp = attribute.property_id in view.datatype_properties
                result.facts.append(
                    FactCandidate(
                        key=f"{mention.key}:a:{attribute.column}",
                        kind="attribute",
                        origin=STRUCTURED,
                        subject=mention.key,
                        predicate_ref=attribute.property_id,
                        predicate_id=attribute.property_id if in_dp else None,
                        value=value,
                        wrong_kind="object_property" if attribute.property_id in view.object_properties else None,
                        subject_ref=identifier,
                        source=ref(),
                    )
                )
                stats["attributes"] += 1

        for index, rel in enumerate(spec.relationships):
            subject, obj = row_mentions.get(rel.subject), row_mentions.get(rel.object)
            if subject is None or obj is None:
                continue
            predicate_ref = rel.predicate_id or values.get(rel.predicate_column or "", "").strip()
            if not predicate_ref:
                stats["skipped_empty"] += 1
                continue
            if rel.predicate_id:
                predicate_id = rel.predicate_id if rel.predicate_id in view.object_properties else None
                wrong = "datatype_property" if rel.predicate_id in view.datatype_properties else None
            else:
                predicate_id = view.resolve_object_property(predicate_ref)
                wrong = None if predicate_id else (
                    "datatype_property" if view.resolve_datatype_property(predicate_ref) else None
                )
            fact_key = f"{prefix}:r{record.row_number}:rel{index}"
            result.facts.append(
                FactCandidate(
                    key=fact_key,
                    kind="relationship",
                    origin=STRUCTURED,
                    subject=subject.key,
                    predicate_ref=predicate_ref,
                    predicate_id=predicate_id,
                    object=obj.key,
                    wrong_kind=wrong,
                    subject_ref=subject.identifier,
                    object_ref=obj.identifier,
                    source=ref(),
                )
            )
            stats["relationships"] += 1
            if predicate_id is None and wrong is None:
                result.gaps.append(
                    GapCandidate(
                        gap_type="unknown_relationship",
                        term=predicate_ref,
                        label=" ".join(predicate_ref.split()).lower(),
                        origin=STRUCTURED,
                        evidence=ref(),
                        description=f"Relationship type '{predicate_ref}' in {source.source_name} is not "
                        "defined in the ontology.",
                        domain_ref=subject.class_ref,
                        domain_id=subject.class_id,
                        range_ref=obj.class_ref,
                        range_id=obj.class_id,
                        fact_key=fact_key,
                    )
                )

        for name in columns:
            if name not in used and values.get(name, "").strip():
                unmapped.setdefault(name, []).append((values[name].strip(), ref()))

    masters = [e for e in spec.entities if not e.reference_only and e.class_id in view.classes]
    domain_id = masters[0].class_id if len(masters) == 1 else None
    for name, occurrences in unmapped.items():
        samples = list(dict.fromkeys(v for v, _ in occurrences))[:5]
        result.gaps.append(
            GapCandidate(
                gap_type="unmapped_field",
                term=name,
                label=humanize(name) or name,
                origin=STRUCTURED,
                evidence=occurrences[0][1],
                description=f"Column '{name}' of {source.source_name} is not mapped to any ontology property "
                f"({len(occurrences)} row(s) have a value).",
                domain_id=domain_id,
                domain_ref=view.class_label(domain_id) if domain_id else None,
                datatype=infer_datatype([v for v, _ in occurrences]),
                column=name,
                mapping_id=mapping_id,
                sample_values=samples,
                occurrences=len(occurrences),
            )
        )
    return result, stats


# ---------------------------------------------------------------------------------- suggestion

_ID_SUFFIXES = ("id", "number", "code", "key", "no")
_NAME_SUFFIXES = ("name", "label", "title")
_PREDICATE_NAMES = {"relationship", "predicate", "relation", "relationship type", "edge type", "verb"}


def _id_prefix(normalized: str) -> str | None:
    words = normalized.split()
    if len(words) >= 2 and words[-1] in _ID_SUFFIXES:
        return " ".join(words[:-1])
    return None


def suggest_mapping(columns: list[str], view: OntologyView) -> tuple[MappingSpec | None, list[str]]:
    """Propose a mapping from column names only (deterministic, no LLM). Always SME-reviewed."""
    notes: list[str] = []
    normalized = {c: normalize_term(c) for c in columns}

    predicate_col = next((c for c in columns if normalized[c] in _PREDICATE_NAMES), None)
    if predicate_col:
        def find(role_words: tuple[str, ...], kind_words: tuple[str, ...]) -> str | None:
            for c in columns:
                words = normalized[c].split()
                if words and words[0] in role_words and words[-1] in kind_words:
                    return c
            return None

        subject_type = find(("subject", "source", "from"), ("type", "class"))
        subject_id = find(("subject", "source", "from"), _ID_SUFFIXES)
        object_type = find(("object", "target", "to"), ("type", "class"))
        object_id = find(("object", "target", "to"), _ID_SUFFIXES)
        if subject_type and subject_id and object_type and object_id:
            notes.append(
                "Detected an edge list: entity types and relationship types are read per row and resolved "
                "against the selected ontology version."
            )
            spec = MappingSpec(
                entities=[
                    EntityMapping(key="subject", class_column=subject_type, id_column=subject_id, reference_only=True),
                    EntityMapping(key="object", class_column=object_type, id_column=object_id, reference_only=True),
                ],
                relationships=[RelationshipMapping(subject="subject", object="object", predicate_column=predicate_col)],
            )
            return spec, notes

    entities: list[EntityMapping] = []
    claimed: set[str] = set()
    for c in columns:
        prefix = _id_prefix(normalized[c])
        if prefix is None:
            continue
        class_id = view.resolve_class(prefix)
        if class_id is None:
            continue
        is_master = not entities
        entity = EntityMapping(
            key=f"e{len(entities) + 1}", class_id=class_id, id_column=c, reference_only=not is_master
        )
        claimed.add(c)
        entities.append(entity)
        role = "records" if is_master else "references"
        notes.append(f"Column '{c}' {role} {view.class_label(class_id)} entities by identifier.")
    if not entities:
        notes.append("No identifier column could be matched to an ontology class; configure the mapping manually.")
        return None, notes

    master = entities[0]
    master_label = view.class_label(master.class_id)
    label_col = next(
        (c for c in columns if c not in claimed and normalized[c].split()[-1:] and normalized[c].split()[-1] in _NAME_SUFFIXES),
        None,
    )
    if label_col:
        master.label_column = label_col
    master.alias_columns = [
        c for c in columns if any(w in re.findall(r"[a-z]+", c.lower()) for w in ("alias", "aliases", "aka", "synonym", "synonyms"))
    ]
    claimed |= set(master.alias_columns)

    for c in columns:
        if c in claimed:
            continue
        candidates = [normalized[c], f"{normalize_term(master_label)} {normalized[c]}"]
        prop_id = next((p for p in (view.resolve_datatype_property(n) for n in candidates) if p), None)
        if prop_id and view.is_a(master.class_id, view.datatype_properties[prop_id].domain_id):
            master.attributes.append(AttributeMapping(column=c, property_id=prop_id))

    relationships: list[RelationshipMapping] = []
    for other in entities[1:]:
        options: list[tuple[str, str, str]] = []
        for prop in view.object_properties.values():
            if view.is_a(master.class_id, prop.domain_id) and view.is_a(other.class_id, prop.range_id):
                options.append((prop.id, master.key, other.key))
            elif view.is_a(other.class_id, prop.domain_id) and view.is_a(master.class_id, prop.range_id):
                options.append((prop.id, other.key, master.key))
        if len(options) == 1:
            prop_id, subject, obj = options[0]
            relationships.append(RelationshipMapping(subject=subject, object=obj, predicate_id=prop_id))
            notes.append(f"Relationship '{view.property_label(prop_id)}' links {master_label} and "
                         f"{view.class_label(other.class_id)} in the direction defined by the ontology.")
        elif options:
            notes.append(
                f"Several relationships could link {master_label} and {view.class_label(other.class_id)}; choose one."
            )
    return MappingSpec(entities=entities, relationships=relationships), notes
