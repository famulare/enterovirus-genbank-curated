"""Collection date and its precision, from the GenBank `/collection_date` qualifier.

Measured against the release before being written: for every record that deposited a date, the
canonical `collection_date` **is** the ISO normalization of the source qualifier and the canonical
precision **is** the shape of that qualifier — 19,732 carved records, with no curated input. The
release's rule text describes these as projections of curated fields (`collection_date_curated`,
`collection_year_curated`), and for these rows those curated fields evidently just held the
normalized source value.

## The deliberate break: `NA`, not `unknown`

4,569 records deposited **no** date at all. The release split them: 2,805 got precision `unknown`
and 1,764 got precision `year` with a year attributed to a source outside GenBank.

Curator decision, 2026-07-30: **a record with no date has no precision.** Those rows get `NA`, and
`collection_date` stays blank. This is more correct than what shipped, not merely more honest —
`unknown` asserts "the precision is unknown" about a date that does not exist, and it consumes the
one vocabulary value that should mean "a date exists but its precision is unclear".

**Invariant broken, and its replacement.** The release guaranteed
`collection_date_precision ∈ {day, month, year, range, unknown}` and said nothing relating the
precision to the value. That vocabulary is now `{day, month, year, range, NA}` — `unknown` is
retired and `NA` is new — under a stronger guarantee that ties the two columns together:
**`collection_date` is blank if and only if `collection_date_precision` is `NA`.** It is enforced in
the build by `validation/invariants.py`, not merely asserted here, and the per-column deltas against
the release are counted in `oracle/parity.py`.

## The dated 1,764, and the premise that was wrong about them

This docstring said until 2026-08-12 that the year on those records came from "an archival
reconstruction whose inputs are not in this repository", and that nothing in `raw/` could tell the
two groups apart. That was never measured. Measured, it is false: 1,690 of the 1,761 that fall in
the shared rows came from parsing a GPEI surveillance identifier in `/strain`, `/isolate`, the
definition line or the other `source` qualifiers, and 71 from an explicit four-digit year in a
strain designation — **every one of them from a field this repository already carries, and none
from the archival reconstruction.** `derive/date_identifiers.py` reads them, and reproduces 2.4.1's
year on 1,761 of 1,761. What remains of the split is the 2,803 the release called `unknown` and
this pipeline calls `NA`, which is the vocabulary break above and not a missing input.

An identifier-inferred year is consulted **only** when no date was deposited and no decision names
one, so it can never displace a value someone measured or a curator confirmed.

R-DATE-PRECISION-1 and R-DATE-1 are therefore superseded here by `-2` rules carrying real semver,
which keeps the frozen `rules.tsv.gz` view byte-identical while the catalog moves on.

## `collection_year_earliest` / `collection_year_latest`

The interval endpoints, blank unless precision is `range`, verified against all 121 shipped range
rows including the floor-of-mean midpoint. One catalog rule covers *two* canonical columns, which is
why `rule_implementation` takes a `fields` argument and a body may return a mapping: the release
records it the same way, a single `winning_rule_id` on both columns. Requiring the returned keys to
equal the declared set is what stops such a rule writing a column nobody declared.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from enterovirus_genbank_curated.derive.date_identifiers import (
    EXPLICIT_CONVENTION,
    explicit_designation_year,
    identifier_year,
)
from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.derive.partition import POLIOVIRUS, resolved_partition
from enterovirus_genbank_curated.registry.rules import rule_implementation

DATE_QUALIFIER = "collection_date"

PRECISION_DAY = "day"
PRECISION_MONTH = "month"
PRECISION_YEAR = "year"
PRECISION_RANGE = "range"
# The rewrite's own value, replacing the release's `unknown` for a record that deposited no date.
PRECISION_NOT_APPLICABLE = "NA"

BASIS_CURATED_DATE = "curated_date"
BASIS_CURATED_YEAR = "curated_year"
BASIS_MONTH_NORMALIZED = "source_date_normalized_to_month"
BASIS_RANGE_MIDPOINT = "curated_range_midpoint"
BASIS_NO_DATE = "no_date_deposited"
BASIS_PRECISION_PROJECTION = "canonical_projection"
BASIS_IDENTIFIER_YEAR = "surveillance_identifier_year"

IDENTIFIER_PARAMETERS = ("minimum_inferred_year", "maximum_inferred_year", "two_digit_year_pivot")
# `source_field` on an identifier-inferred row names the convention that read the year, so the
# 1,761 recoveries are attributable per convention from the shipped provenance alone.
IDENTIFIER_SOURCE_PREFIX = "surveillance_identifier:"

LEDGER_YEAR_FIELD = "collection_year_curated"
UNRESOLVED_UNPARSEABLE = "collection_date_not_parseable"

_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
_YEAR = re.compile(r"^\d{4}$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DD_MON_YYYY = re.compile(r"^(\d{2})-([A-Za-z]{3})-(\d{4})$")
_MON_YYYY = re.compile(r"^([A-Za-z]{3})-(\d{4})$")
_FIRST_YEAR = re.compile(r"(\d{4})")


def normalize_collection_date(value: str) -> tuple[str, str]:
    """`(iso_value, precision)` for one `/collection_date`, or `("", "")` when it cannot be read.

    GenBank permits several spellings of one precision — `06-Jul-1909` and `1909-07-06` are both
    day-precision — so the shape is normalized before the precision is named, not after.
    """
    raw = value.strip()
    if not raw:
        return "", ""
    if "/" in raw:
        first, _, second = raw.partition("/")
        start, end = _year_of(first), _year_of(second)
        if not (start and end):
            return "", ""
        return str((int(start) + int(end)) // 2), PRECISION_RANGE
    if _YEAR.match(raw):
        return raw, PRECISION_YEAR
    if _YEAR_MONTH.match(raw) or _ISO_DAY.match(raw):
        return raw, PRECISION_MONTH if _YEAR_MONTH.match(raw) else PRECISION_DAY
    day = _DD_MON_YYYY.match(raw)
    if day and day.group(2).lower() in _MONTHS:
        return f"{day.group(3)}-{_MONTHS[day.group(2).lower()]:02d}-{day.group(1)}", PRECISION_DAY
    month = _MON_YYYY.match(raw)
    if month and month.group(1).lower() in _MONTHS:
        return f"{month.group(2)}-{_MONTHS[month.group(1).lower()]:02d}", PRECISION_MONTH
    return "", ""


def _year_of(value: str) -> str:
    found = _FIRST_YEAR.search(value.strip())
    return found.group(1) if found else ""


@dataclass(frozen=True)
class _Resolved:
    """What a record's date is, and what established it."""

    value: str
    precision: str
    from_decision: bool = False
    # Set only when the year was read out of a surveillance identifier: which naming convention
    # matched, and the token it matched. Empty on every other row.
    convention: str = ""
    token: str = ""


