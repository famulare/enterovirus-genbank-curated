"""Geography derived from one GenBank `/geo_loc_name` string.

`country` and `admin1` are transport — no projection row exists for them, because the value *is*
the source value. `locality` is the exception, and the reason this module holds a bound rule: it
carries a projection row under R-GEO-LOCALITY-2, so it is the smallest end-to-end proof that the
rule catalog, `RuleOutcome` and the provenance writer agree with the release.

## The deliberate break: three reasons a locality is blank, not one

2.4.1 labels **every** blank `locality` `duplicate_of_admin1_suppressed`. Measured, only **4,233 of
23,268** of those are actually suppressions. The other two groups had nothing to suppress:

| n | what the record deposited | correct basis |
|---|---|---|
| 4,233 | `Country: Region` — a locality would repeat `admin1` | `duplicate_of_admin1_suppressed` |
| 16,987 | `Country` only — no region at all | `no_admin1_deposited` |
| 2,048 | no `/geo_loc_name` whatsoever | `no_geography_deposited` |

So the shipped label asserts a determination that was never made on 19,035 records — the same defect
as giving a precision to a record with no date, and corrected the same way. The two new bases stay
distinct on purpose: a record naming only a country *did* deposit geography, so folding it into
"nothing deposited" would replace one overstatement with another.

The replacement guarantee ties each basis to the data, instead of leaving the column decorative:

* `locality` is blank if and only if the basis is one of the three blank reasons;
* `duplicate_of_admin1_suppressed` implies a **non-blank** `admin1` the locality would repeat;
* `no_admin1_deposited` implies a non-blank `country` and a blank `admin1`;
* `no_geography_deposited` implies both blank.

`validation/invariants.py` enforces all four against the build's own output, which is what stops the
basis column drifting back into free text. R-GEO-LOCALITY-1 is deprecated behind R-GEO-LOCALITY-2,
so the frozen rule view still regenerates byte-for-byte.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

GEO_QUALIFIER = "geo_loc_name"
LOCALITY_SOURCE_FIELD = "location_genbank"
BASIS_PARSED = "geo_parse"
BASIS_SUPPRESSED = "duplicate_of_admin1_suppressed"
# The rewrite's own two bases, for the blanks that are not suppressions.
BASIS_NO_ADMIN1 = "no_admin1_deposited"
BASIS_NO_GEOGRAPHY = "no_geography_deposited"


@dataclass(frozen=True)
class GeoParse:
    country: str
    admin1: str
    locality: str


def parse_geo_loc_name(value: str) -> GeoParse:
    """Split one GenBank `/geo_loc_name` into country, admin1 and sub-admin1 locality.

    The qualifier's grammar is `country[: region[, finer detail]]`. Two consequences are easy to
    get wrong and are load-bearing for parity:

    * `locality` holds the *whole* remainder after the colon, not just the part past the comma, so
      it always starts with `admin1`;
    * a remainder with no comma carries no sub-admin1 information, so R-GEO-LOCALITY-1 blanks
      `locality` whenever it would merely repeat `admin1` — 4,285 of 5,319 rows in the release. A
      non-blank `locality` therefore means genuine detail rather than a duplicated region name.
    """
    if not value:
        return GeoParse("", "", "")
    country, separator, remainder = value.partition(":")
    country = country.strip()
    remainder = remainder.strip()
    if not separator or not remainder:
        return GeoParse(country, "", "")
    admin1 = remainder.partition(",")[0].strip()
    locality = "" if remainder == admin1 else remainder
    return GeoParse(country, admin1, locality)


def unsuppressed_locality(value: str) -> str:
    """The locality before R-GEO-LOCALITY-1 blanks it: the whole remainder after the first colon.

    This is what the release records as `source_value`, not the raw qualifier — verified against all
    24,301 shipped provenance rows. Recording the raw string would lose the distinction between "no
    geography was deposited" and "geography was deposited with no sub-admin1 detail".
    """
    if not value:
        return ""
    _, separator, remainder = value.partition(":")
    return remainder.strip() if separator else ""


@rule_implementation(
    "derive.geo.locality",
    parameters=("no_admin1_basis", "no_geography_basis"),
    evidence_bases=(BASIS_PARSED, BASIS_SUPPRESSED, BASIS_NO_ADMIN1, BASIS_NO_GEOGRAPHY),
)
def locality(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    raw = view.qualifier(GEO_QUALIFIER)
    parsed = parse_geo_loc_name(raw)
    if parsed.locality:
        basis = BASIS_PARSED
    elif parsed.admin1:
        basis = BASIS_SUPPRESSED
    elif parsed.country:
        # A country with no region: nothing a locality could have duplicated, but geography was
        # deposited, so this is not "no geography" either.
        basis = parameters["no_admin1_basis"]
    else:
        basis = parameters["no_geography_basis"]
    return RuleOutcome(
        value=parsed.locality,
        evidence_basis=basis,
        source_field=LOCALITY_SOURCE_FIELD,
        source_value=unsuppressed_locality(raw),
    )
