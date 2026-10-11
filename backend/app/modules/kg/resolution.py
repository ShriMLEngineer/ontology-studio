"""Deterministic entity resolution.

Order of precedence:

1. Business key - same class (or a compatible sub/superclass for text mentions), same key
   namespace and same normalised identifier: merged.
2. Label or configured alias - a mention without an identifier is merged only if exactly one
   identified entity of a compatible class carries that normalised name.
3. More than one candidate - the mention is flagged *ambiguous* and kept separate; its facts are
   quarantined for review. Similarity is never used to merge.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.modules.kg.canonical import STRUCTURED, Mention
from app.modules.kg.ontology_view import OntologyView

BUSINESS_KEY = "business_key"
LABEL = "label"
ALIAS = "alias"
NEW = "new"
AMBIGUOUS = "ambiguous"
UNRESOLVED_CLASS = "unresolved_class"
MISSING_IDENTIFIER = "missing_identifier"


def normalize_identifier(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def normalize_name(value: str) -> str:
    return " ".join(re.findall(r"[0-9a-z]+", unicodedata.normalize("NFKC", value).casefold()))


def stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"v{digest[:24]}"


@dataclass
class ResolvedEntity:
    vertex_id: str
    class_id: str | None
    class_ref: str
    identifier: str | None
    key_namespace: str
    method: str
    mentions: list[Mention] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return self.method == AMBIGUOUS

    @property
    def has_master_record(self) -> bool:
        return any(m.origin == STRUCTURED and not m.reference_only for m in self.mentions)

    @property
    def label(self) -> str:
        ordered = sorted(
            self.mentions, key=lambda m: (m.origin != STRUCTURED, m.reference_only, m.label is None)
        )
        for mention in ordered:
            if mention.label:
                return mention.label
        return self.identifier or (self.mentions[0].label if self.mentions else "") or self.vertex_id

    @property
    def aliases(self) -> list[str]:
        names: list[str] = []
        for mention in self.mentions:
            names += [n for n in (mention.label, *mention.aliases) if n]
        label = self.label
        return [n for n in dict.fromkeys(names) if n != label]

    def names(self) -> set[str]:
        values = {normalize_name(n) for m in self.mentions for n in m.names}
        if self.identifier:
            values.add(normalize_name(self.identifier))
        return {v for v in values if v}


@dataclass
class ResolutionResult:
    entities: dict[str, ResolvedEntity]
    by_mention: dict[str, str]
    mention_method: dict[str, str]

    def entity_of(self, mention_key: str | None) -> ResolvedEntity | None:
        if mention_key is None:
            return None
        vertex_id = self.by_mention.get(mention_key)
        return self.entities.get(vertex_id) if vertex_id else None

    def stats(self) -> dict[str, int]:
        methods: dict[str, int] = {}
        for method in self.mention_method.values():
            methods[method] = methods.get(method, 0) + 1
        return {
            "mentions": len(self.by_mention),
            "entities": len(self.entities),
            "merged_mentions": len(self.by_mention) - len(self.entities),
            "ambiguous_entities": sum(1 for e in self.entities.values() if e.ambiguous),
            "unresolved_class_entities": sum(1 for e in self.entities.values() if e.method == UNRESOLVED_CLASS),
            **{f"mentions_{k}": v for k, v in sorted(methods.items())},
        }


def resolve_entities(mentions: list[Mention], view: OntologyView) -> ResolutionResult:
    entities: dict[str, ResolvedEntity] = {}
    by_mention: dict[str, str] = {}
    method_of: dict[str, str] = {}

    def attach(entity: ResolvedEntity, mention: Mention, method: str) -> None:
        entity.mentions.append(mention)
        by_mention[mention.key] = entity.vertex_id
        method_of[mention.key] = method

    # 1. business keys within a class
    for mention in mentions:
        if not (mention.class_id and mention.identifier):
            continue
        key = normalize_identifier(mention.identifier)
        vertex_id = stable_id("key", mention.class_id, mention.key_namespace, key)
        entity = entities.get(vertex_id)
        if entity is None:
            entity = entities[vertex_id] = ResolvedEntity(
                vertex_id=vertex_id,
                class_id=mention.class_id,
                class_ref=mention.class_ref,
                identifier=mention.identifier,
                key_namespace=mention.key_namespace,
                method=BUSINESS_KEY,
            )
        attach(entity, mention, BUSINESS_KEY)

    # Text mentions may classify an identified entity more generally or more specifically.
    for vertex_id, entity in list(entities.items()):
        if any(m.origin == STRUCTURED for m in entity.mentions):
            continue
        key = normalize_identifier(entity.identifier or "")
        targets = [
            other
            for other in entities.values()
            if other is not entity
            and any(m.origin == STRUCTURED for m in other.mentions)
            and other.key_namespace == entity.key_namespace
            and normalize_identifier(other.identifier or "") == key
            and view.compatible(other.class_id, entity.class_id)
        ]
        if len(targets) == 1:
            target = targets[0]
            for mention in entity.mentions:
                attach(target, mention, BUSINESS_KEY)
            target.notes.append(
                f"Text mention classified as {view.class_label(entity.class_id)} merged by business key "
                f"'{entity.identifier}' (compatible with {view.class_label(target.class_id)})."
            )
            del entities[vertex_id]

    identified = [e for e in entities.values() if e.identifier]

    # 2. label / alias for mentions without an identifier
    for mention in mentions:
        if mention.key in by_mention or not mention.class_id:
            continue
        name = normalize_name(mention.label or "")
        if mention.origin == STRUCTURED or not name:
            vertex_id = stable_id("unidentified", mention.key)
            entity = entities[vertex_id] = ResolvedEntity(
                vertex_id=vertex_id,
                class_id=mention.class_id,
                class_ref=mention.class_ref,
                identifier=None,
                key_namespace=mention.key_namespace,
                method=MISSING_IDENTIFIER,
            )
            column = f" (column '{mention.id_column}' is empty)" if mention.id_column else ""
            entity.notes.append(f"No identifier{column}; the entity cannot be resolved.")
            attach(entity, mention, MISSING_IDENTIFIER)
            continue
        candidates = [e for e in identified if view.compatible(e.class_id, mention.class_id) and name in e.names()]
        if len(candidates) == 1:
            target = candidates[0]
            exact = any(normalize_name(m.label or "") == name for m in target.mentions) or (
                normalize_name(target.identifier or "") == name
            )
            method = LABEL if exact else ALIAS
            attach(target, mention, method)
            target.notes.append(f"'{mention.label}' from {mention.source.location} matched by {method}.")
            continue
        if len(candidates) > 1:
            vertex_id = stable_id("ambiguous", mention.class_id, name)
            entity = entities.get(vertex_id)
            if entity is None:
                entity = entities[vertex_id] = ResolvedEntity(
                    vertex_id=vertex_id,
                    class_id=mention.class_id,
                    class_ref=mention.class_ref,
                    identifier=None,
                    key_namespace="",
                    method=AMBIGUOUS,
                    candidates=[
                        {"vertex_id": c.vertex_id, "label": c.label, "identifier": c.identifier} for c in candidates
                    ],
                )
                entity.notes.append(
                    f"'{mention.label}' matches {len(candidates)} entities ("
                    + ", ".join(f"{c.label} [{c.identifier}]" for c in candidates)
                    + "); not merged automatically."
                )
            attach(entity, mention, AMBIGUOUS)
            continue
        vertex_id = stable_id("label", mention.class_id, name)
        entity = entities.get(vertex_id)
        if entity is None:
            entity = entities[vertex_id] = ResolvedEntity(
                vertex_id=vertex_id,
                class_id=mention.class_id,
                class_ref=mention.class_ref,
                identifier=None,
                key_namespace="",
                method=NEW,
            )
            entity.notes.append("No identified entity matches this name; kept as a new entity identified by its name.")
        attach(entity, mention, NEW if len(entity.mentions) == 0 else LABEL)

    # 3. mentions whose class is not in the ontology version
    for mention in mentions:
        if mention.key in by_mention:
            continue
        name = normalize_identifier(mention.identifier or "") or normalize_name(mention.label or "") or mention.key
        vertex_id = stable_id("unresolved", normalize_name(mention.class_ref), name)
        entity = entities.get(vertex_id)
        if entity is None:
            entity = entities[vertex_id] = ResolvedEntity(
                vertex_id=vertex_id,
                class_id=None,
                class_ref=mention.class_ref,
                identifier=mention.identifier,
                key_namespace=mention.key_namespace,
                method=UNRESOLVED_CLASS,
            )
            entity.notes.append(f"Class '{mention.class_ref}' is not defined in {view.name} {view.version}.")
        attach(entity, mention, UNRESOLVED_CLASS)

    return ResolutionResult(entities=entities, by_mention=by_mention, mention_method=method_of)