def _deposited_date(view: RecordView) -> _Resolved:
    """The ledger and the `/collection_date` qualifier only; `NA` when neither carries a date.

    The ledger is consulted first and wins outright. Two of the five active
    `collection_year_curated` decisions correct a submitter error: `/collection_date=06-Jul-1909` on
    a 2013 isolate. A rule preferring the source qualifier would reinstate a date the curator has
    already rejected.
    """
    asserted = view.decisions.get(LEDGER_YEAR_FIELD)
    if asserted:
        return _Resolved(asserted, PRECISION_YEAR, from_decision=True)
    raw = view.qualifier(DATE_QUALIFIER)
    value, precision = normalize_collection_date(raw)
    if not precision:
        # A deposited date the parser cannot read is NOT an absent date. Calling it `NA` would
        # assert "this record has no date", the same false determination both deliberate breaks
        # corrected elsewhere. It declines instead, which also routes it to the curation queue.
        # No such value exists in the corpus today, and a test pins that zero, so a raw refresh
        # introducing `>2013` or `20130706` surfaces rather than being silently mislabelled.
        return _Resolved("", "") if raw.strip() else _Resolved("", PRECISION_NOT_APPLICABLE)
    return _Resolved(value, precision)


def _resolved_date(parameters: Mapping[str, Any], view: RecordView) -> _Resolved:
    """The deposited date, or failing that a year read out of a surveillance identifier.

    Last, deliberately. A deposited date and a curator's decision are both statements about this
    record; a year read out of a strain name is an inference from a naming convention, and it may
    only speak where neither of the other two does. It also may not speak over a *decline*: a
    deposited date the parser cannot read means something is wrong with that record, and answering
    it from its name would bury the problem rather than queue it.

    The conventions are poliovirus-surveillance-specific — GPEI EPID numbering — so the inference is
    gated on the curated partition, the upstream stage's own decision of 2026-05-29. A record whose
    partition is itself undecided is not inferred from either; it keeps the `NA` it has today rather
    than acquiring a new decline class, because no year was ever claimed for it.
    """
    deposited = _deposited_date(view)
    if deposited.precision != PRECISION_NOT_APPLICABLE:
        return deposited
    if resolved_partition(view) != POLIOVIRUS:
        return deposited
    window = {
        "minimum": int(parameters["minimum_inferred_year"]),
        "maximum": int(parameters["maximum_inferred_year"]),
    }
    year, _convention_or_suppressor, token = identifier_year(
        view, pivot=int(parameters["two_digit_year_pivot"]), **window
    )
    if year:
        return _Resolved(year, PRECISION_YEAR, convention=_convention_or_suppressor, token=token)
    # A suppressing convention stops the *cascade*, not this second pass: it fires because the text
    # is full of numeric tokens that carry no year, which says nothing about whether a strain
    # designation also spells one out. Fourteen `FR7155xx` records prove it — their `/isolate`
    # `30-ROU-2008` states 2008, and their `taxon:909391` is a six-digit token the suppressor
    # matches first. Returning early here left all fourteen undated.
    explicit = explicit_designation_year(view, **window)
    if explicit:
        return _Resolved(
            explicit,
            PRECISION_YEAR,
            convention=EXPLICIT_CONVENTION,
            token=explicit,
        )
    return deposited


