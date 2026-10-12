"""Deterministic fact validation in two independent categories.

* Structural validation checks a fact against the selected published ontology version: classes and
  predicates exist, domain and range hold (with subclass inheritance), literals parse as the
  declared datatype and the referenced entities are identified. A reversed relationship is
  detected and explained but never repaired.
* Evidence validation checks that the fact is traceable to a source location and supported by it:
  the structured record itself, or a quote located verbatim in the document text that mentions
  the entities (or value) involved.

Status: any structural failure -> REJECTED; an ambiguous value, an ambiguous entity or inadequate evidence ->
QUARANTINED; no evidence at all -> REJECTED; otherwise ACCEPTED. A structurally valid fact is
not assumed to be supported, and neither check proves factual correctness.

Attribute values reach this module already normalised (see :mod:`app.modules.kg.normalization`): the
datatype comes from the published ontology version, an unambiguous conversion is applied and recorded,
and a value that cannot be typed is rejected (not a literal of the datatype) or quarantined (ambiguous).
The strict SHACL and structural checks then run on the typed literal exactly as before.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.kg.canonical import STRUCTURED, FactCandidate, Mention
from app.modules.kg.normalization import (
    AMBIGUOUS,
    FAILED,
    NORMALIZED,
    NUMERIC_DATATYPES,
    ValueNormalization,
    normalize_value,
    same_value,
)
from app.modules.kg.ontology_view import OntologyView
from app.modules.kg.policy import SIGNATURE_CODES, ValidationPolicy
from app.modules.kg.resolution import MISSING_IDENTIFIER, ResolvedEntity, normalize_name

ACCEPTED = "accepted"
REJECTED = "rejected"
QUARANTINED = "quarantined"

SUPPORTED = "supported"
WEAK = "weak"
UNLOCATED = "unlocated"
MISSING = "missing"
_EVIDENCE_RANK = {SUPPORTED: 3, WEAK: 2, UNLOCATED: 1, MISSING: 0}
# A failed check with one of these codes holds the fact for review (quarantine) instead of rejecting it:
# the value could be read more than one way, so it is neither converted nor called invalid.
HOLD_CODES = frozenset({"literal_ambiguous"})


@dataclass
class Check:
    code: str
    passed: bool
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "passed": self.passed, "message": self.message}


@dataclass
class Assessment:
    structural: list[Check] = field(default_factory=list)
    resolution: list[Check] = field(default_factory=list)
    evidence: list[Check] = field(default_factory=list)
    evidence_status: str = MISSING
    canonical_value: str | None = None
    # How the raw attribute value was typed (None for entities, relationships and historical builds).
    normalization: ValueNormalization | None = None
    status: str = REJECTED
    reasons: list[str] = field(default_factory=list)
    # Policy, SHACL and entailment lanes. ``policy`` is None for the original evaluation (no SHACL / entailment lanes).
    policy: ValidationPolicy | None = None
    shacl: list[dict[str, Any]] = field(default_factory=list)
    entailment: list[Check] = field(default_factory=list)
    inferred_types: list[str] = field(default_factory=list)

    def _blocking_structural(self) -> list[Check]:
        failed = [c for c in self.structural if not c.passed and c.code not in HOLD_CODES]
        if self.policy is not None and self.policy.signature != "reject":
            return [c for c in failed if c.code not in SIGNATURE_CODES]
        return failed

    def _held_structural(self) -> list[Check]:
        return [c for c in self.structural if not c.passed and c.code in HOLD_CODES]

    @property
    def held(self) -> bool:
        """True when the only thing holding the fact back is an ambiguous value (it is quarantined, not rejected)."""
        return bool(self._held_structural()) and not self._blocking_structural()

    def finalize(self) -> "Assessment":
        blocking = self._blocking_structural()
        held = self._held_structural()
        resolution_ok = all(c.passed for c in self.resolution)
        outcomes = {r["outcome"] for r in self.shacl}
        entailment_ok = all(c.passed for c in self.entailment)
        if blocking or "reject" in outcomes:
            self.status = REJECTED
        elif held or not resolution_ok or "quarantine" in outcomes:
            self.status = QUARANTINED
        elif self.evidence_status == MISSING:
            self.status = REJECTED
        elif self.evidence_status != SUPPORTED:
            self.status = QUARANTINED
        elif not entailment_ok:
            self.status = QUARANTINED
        else:
            self.status = ACCEPTED
        self.reasons = [
            *(c.message for c in blocking),
            *(c.message for c in held),
            *(c.message for group in (self.resolution, self.evidence) for c in group if not c.passed),
            *(f"SHACL: {r['message']}" for r in self.shacl if r["outcome"] in ("reject", "quarantine")),
            *(c.message for c in self.entailment if not c.passed),
        ]
        return self

    def lanes_dict(self) -> dict[str, Any] | None:
        if self.policy is None:
            return None
        blocking = self._blocking_structural()
        relaxed = [c.as_dict() for c in self.structural if not c.passed and c not in blocking and c.code not in HOLD_CODES]
        return {
            "policy": {"id": self.policy.id, "name": self.policy.name, "relaxed_checks": relaxed},
            "shacl": {
                "conforms": not self.shacl,
                "results": self.shacl,
            },
            "entailment": {
                "ran": self.policy.entailment,
                "passed": all(c.passed for c in self.entailment),
                "checks": [c.as_dict() for c in self.entailment],
                "inferred_types": self.inferred_types,
            },
        }

    def structural_dict(self) -> dict[str, Any]:
        return {"passed": all(c.passed for c in self.structural), "checks": [c.as_dict() for c in self.structural]}

    def evidence_dict(self) -> dict[str, Any]:
        return {"status": self.evidence_status, "checks": [c.as_dict() for c in self.evidence]}

    def resolution_dict(self) -> dict[str, Any]:
        return {"passed": all(c.passed for c in self.resolution), "checks": [c.as_dict() for c in self.resolution]}


# ---------------------------------------------------------------------------------- helpers

# A whole number token of a quote: not inside a longer word or number, and not the digits of an identifier (S-101).
_QUOTE_NUMBER = re.compile(r"(?<![\w.,])(?<!\w[-+])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|[.,]\d)")


def _quote_states_number(quote: str | None, normalization: ValueNormalization | None) -> bool:
    """True when a normalised numeric value equals a number written in the quote (compared by value, whole tokens only)."""
    if (
        normalization is None
        or normalization.status != NORMALIZED
        or normalization.datatype not in NUMERIC_DATATYPES
        or normalization.normalized_value is None
    ):
        return False
    try:
        target = Decimal(normalization.normalized_value)
        return any(Decimal(m.group().replace(",", "")) == target for m in _QUOTE_NUMBER.finditer(quote or ""))
    except InvalidOperation:
        return False


def mentions_any(text: str | None, names: list[str]) -> bool:
    haystack = f" {normalize_name(text or '')} "
    return any(f" {n} " in haystack for n in (normalize_name(x) for x in names) if n)


def _entity_names(entity: ResolvedEntity | None, mention: Mention | None) -> list[str]:
    names: list[str] = []
    if mention is not None:
        names += mention.names
    if entity is not None:
        names += [entity.label, *entity.aliases] + ([entity.identifier] if entity.identifier else [])
    return names


def _describe(entity: ResolvedEntity | None, fallback: str | None, view: OntologyView) -> str:
    if entity is None:
        return f"'{fallback or '?'}'"
    cls = view.class_label(entity.class_id, entity.class_ref)
    return f"'{entity.label}' ({cls})"


# ---------------------------------------------------------------------------------- entities


def mention_evidence(mention: Mention) -> tuple[str, str]:
    source = mention.source
    if mention.origin == STRUCTURED:
        if mention.reference_only:
            return WEAK, f"Referenced only by {source.location}; that row does not establish the entity."
        mapping = f" (mapping '{source.mapping_name}')" if source.mapping_name else ""
        return SUPPORTED, f"Established by {source.location}{mapping}."
    if not source.llm_quote:
        return MISSING, "The model provided no evidence quote."
    if not source.located:
        return UNLOCATED, f"The quoted evidence could not be located in {source.document_name}."
    if mentions_any(source.quote, mention.names):
        return SUPPORTED, f"Named in {source.location}."
    return WEAK, f"The located quote in {source.location} does not name '{mention.label}'."


def assess_entity_structure(entity: ResolvedEntity, view: OntologyView) -> Assessment:
    """Structural (and resolution) checks for the fact 'entity is an instance of its class'."""
    result = Assessment()
    if entity.class_id and entity.class_id in view.classes:
        result.structural.append(Check("class_defined", True, f"Class {view.class_label(entity.class_id)} is defined."))
    else:
        result.structural.append(
            Check("class_defined", False, f"Class '{entity.class_ref}' is not defined in {view.name} {view.version}.")
        )
    if entity.method == MISSING_IDENTIFIER:
        result.structural.append(Check("identifier_present", False, entity.notes[0] if entity.notes else "No identifier."))
    else:
        result.structural.append(Check("identifier_present", True, "The entity is identified."))
    if entity.ambiguous:
        result.resolution.append(Check("unambiguous", False, entity.notes[0] if entity.notes else "Ambiguous entity."))
    return result


def assess_entity_evidence(result: Assessment, entity: ResolvedEntity) -> Assessment:
    best = (MISSING, "No source mentions this entity.")
    for mention in entity.mentions:
        status, message = mention_evidence(mention)
        if _EVIDENCE_RANK[status] > _EVIDENCE_RANK[best[0]]:
            best = (status, message)
    result.evidence_status = best[0]
    result.evidence = [
        Check("source_traceable", bool(entity.mentions), f"{len(entity.mentions)} source mention(s)."),
        Check("supporting_evidence", best[0] == SUPPORTED, best[1]),
    ]
    return result.finalize()


# ---------------------------------------------------------------------------------- facts


def _reference_checks(
    result: Assessment, role: str, entity: ResolvedEntity | None, raw_ref: str | None, view: OntologyView
) -> None:
    title = role.capitalize()
    if entity is None:
        result.structural.append(
            Check(f"{role}_reference", False, f"{title} '{raw_ref or '?'}' does not refer to an extracted entity.")
        )
        return
    if entity.class_id and entity.class_id in view.classes:
        result.structural.append(
            Check(f"{role}_class", True, f"{title} {_describe(entity, None, view)} is an instance of a defined class.")
        )
    else:
        result.structural.append(
            Check(f"{role}_class", False, f"{title} class '{entity.class_ref}' is not defined in {view.name} {view.version}.")
        )
    if entity.method == MISSING_IDENTIFIER:
        result.structural.append(Check(f"{role}_identifier", False, f"{title} has no identifier."))
    if entity.ambiguous:
        result.resolution.append(
            Check(f"{role}_unambiguous", False, f"{title}: {entity.notes[0] if entity.notes else 'ambiguous'}")
        )


def assess_relationship_structure(
    fact: FactCandidate, subject: ResolvedEntity | None, obj: ResolvedEntity | None, view: OntologyView
) -> Assessment:
    result = Assessment()
    prop = view.object_properties.get(fact.predicate_id or "")
    if prop is None:
        if fact.wrong_kind == "datatype_property":
            message = f"'{fact.predicate_ref}' is an attribute in the ontology, not a relationship."
        else:
            message = f"Relationship '{fact.predicate_ref}' is not defined in {view.name} {view.version}."
        result.structural.append(Check("predicate_defined", False, message))
    else:
        result.structural.append(Check("predicate_defined", True, f"Relationship '{prop.label}' is defined."))
    _reference_checks(result, "subject", subject, fact.subject_ref, view)
    _reference_checks(result, "object", obj, fact.object_ref, view)

    subject_cls = subject.class_id if subject else None
    object_cls = obj.class_id if obj else None
    if prop is not None and subject_cls in view.classes and object_cls in view.classes:
        domain_ok = view.satisfies(subject_cls, prop.domain_id)
        range_ok = view.satisfies(object_cls, prop.range_id)
        defined = f"{view.constraint_label(prop.domain_id)} \u2192 {prop.label} \u2192 {view.constraint_label(prop.range_id)}"
        stated = f"{view.class_label(subject_cls)} \u2192 {prop.label} \u2192 {view.class_label(object_cls)}"
        reversed_ok = view.satisfies(object_cls, prop.domain_id) and view.satisfies(subject_cls, prop.range_id)
        if not (domain_ok and range_ok) and reversed_ok:
            result.structural.append(
                Check(
                    "direction",
                    False,
                    f"Direction reversed: the ontology defines {defined}, but this fact states {stated}. "
                    "The fact is rejected; it is not reversed or repaired automatically.",
                )
            )
        result.structural.append(
            Check(
                "domain",
                domain_ok,
                f"Subject class {view.class_label(subject_cls)} "
                + ("satisfies" if domain_ok else "violates")
                + f" the domain {view.constraint_label(prop.domain_id)} of '{prop.label}'.",
            )
        )
        result.structural.append(
            Check(
                "range",
                range_ok,
                f"Object class {view.class_label(object_cls)} "
                + ("satisfies" if range_ok else "violates")
                + f" the range {view.constraint_label(prop.range_id)} of '{prop.label}'.",
            )
        )
    return result


def assess_attribute_structure(
    fact: FactCandidate,
    subject: ResolvedEntity | None,
    view: OntologyView,
    normalization: ValueNormalization | None = None,
) -> Assessment:
    result = Assessment()
    prop = view.datatype_properties.get(fact.predicate_id or "")
    if prop is None:
        if fact.wrong_kind == "object_property":
            message = f"'{fact.predicate_ref}' is a relationship in the ontology, not an attribute."
        else:
            message = f"Attribute '{fact.predicate_ref}' is not defined in {view.name} {view.version}."
        result.structural.append(Check("property_defined", False, message))
    else:
        result.structural.append(Check("property_defined", True, f"Attribute '{prop.label}' is defined."))
    _reference_checks(result, "subject", subject, fact.subject_ref, view)
    subject_cls = subject.class_id if subject else None
    if prop is not None and subject_cls in view.classes:
        domain_ok = view.satisfies(subject_cls, prop.domain_id)
        result.structural.append(
            Check(
                "domain",
                domain_ok,
                f"{view.class_label(subject_cls)} "
                + ("is within" if domain_ok else "is outside")
                + f" the domain {view.constraint_label(prop.domain_id)} of '{prop.label}'.",
            )
        )
    if prop is not None:
        spec = view.value_spec(prop.id)
        assert spec is not None
        normalization = normalization or normalize_value(fact.value, spec)
        result.normalization = normalization
        result.canonical_value = normalization.normalized_value
        if normalization.status == AMBIGUOUS:
            result.structural.append(Check("literal_ambiguous", False, normalization.message))
        else:
            result.structural.append(
                Check("literal_datatype", normalization.status != FAILED, normalization.message)
            )
    return result


def assess_fact_evidence(
    result: Assessment,
    fact: FactCandidate,
    *,
    subject: ResolvedEntity | None,
    obj: ResolvedEntity | None,
    subject_mention: Mention | None,
    object_mention: Mention | None,
    entity_status: dict[str, Assessment],
    view: OntologyView,
) -> Assessment:
    """Evidence validation, independent of the structural result. Finalises the fact status."""
    source = fact.source
    checks = [
        Check("source_traceable", bool(source.document_id), f"Source: {source.document_name}."),
        Check(
            "source_location",
            source.row_number is not None or source.chunk_id is not None,
            f"Location: {source.location}.",
        ),
    ]
    if fact.kind == "relationship":
        required = [
            (_describe(subject, fact.subject_ref, view), _entity_names(subject, subject_mention)),
            (_describe(obj, fact.object_ref, view), _entity_names(obj, object_mention)),
        ]
        endpoints = [("subject", subject), ("object", obj)]
    else:
        required = [(f"the value '{fact.value}'", [fact.value or ""])]
        endpoints = [("subject", subject)]

    if fact.origin == STRUCTURED:
        status = SUPPORTED
        mapping = f" (mapping '{source.mapping_name}')" if source.mapping_name else ""
        checks.append(Check("supporting_evidence", True, f"Stated by {source.location}{mapping}."))
    elif not source.llm_quote:
        status = MISSING
        checks.append(Check("supporting_evidence", False, "The model provided no evidence quote."))
    elif not source.located:
        status = UNLOCATED
        checks.append(
            Check(
                "supporting_evidence",
                False,
                f"The quoted evidence could not be located in {source.document_name}: "
                f"\u201c{(source.llm_quote or '')[:120]}\u201d.",
            )
        )
    else:
        missing = [what for what, names in required if not mentions_any(source.quote, names)]
        if missing and fact.kind == "attribute" and _quote_states_number(source.quote, result.normalization):
            missing = []  # the quote states the same number, written differently (94.5% for the value 94.50)
        if missing:
            status = WEAK
            checks.append(
                Check(
                    "supporting_evidence",
                    False,
                    f"The located quote does not mention {', '.join(missing)}, so it does not support this fact.",
                )
            )
        else:
            status = SUPPORTED
            checks.append(Check("supporting_evidence", True, f"Quote located in {source.location}."))

    for role, entity in endpoints:
        if entity is None:
            continue
        endpoint = entity_status.get(entity.vertex_id)
        if endpoint is None or endpoint.evidence_status == SUPPORTED:
            continue
        if status == SUPPORTED:
            status = WEAK
        checks.append(
            Check(
                f"{role}_established",
                False,
                f"{role.capitalize()} {_describe(entity, None, view)} is not established by any source "
                f"record or located text ({endpoint.evidence_status} evidence).",
            )
        )
    result.evidence_status = status
    result.evidence = checks
    return result.finalize()


def quarantine_conflicts(
    items: list[tuple[FactCandidate, Assessment, ResolvedEntity | None]], view: OntologyView
) -> int:
    """Single-valued attributes hold one value per entity; later conflicting values are quarantined."""
    chosen: dict[tuple[str, str], tuple[str, FactCandidate]] = {}
    conflicts = 0
    ordered = sorted(
        (i for i in items if i[1].status == ACCEPTED and i[2] is not None),
        key=lambda i: i[0].origin != STRUCTURED,
    )
    for fact, assessment, entity in ordered:
        prop = view.datatype_properties.get(fact.predicate_id or "")
        if prop is None or prop.multi_valued or entity is None:
            continue
        key = (entity.vertex_id, prop.id)
        value = assessment.canonical_value or ""
        if key not in chosen:
            chosen[key] = (value, fact)
            continue
        kept_value, kept_fact = chosen[key]
        if not same_value(value, kept_value, prop.datatype.value):
            conflicts += 1
            assessment.resolution.append(
                Check(
                    "single_value",
                    False,
                    f"Conflicts with '{kept_value}' from {kept_fact.source.location}; '{prop.label}' is single-valued.",
                )
            )
            assessment.finalize()
    return conflicts
