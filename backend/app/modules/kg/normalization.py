"""Ontology-driven normalisation of literal values, between extraction and candidate-fact validation.

LLM extraction and structured mappings both hand over *raw* text (``"97.0%"``, ``"98.2 percentg"``,
``"Yes."``). This module turns such text into a correctly typed xsd literal **only when the conversion is
unambiguous**, and always reports what it did so that every decision can be audited:

* the target datatype comes from the attribute's definition in the selected, immutable published
  ontology version (never from the value, never guessed);
* a value that is already a valid literal of that datatype is kept exactly as before (``exact``), or
  rewritten to its canonical lexical form (``normalized``);
* a value that needs a conversion is converted only by an explicit, documented rule (``normalized``);
* a value with an unrecognised or undeclared unit, or with more than one reading, is **not** converted
  (``ambiguous``); a value that is not a literal of the datatype at all is ``failed``.

Percentages. An attribute is *percentage-valued* when its own definition (label, local name, alias or
description) names a percentage (the words percent / percentage / pct, or the % sign) and does not
document a different (0-1) scale. For such an attribute a number followed by a percent unit
(``97.0%``, ``97 percent``, ``98.2 percentg``) is stored as the bare number on the **0-100 scale**
(``97.0``). Nothing is rescaled and nothing is stripped for any other attribute: a decimal attribute
that is not defined as a percentage keeps ``97.0%`` as an ambiguous value.

The functions are pure; the decision is recorded in :class:`ValueNormalization`.
"""

import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from rdflib.namespace import XSD

from app.modules.ontology.domain import DatatypePropertyDefinition

EXACT = "exact"  # already a valid literal of the datatype, lexical form unchanged
NORMALIZED = "normalized"  # converted (or rewritten to the canonical form) by a documented rule
AMBIGUOUS = "ambiguous"  # more than one reading, or a unit the ontology does not define: not converted
FAILED = "failed"  # not a literal of the datatype

PERCENT = "percent"
PERCENT_SCALE = "0-100"

NUMERIC_DATATYPES = frozenset({"integer", "decimal", "float", "double", "int", "long"})
_INTEGER_DATATYPES = frozenset({"integer", "int", "long"})

# ---------------------------------------------------------------------------------- strict literals

_INTEGER = re.compile(r"^[+-]?\d+$")
_DECIMAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
# Thousands grouping never starts with a zero group: "0,234" is not 234.
_GROUPED_DECIMAL = re.compile(r"^[+-]?[1-9]\d{0,2}(,\d{3})+(\.\d+)?$")
_TRUE = {"true", "yes", "1"}
_FALSE = {"false", "no", "0"}
_FLOAT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
_GYEAR = re.compile(r"^-?\d{4,}(Z|[+-]\d{2}:\d{2})?$")
_BOUNDED_INTEGERS = {"int": (-(2**31), 2**31 - 1), "long": (-(2**63), 2**63 - 1)}


