"""Collection date and its precision, from the GenBank `/collection_date` qualifier.

Measured against the release before being written: for every record that deposited a date, the
canonical `collection_date` **is** the ISO normalization of the source qualifier and the canonical
precision **is** the shape of that qualifier — 19,732 carved records, with no curated input. The
release's rule text describes these as projections of curated fields (`collection_date_curated`,
`collection_year_curated`), and for these rows those curated fields evidently just held the
normalized source value.

## The deliberate break: `NA`, not `unknown` or a year

4,569 records deposited **no** date at all. The release splits them: 2,805 get precision `unknown`
and 1,764 get precision `year` with a year supplied from outside GenBank — an archival
reconstruction whose inputs are not in this repository. Nothing in `raw/` can tell those two groups
apart, so reproducing the split is impossible and guessing it would be a fabrication on 4,569 rows.

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

The 1,764 records whose year came from identifier parsing are recoverable later: the frozen
archival-dates extract carried under the registry's legacy tree labels 21 identifier rule families,
and is a validation oracle for those rules rather than a build input. Every year recovered moves one
row from `NA` to `year`, never the reverse.

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
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
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


def _resolved_date(view: RecordView) -> tuple[str, str, bool]:
    """`(value, precision, from_decision)`; precision is `NA` when no date was deposited.

    The ledger is consulted first and wins outright. Two of the five active
    `collection_year_curated` decisions correct a submitter error: `/collection_date=06-Jul-1909` on
    a 2013 isolate. A rule preferring the source qualifier would reinstate a date the curator has
    already rejected.
    """
    asserted = view.decisions.get(LEDGER_YEAR_FIELD)
    if asserted:
        return asserted, PRECISION_YEAR, True
    raw = view.qualifier(DATE_QUALIFIER)
    value, precision = normalize_collection_date(raw)
    if not precision:
        # A deposited date the parser cannot read is NOT an absent date. Calling it `NA` would
        # assert "this record has no date", the same false determination both deliberate breaks
        # corrected elsewhere. It declines instead, which also routes it to the curation queue.
        # No such value exists in the corpus today, and a test pins that zero, so a raw refresh
        # introducing `>2013` or `20130706` surfaces rather than being silently mislabelled.
        return ("", "", False) if raw.strip() else ("", PRECISION_NOT_APPLICABLE, False)
    return value, precision, False


@rule_implementation(
    "derive.dates.collection_date_precision",
    parameters=("precisions", "not_applicable"),
    evidence_bases=(BASIS_PRECISION_PROJECTION, BASIS_NO_DATE),
)
def collection_date_precision(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    _, precision, from_decision = _resolved_date(view)
    if not precision:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_NO_DATE,
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
    return RuleOutcome(
        value=precision,
        evidence_basis=BASIS_PRECISION_PROJECTION,
        source_field="collection_date_precision",
        source_value=precision,
        manual_override=from_decision,
    )


@rule_implementation(
    "derive.dates.collection_date",
    parameters=("output_pattern", "precisions"),
    evidence_bases=(
        BASIS_CURATED_DATE,
        BASIS_CURATED_YEAR,
        BASIS_MONTH_NORMALIZED,
        BASIS_RANGE_MIDPOINT,
        BASIS_NO_DATE,
    ),
)
def collection_date(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Precision-driven, and every emitted value matches the declared output pattern.

    The `source_field` and `evidence_basis` per branch are the release's own, so a reader joining
    this to the shipped provenance sees the same trace: a day-precision value is recorded against
    `collection_date_curated`, a month-precision one against the raw `collection_date` it was
    normalized from, and a year or range midpoint against `collection_year_curated`.
    """
    value, precision, from_decision = _resolved_date(view)
    if not precision:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_NO_DATE,
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
    basis, source_field = {
        PRECISION_DAY: (BASIS_CURATED_DATE, "collection_date_curated"),
        PRECISION_MONTH: (BASIS_MONTH_NORMALIZED, DATE_QUALIFIER),
        PRECISION_YEAR: (BASIS_CURATED_YEAR, "collection_year_curated"),
        PRECISION_RANGE: (BASIS_RANGE_MIDPOINT, "collection_year_curated"),
    }[precision]
    if not re.match(parameters["output_pattern"], value):
        raise ValueError(f"{value!r} does not match the declared output pattern")
    return RuleOutcome(
        value=value,
        evidence_basis=basis,
        source_field=source_field,
        # The month branch records the raw qualifier it normalized; the others record the value.
        source_value=view.qualifier(DATE_QUALIFIER) if precision == PRECISION_MONTH else value,
        manual_override=from_decision,
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
    """
    raw = view.qualifier(DATE_QUALIFIER)
    _, precision, _ = _resolved_date(view)
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
                evidence_basis=BASIS_NO_DATE,
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
