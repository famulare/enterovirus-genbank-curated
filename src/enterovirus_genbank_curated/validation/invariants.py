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

DATE_FIELD = "collection_date"
PRECISION_FIELD = "collection_date_precision"


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
