"""Cross-column invariants, checked against the build's own output before it is written.

These are the guarantees the release makes about *relationships between* canonical columns, which no
single rule can enforce because each rule sees one field. A rule can be individually correct and the
table still incoherent.

Every invariant here is checked against the build, not against the release — so it holds for a fresh
clone with no `final/` present, and so it cannot be satisfied by copying.
"""

from __future__ import annotations

from collections.abc import Iterable

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.dates import PRECISION_NOT_APPLICABLE
from enterovirus_genbank_curated.derive.geo import (
    BASIS_NO_ADMIN1,
    BASIS_NO_GEOGRAPHY,
    BASIS_SUPPRESSED,
)

DATE_FIELD = "collection_date"
PRECISION_FIELD = "collection_date_precision"
LOCALITY_FIELD = "locality"


def assert_locality_basis_invariant(
    rows: Iterable[dict[str, str]], transport: Iterable[dict[str, str]]
) -> dict[str, int]:
    """Each blank-`locality` basis must be true of the record's own geography.

    2.4.1 labelled every blank `locality` `duplicate_of_admin1_suppressed`, and only 4,233 of
    23,268 were suppressions — nothing constrained the label, so it drifted into meaning "blank".
    These four checks are what make the basis column load-bearing rather than decorative:

    * blank `locality` iff the basis is one of the three blank reasons;
    * `duplicate_of_admin1_suppressed` requires a non-blank `admin1` for the locality to have
      repeated;
    * `no_admin1_deposited` requires a non-blank `country` and a blank `admin1`;
    * `no_geography_deposited` requires both blank.

    `country` and `admin1` are transport columns rather than projections, so they arrive
    separately — which is why this cannot live inside the rule: no rule sees two columns at once.
    """
    geography = {row["version"]: row for row in transport}
    blank_bases = {BASIS_SUPPRESSED, BASIS_NO_ADMIN1, BASIS_NO_GEOGRAPHY}
    breaches: list[str] = []
    counts: dict[str, int] = {}
    for row in rows:
        if row["canonical_field"] != LOCALITY_FIELD:
            continue
        basis, value = row["evidence_basis"], row["final_value"]
        counts[basis] = counts.get(basis, 0) + 1
        record = geography.get(row["version"])
        if record is None:
            continue
        country, admin1 = record["country"], record["admin1"]
        if bool(value) == (basis in blank_bases):
            breaches.append(f"{row['version']}: value {value!r} with basis {basis}")
        elif basis == BASIS_SUPPRESSED and not admin1:
            breaches.append(f"{row['version']}: {basis} but admin1 is blank")
        elif (basis == BASIS_NO_ADMIN1 and (admin1 or not country)) or (
            basis == BASIS_NO_GEOGRAPHY and (country or admin1)
        ):
            breaches.append(f"{row['version']}: {basis} with country={country!r} admin1={admin1!r}")
    if breaches:
        shown = "; ".join(breaches[:10])
        raise ContractError(
            f"{len(breaches)} records break the locality basis invariant — {shown}"
        )
    return counts


def assert_date_precision_invariant(rows: Iterable[dict[str, str]]) -> int:
    """`collection_date` is blank if and only if `collection_date_precision` is `NA`.

    This replaces a weaker release guarantee. 2.4.1 promised only that the precision came from a
    five-value vocabulary including `unknown`, and said nothing relating the two columns — which is
    how 1,764 records ended up with precision `year` and a date, alongside 2,805 with precision
    `unknown` and no date, with no way to tell from GenBank which was which.

    The replacement is checkable in both directions, and both directions matter. A blank date with a
    real precision claims a determination about a date that is not there; a populated date with `NA`
    claims no determination about a date that is. Returns the number of `NA` rows so a caller can
    report the population rather than only the pass.
    """
    by_record: dict[str, dict[str, str]] = {}
    for row in rows:
        field = row["canonical_field"]
        if field in (DATE_FIELD, PRECISION_FIELD):
            by_record.setdefault(row["version"], {})[field] = row["final_value"]

    breaches: list[str] = []
    not_applicable = 0
    for version, values in sorted(by_record.items()):
        if DATE_FIELD not in values or PRECISION_FIELD not in values:
            continue
        date, precision = values[DATE_FIELD], values[PRECISION_FIELD]
        if precision == PRECISION_NOT_APPLICABLE:
            not_applicable += 1
            if date:
                breaches.append(f"{version}: precision {precision} with date {date!r}")
        elif not date:
            breaches.append(f"{version}: blank date with precision {precision!r}")
    if breaches:
        shown = "; ".join(breaches[:10])
        raise ContractError(
            f"{len(breaches)} records break the date/precision invariant "
            f"(blank date iff precision {PRECISION_NOT_APPLICABLE}) — {shown}"
        )
    return not_applicable
