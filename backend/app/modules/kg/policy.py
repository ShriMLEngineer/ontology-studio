"""Validation policies: how the results of each validation lane determine a fact's status.

Policies are immutable and versioned (``key/version``); a build records the full policy
configuration in its frozen configuration, so later releases can add policies or new versions
without re-judging earlier builds. ``application-strict/1`` (the default) reproduces the Phase 3
outcome exactly; SHACL adds information (missing required values become warnings) but never
changes the status of a fact that Phase 3 accepted, unless an SME authored a shape with severity
Violation.
"""

from dataclasses import asdict, dataclass, field
from typing import Literal

Outcome = Literal["reject", "quarantine", "warn", "info"]
SignatureMode = Literal["reject", "shacl", "infer_and_flag"]
SIGNATURE_CODES = frozenset({"domain", "range", "direction"})
DEFAULT_POLICY_ID = "application-strict/1"


@dataclass(frozen=True)
class ValidationPolicy:
    id: str
    name: str
    description: str
    signature: SignatureMode
    use_signature_shapes: bool
    entailment: bool
    shacl: dict[str, Outcome] = field(default_factory=dict)

    def config(self) -> dict[str, object]:
        return asdict(self)

    def shacl_outcome(self, *, severity: str, component: str, origin: str, role: str) -> Outcome:
        if role == "signature":
            return "reject" if self.signature == "shacl" else "info"
        if origin == "generated" and component == "MinCountConstraintComponent":
            return self.shacl["generated_min_count"]
        if origin == "generated" and component == "MaxCountConstraintComponent":
            return self.shacl["generated_max_count"]
        return self.shacl.get(severity, "reject")


_SHACL_DEFAULTS: dict[str, Outcome] = {
    "Violation": "reject",
    "Warning": "warn",
    "Info": "info",
    # Generated cardinalities duplicate application semantics: a missing required value is reported
    # (Phase 3 only counted it in a metric) and single-value conflicts are quarantined by the
    # application's conflict resolution, which knows which value was stated first.
    "generated_min_count": "warn",
    "generated_max_count": "info",
}

POLICIES: dict[str, ValidationPolicy] = {
    p.id: p
    for p in (
        ValidationPolicy(
            id="application-strict/1",
            name="Application strict",
            description=(
                "Phase 3 behaviour. Domain and range are enforced by the application check (a reversed relationship "
                "is rejected and diagnosed). SHACL constraint violations reject; missing required values are "
                "warnings; single-value conflicts are quarantined."
            ),
            signature="reject",
            use_signature_shapes=False,
            entailment=False,
            shacl=dict(_SHACL_DEFAULTS),
        ),
        ValidationPolicy(
            id="shacl-signature/1",
            name="SHACL signatures",
            description=(
                "Standards-aligned closed-world validation: domain and range are enforced by generated SHACL "
                "signature shapes (sh:targetSubjectsOf / sh:targetObjectsOf + sh:class). The application "
                "signature check is reported as information."
            ),
            signature="shacl",
            use_signature_shapes=True,
            entailment=False,
            shacl=dict(_SHACL_DEFAULTS),
        ),
        ValidationPolicy(
            id="infer-and-flag/1",
            name="Infer and flag",
            description=(
                "Open-world exploration: a fact outside the declared domain or range is not rejected. The OWL 2 RL "
                "entailment lane records the types it implies: an implication that refines the asserted class (a "
                "subclass) is accepted; one that is incompatible with it (neither superclass nor subclass), or an "
                "OWL 2 RL inconsistency such as a disjointness violation, quarantines the fact for review. "
                "Inferred triples are never persisted."
            ),
            signature="infer_and_flag",
            use_signature_shapes=False,
            entailment=True,
            shacl=dict(_SHACL_DEFAULTS),
        ),
    )
}


def get_policy(policy_id: str | None) -> ValidationPolicy:
    return POLICIES[policy_id or DEFAULT_POLICY_ID]