def parse_literal(value: str, datatype: str) -> tuple[bool, str | None, str]:
    """Return (valid, canonical value, message) for ``value`` as an XSD ``datatype``.

    This is the strict parser: it accepts only text that is already a literal of the datatype (plus the
    long-standing canonical rewrites: grouped thousands, yes/no, surrounding whitespace). Conversions
    live in :func:`normalize_value`.
    """
    text = value.strip()
    if not text:
        return False, None, "The value is empty."
    if datatype == "string":
        return True, text, ""
    if datatype == "integer":
        if _INTEGER.match(text):
            return True, str(int(text)), ""
        return False, None, f"'{text}' is not an integer."
    if datatype == "decimal":
        candidate = text.replace(",", "") if _GROUPED_DECIMAL.match(text) else text
        if _DECIMAL.match(candidate):
            try:
                return True, str(Decimal(candidate)), ""
            except InvalidOperation:
                pass
        return False, None, f"'{text}' is not a decimal number."
    if datatype == "boolean":
        lowered = text.lower()
        if lowered in _TRUE | _FALSE:
            return True, "true" if lowered in _TRUE else "false", ""
        return False, None, f"'{text}' is not a boolean."
    if datatype == "date":
        try:
            return True, date.fromisoformat(text).isoformat(), ""
        except ValueError:
            return False, None, f"'{text}' is not an ISO 8601 date (YYYY-MM-DD)."
    if datatype == "dateTime":
        try:
            return True, datetime.fromisoformat(text).isoformat(), ""
        except ValueError:
            return False, None, f"'{text}' is not an ISO 8601 date-time."
    if datatype == "anyURI":
        parts = urlsplit(text)
        if parts.scheme and (parts.netloc or parts.scheme in {"urn", "mailto"}):
            return True, text, ""
        return False, None, f"'{text}' is not an absolute URI."
    if datatype in _BOUNDED_INTEGERS:
        low, high = _BOUNDED_INTEGERS[datatype]
        if _INTEGER.match(text) and low <= int(text) <= high:
            return True, str(int(text)), ""
        return False, None, f"'{text}' is not a valid xsd:{datatype} ({low} to {high})."
    if datatype in ("float", "double"):
        candidate = text.replace(",", "") if _GROUPED_DECIMAL.match(text) else text
        if candidate in ("INF", "-INF", "+INF", "NaN") or _FLOAT.match(candidate):
            try:
                number = float(candidate.replace("INF", "inf").replace("NaN", "nan"))
            except ValueError:
                number = None
            if number is not None:
                return True, repr(number) if candidate not in ("INF", "-INF", "+INF", "NaN") else candidate, ""
        return False, None, f"'{text}' is not a valid xsd:{datatype}."
    if datatype == "time":
        try:
            return True, time.fromisoformat(text).isoformat(), ""
        except ValueError:
            return False, None, f"'{text}' is not an ISO 8601 time (hh:mm:ss)."
    if datatype == "gYear":
        if _GYEAR.match(text):
            return True, text, ""
        return False, None, f"'{text}' is not a year (YYYY)."
    return False, None, f"Unsupported datatype '{datatype}'."


# ---------------------------------------------------------------------------------- what the ontology says