def _identifier_source_field(convention: str) -> str:
    return f"{IDENTIFIER_SOURCE_PREFIX}{convention}"


@rule_implementation(
    "derive.dates.collection_date_precision",
    parameters=("precisions", "not_applicable", *IDENTIFIER_PARAMETERS),
    evidence_bases=(BASIS_PRECISION_PROJECTION, BASIS_NO_DATE, BASIS_IDENTIFIER_YEAR),
)
def collection_date_precision(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    resolved = _resolved_date(parameters, view)
    precision = resolved.precision
    if not precision:
        return RuleOutcome(
            value="",
            evidence_basis="",
            source_field=DATE_QUALIFIER,
            source_value=view.qualifier(DATE_QUALIFIER),
            unresolved_reason=UNRESOLVED_UNPARSEABLE,
        )
    if precision == PRECISION_NOT_APPLICABLE:
        return RuleOutcome(
            value=parameters["not_applicable"],
            evidence_basis=BASIS_NO_DATE,
            source_field=DATE_QUALIFIER,
            source_value="",
        )
    declared = parameters["precisions"]
    if precision not in declared:
        raise ValueError(f"{precision!r} is not one of the declared precisions {declared}")
    if resolved.convention:
        return RuleOutcome(
            value=precision,
            evidence_basis=BASIS_IDENTIFIER_YEAR,
            source_field=_identifier_source_field(resolved.convention),
            source_value=resolved.token,
        )
    return RuleOutcome(
        value=precision,
        evidence_basis=BASIS_PRECISION_PROJECTION,
        source_field="collection_date_precision",
        source_value=precision,
        manual_override=resolved.from_decision,
    )


@rule_implementation(
    "derive.dates.collection_date",
    parameters=("output_pattern", "precisions", *IDENTIFIER_PARAMETERS),
    evidence_bases=(
        BASIS_CURATED_DATE,
        BASIS_CURATED_YEAR,
        BASIS_MONTH_NORMALIZED,
        BASIS_RANGE_MIDPOINT,
        BASIS_NO_DATE,
        BASIS_IDENTIFIER_YEAR,
    ),
)
def collection_date(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Precision-driven, and every emitted value matches the declared output pattern.

    The `source_field` and `evidence_basis` per branch are the release's own, so a reader joining
    this to the shipped provenance sees the same trace: a day-precision value is recorded against
    `collection_date_curated`, a month-precision one against the raw `collection_date` it was
    normalized from, and a year or range midpoint against `collection_year_curated`. The identifier
    branch is this pipeline's own and says so — it names the convention that read the year.
    """
    resolved = _resolved_date(parameters, view)
    value, precision = resolved.value, resolved.precision
    if not precision:
        return RuleOutcome(
            value="",
            evidence_basis="",
            source_field=DATE_QUALIFIER,
            source_value=view.qualifier(DATE_QUALIFIER),
            unresolved_reason=UNRESOLVED_UNPARSEABLE,
        )
    if precision == PRECISION_NOT_APPLICABLE:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_NO_DATE,
            source_field="collection_date_precision",
            source_value=PRECISION_NOT_APPLICABLE,
        )
    if not re.match(parameters["output_pattern"], value):
        raise ValueError(f"{value!r} does not match the declared output pattern")
    if resolved.convention:
        return RuleOutcome(
            value=value,
            evidence_basis=BASIS_IDENTIFIER_YEAR,
            source_field=_identifier_source_field(resolved.convention),
            source_value=resolved.token,
        )
    basis, source_field = {
        PRECISION_DAY: (BASIS_CURATED_DATE, "collection_date_curated"),
        PRECISION_MONTH: (BASIS_MONTH_NORMALIZED, DATE_QUALIFIER),
        PRECISION_YEAR: (BASIS_CURATED_YEAR, "collection_year_curated"),
        PRECISION_RANGE: (BASIS_RANGE_MIDPOINT, "collection_year_curated"),
    }[precision]
    return RuleOutcome(
        value=value,
        evidence_basis=basis,
        source_field=source_field,
        # The month branch records the raw qualifier it normalized; the others record the value.
        source_value=view.qualifier(DATE_QUALIFIER) if precision == PRECISION_MONTH else value,
        manual_override=resolved.from_decision,
    )


EARLIEST_FIELD = "collection_year_earliest"
LATEST_FIELD = "collection_year_latest"
BASIS_NOT_A_RANGE = "not_a_range"


def interval_endpoint_years(value: str) -> tuple[str, str]:
    """The two endpoint years of a GenBank date interval, or `("", "")` if it is not one."""
    if "/" not in value:
        return "", ""
    first, _, second = value.partition("/")
    start, end = _year_of(first), _year_of(second)
    return (start, end) if start and end else ("", "")


@rule_implementation(
    "derive.dates.collection_year_bounds",
    parameters=("populated_when_precision_is",),
    evidence_bases=(BASIS_PRECISION_PROJECTION, BASIS_NOT_A_RANGE, BASIS_NO_DATE),
    fields=(EARLIEST_FIELD, LATEST_FIELD),
)
def collection_year_bounds(
    parameters: Mapping[str, Any], view: RecordView
) -> dict[str, RuleOutcome]:
    """Both interval endpoints, populated only for a `range` and blank on every other row.

    The one rule that projects two canonical columns, which is why `rule_implementation` grew a
    `fields` argument. The release records it the same way — a single `winning_rule_id` on both.

    On a non-range row the value is blank but `source_value` still carries the record's year, the
    release's own convention: the year *was* known, it simply is not a bound. Verified against all
    121 shipped range rows including the floor-of-mean midpoint `collection_date` reports.

    Reads the *deposited* date, not the identifier-inferred one, and that is the reason rather than
    an omission: an interval is a thing a depositor wrote in `/collection_date`, and no surveillance
    naming convention can produce one. So this rule needs no plausibility window and declares none,
    and an identifier-inferred row reaches the same non-range branch it reaches today.
    """
    raw = view.qualifier(DATE_QUALIFIER)
    precision = _deposited_date(view).precision
    ranged = parameters["populated_when_precision_is"]

    if precision == ranged:
        earliest, latest = interval_endpoint_years(raw)
        return {
            field: RuleOutcome(
                value=value,
                evidence_basis=BASIS_PRECISION_PROJECTION,
                source_field=field,
                source_value=value,
            )
            for field, value in ((EARLIEST_FIELD, earliest), (LATEST_FIELD, latest))
        }

    if not precision:
        return {
            field: RuleOutcome(
                value="",
                evidence_basis="",
                source_field=field,
                source_value="",
                unresolved_reason=UNRESOLVED_UNPARSEABLE,
            )
            for field in (EARLIEST_FIELD, LATEST_FIELD)
        }

    # Not a range: no bounds exist, but the year the record does have is recorded as what was read.
    known_year = "" if precision == PRECISION_NOT_APPLICABLE else _year_of(raw) or _year_of(
        view.decisions.get(LEDGER_YEAR_FIELD, "")
    )
    return {
        field: RuleOutcome(
            value="",
            evidence_basis=BASIS_NOT_A_RANGE,
            source_field=field,
            source_value=known_year,
        )
        for field in (EARLIEST_FIELD, LATEST_FIELD)
    }