_PERCENT_WORDS = frozenset({"percent", "percents", "percentage", "percentages", "pct"})
# A definition that documents a 0-1 / fractional scale conflicts with the 0-100 percentage scale ...
_UNIT_INTERVAL = re.compile(
    r"\b0(?:\.0+)?\s*(?:-|\u2013|\u2014|to|and)\s*1(?:\.0+)?\b|\bfraction(?:al)?\b|\bproportion(?:al)?\b|\bunit interval\b",
    re.IGNORECASE,
)
# ... unless it also states the 0-100 scale explicitly.
_HUNDRED_SCALE = re.compile(
    r"\b0(?:\.0+)?\s*(?:-|\u2013|\u2014|to)\s*100(?:\.0+)?\b|\bout of 100\b|\bper hundred\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ValueSpec:
    """What the published ontology says about an attribute's values."""

    datatype: str
    label: str = ""
    unit: str | None = None  # "percent" when the definition names a percentage
    scale: str | None = None  # "0-100" when percent values can be stored on the documented scale
    note: str | None = None  # why the declared unit cannot be relied on


def _words(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return re.findall(r"[a-z]+", spaced.lower())


def _names_percentage(text: str) -> bool:
    return "%" in text or any(word in _PERCENT_WORDS for word in _words(text))


def value_spec_for(prop: DatatypePropertyDefinition) -> ValueSpec:
    """Derive the value specification of an attribute from its (immutable, published) definition."""
    datatype = prop.datatype.value
    base = ValueSpec(datatype=datatype, label=prop.label)
    if datatype not in NUMERIC_DATATYPES:
        return base
    if not any(_names_percentage(text) for text in (prop.label, prop.local_name, *prop.aliases, prop.description)):
        return base
    if _UNIT_INTERVAL.search(prop.description) and not _HUNDRED_SCALE.search(prop.description):
        return ValueSpec(
            datatype=datatype,
            label=prop.label,
            unit=PERCENT,
            note="its definition states a 0-1 (fractional) scale, and values are only converted onto the 0-100 scale",
        )
    return ValueSpec(datatype=datatype, label=prop.label, unit=PERCENT, scale=PERCENT_SCALE)


# ---------------------------------------------------------------------------------- the audit record


@dataclass(frozen=True)
class ValueNormalization:
    """What happened to one raw value: kept for every candidate attribute fact."""

    status: str
    raw_value: str
    datatype: str
    normalized_value: str | None
    rule: str
    message: str
    unit: str | None = None
    scale: str | None = None

    @property
    def datatype_iri(self) -> str:
        return str(XSD[self.datatype])

    @property
    def usable(self) -> bool:
        return self.status in (EXACT, NORMALIZED)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "datatype_iri": self.datatype_iri}


def _record(
    status: str,
    raw: str,
    datatype: str,
    normalized: str | None,
    rule: str,
    message: str,
    *,
    unit: str | None = None,
    scale: str | None = None,
) -> ValueNormalization:
    return ValueNormalization(status, raw, datatype, normalized, rule, message, unit, scale)


# ---------------------------------------------------------------------------------- numbers and units

_NUMBER = re.compile(r"[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)")
_UNIT_WORDS = re.compile(r"[A-Za-z]+(?:[ .\-/][A-Za-z]+){0,2}")
_PERCENT_SYMBOLS = frozenset("%\uff05\ufe6a\u066a")
_CURRENCY_SYMBOLS = frozenset("$\u20ac\u00a3\u00a5")
_OTHER_SYMBOLS = frozenset("\u2030\u00b0") | _CURRENCY_SYMBOLS  # per mille, degree, currency
_PERCENT_TARGETS = ("percent", "percentage")
_NOT_PERCENT = frozenset({"percept"})  # a real word one edit away from "percent"


def _within_one_edit(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` differ by at most one insertion, deletion, substitution or transposition."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diffs = [i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]
        if len(diffs) == 1:
            return True
        return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


def _is_percent_word(folded: str) -> bool:
    if folded in _PERCENT_WORDS:
        return True
    if folded in _NOT_PERCENT or len(folded) < 6:
        return False
    return any(_within_one_edit(folded, target) for target in _PERCENT_TARGETS)


def _classify_unit(text: str) -> tuple[str, str]:
    """('percent' | 'other' | 'invalid', cleaned unit text)."""
    unit = text.strip().rstrip(".").strip()
    if unit in _PERCENT_SYMBOLS:
        return "percent", unit
    if unit in _OTHER_SYMBOLS:
        return "other", unit
    if _UNIT_WORDS.fullmatch(unit):
        folded = re.sub(r"[ .\-/]", "", unit.lower())
        return ("percent" if _is_percent_word(folded) else "other"), unit
    return "invalid", unit


def _clean_number(token: str) -> tuple[str, str | None, str]:
    """('ok' | 'ambiguous' | 'failed', cleaned number, rule or reason)."""
    if "," not in token:
        return "ok", token, ""
    if _GROUPED_DECIMAL.match(token):
        return "ok", token.replace(",", ""), "thousands-separator"
    if re.fullmatch(r"[+-]?\d+,\d+", token):
        return "ambiguous", None, "the comma could be a decimal separator (12,5 = 12.5) or a thousands separator"
    return "failed", None, "its commas are not a valid thousands separator"


def _finalize_number(cleaned: str, datatype: str) -> tuple[bool, str | None, str]:
    """Type a cleaned number token as ``datatype`` (integral decimals become integers; nothing is rounded)."""
    if datatype in _INTEGER_DATATYPES:
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            return False, None, f"'{cleaned}' is not a number."
        if number != number.to_integral_value():
            return False, None, f"'{cleaned}' is not a whole number, and values are never rounded."
        cleaned = str(int(number))
    return parse_literal(cleaned, datatype)


def _normalize_numeric(text: str, spec: ValueSpec) -> ValueNormalization:
    datatype = spec.datatype
    match = _NUMBER.search(text)
    if match is None:
        return _record(FAILED, text, datatype, None, "not-a-number", f"'{text}' is not a number.")
    prefix, suffix = text[: match.start()].strip(), text[match.end() :].strip()
    # A unit follows the number; only a currency symbol may precede it. Any other leading text (approx., ~,
    # about, USD ...) is a qualifier, not a unit, and the value is not a plain number.
    if (prefix and suffix) or (prefix and prefix not in _CURRENCY_SYMBOLS):
        return _record(FAILED, text, datatype, None, "not-a-plain-number", f"'{text}' is not a plain number.")
    kind, cleaned, detail = _clean_number(match.group(0))
    if kind == "failed":
        return _record(FAILED, text, datatype, None, "not-a-number", f"'{text}' is not a valid number: {detail}.")
    unit_text = prefix or suffix
    unit_kind, unit = _classify_unit(unit_text) if unit_text else ("none", "")
    if unit_kind == "invalid":
        return _record(FAILED, text, datatype, None, "not-a-plain-number", f"'{text}' is not a plain number.")
    if kind == "ambiguous":
        return _record(AMBIGUOUS, text, datatype, None, "decimal-comma", f"'{text}' is ambiguous: {detail}; it was not converted.")
    assert cleaned is not None
    if unit_kind == "none":
        valid, canonical, message = _finalize_number(cleaned, datatype)
        if not valid:
            return _record(FAILED, text, datatype, None, "datatype-mismatch", f"'{text}': {message}")
        rule = detail or "integral-decimal"
        return _record(NORMALIZED, text, datatype, canonical, rule, _describe(text, canonical, rule, spec))
    if unit_kind == "other":
        return _record(
            AMBIGUOUS, text, datatype, None, "unit-not-defined",
            f"'{text}' carries the unit '{unit}', which the ontology does not define for '{spec.label}'; "
            "it was neither converted nor stripped.",
            unit=unit,
        )
    # A percent unit.
    if spec.unit != PERCENT:
        return _record(
            AMBIGUOUS, text, datatype, None, "percent-not-defined",
            f"'{text}' carries a percent unit, but '{spec.label}' is not defined as a percentage in the ontology, "
            "so the value was not converted.",
            unit=PERCENT,
        )
    if spec.scale != PERCENT_SCALE:
        return _record(
            AMBIGUOUS, text, datatype, None, "percent-scale-conflict",
            f"'{text}' is a percentage, but {spec.note or 'the attribute does not document the 0-100 scale'}; "
            "it was not converted.",
            unit=PERCENT,
        )
    valid, canonical, message = _finalize_number(cleaned, datatype)
    if not valid:
        return _record(FAILED, text, datatype, None, "datatype-mismatch", f"'{text}': {message}", unit=PERCENT, scale=PERCENT_SCALE)
    return _record(
        NORMALIZED, text, datatype, canonical, "percentage-0-100",
        f"'{text}' is a percentage and '{spec.label}' is defined as one: the percent unit was removed and "
        f"{canonical} is stored on the 0-100 scale as xsd:{datatype}.",
        unit=PERCENT,
        scale=PERCENT_SCALE,
    )


def _describe(text: str, canonical: str | None, rule: str, spec: ValueSpec) -> str:
    reasons = {
        "thousands-separator": "the thousands separator was removed",
        "integral-decimal": "an integral decimal was written as a whole number",
    }
    return f"'{text}' was normalised to {canonical} as xsd:{spec.datatype}: {reasons.get(rule, rule)}."


# ---------------------------------------------------------------------------------- booleans and dates

_BOOLEAN_NOISE = " \t\"'`.!;"
_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00(?::00(?:\.0+)?)?$")
_YEAR_FIRST = re.compile(r"^(\d{4})([/.\-])(\d{1,2})\2(\d{1,2})$")
_YEAR_LAST = re.compile(r"^(\d{1,2})([/.\-])(\d{1,2})\2(\d{4})$")


def _normalize_boolean(text: str, spec: ValueSpec) -> ValueNormalization | None:
    token = text.strip(_BOOLEAN_NOISE).lower()
    if token in _TRUE | _FALSE:
        canonical = "true" if token in _TRUE else "false"
        return _record(
            NORMALIZED, text, spec.datatype, canonical, "boolean-token",
            f"'{text}' was read as the boolean {canonical}.",
        )
    return None


def _calendar_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _normalize_date(text: str, spec: ValueSpec) -> ValueNormalization | None:
    datatype = spec.datatype
    midnight = _MIDNIGHT.match(text)
    if midnight:
        canonical = _calendar_date(*(int(part) for part in midnight.group(1).split("-")))
        if canonical:
            return _record(
                NORMALIZED, text, datatype, canonical, "midnight-datetime-to-date",
                f"'{text}' is a date-time at midnight; the time of day was dropped: {canonical}.",
            )
    year_first = _YEAR_FIRST.match(text)
    if year_first:
        year, _, month, day = year_first.groups()
        canonical = _calendar_date(int(year), int(month), int(day))
        if canonical:
            return _record(
                NORMALIZED, text, datatype, canonical, "year-first-date",
                f"'{text}' is a year-month-day date and was written as ISO 8601: {canonical}.",
            )
        return None
    year_last = _YEAR_LAST.match(text)
    if year_last:
        first, _, second, year = year_last.groups()
        a, b = int(first), int(second)
        if a > 12 and b > 12:
            return None
        if a <= 12 and b <= 12 and a != b:
            return _record(
                AMBIGUOUS, text, datatype, None, "date-order",
                f"'{text}' is ambiguous: it could be day/month/year or month/day/year; it was not converted.",
            )
        # Exactly one reading is possible: the part above 12 is the day (or both parts are equal).
        day, month = (a, b) if a > 12 else (b, a)
        canonical = _calendar_date(int(year), month, day)
        if canonical:
            return _record(
                NORMALIZED, text, datatype, canonical, "day-month-year-date",
                f"'{text}' has only one valid day/month reading and was written as ISO 8601: {canonical}.",
            )
    return None


# ---------------------------------------------------------------------------------- entry points


def normalize_value(raw: str | None, spec: ValueSpec) -> ValueNormalization:
    """Normalise one raw value for the attribute described by ``spec``. Never raises, never guesses."""
    original = raw or ""
    text = original.strip()
    datatype = spec.datatype
    if not text:
        return _record(FAILED, original, datatype, None, "empty", "The value is empty.")
    valid, canonical, message = parse_literal(text, datatype)
    if valid:
        assert canonical is not None
        if canonical == text:
            return _record(EXACT, original, datatype, canonical, "as-written", f"Value is a valid {datatype}.")
        rule = "boolean-token" if datatype == "boolean" else "thousands-separator" if "," in text else "canonical-form"
        return _record(
            NORMALIZED, original, datatype, canonical, rule,
            f"'{text}' was rewritten to the canonical xsd:{datatype} form {canonical}.",
        )
    result: ValueNormalization | None = None
    if datatype in NUMERIC_DATATYPES:
        result = _normalize_numeric(text, spec)
    elif datatype == "boolean":
        result = _normalize_boolean(text, spec)
    elif datatype == "date":
        result = _normalize_date(text, spec)
    if result is not None and result.status != FAILED:
        return replace(result, raw_value=original)
    # Not convertible: the datatype message stays the strict one (reasons shown to reviewers are unchanged);
    # the rule records why the extended readings did not apply.
    rule = result.rule if result is not None else "datatype-mismatch"
    return _record(FAILED, original, datatype, None, rule, message)


def same_value(a: str, b: str, datatype: str) -> bool:
    """Value equality of two canonical lexical forms (numeric types compare by value: 97 equals 97.0)."""
    if a == b:
        return True
    if datatype in NUMERIC_DATATYPES:
        try:
            return Decimal(a) == Decimal(b)
        except InvalidOperation:
            return False
    return False
