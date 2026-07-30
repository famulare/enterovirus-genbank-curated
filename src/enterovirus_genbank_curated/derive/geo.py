"""Geography derived from one GenBank `/geo_loc_name` string.

`country` and `admin1` are transport — no projection row exists for them, because the value *is*
the source value. `locality` is the exception, and the reason this module holds a bound rule: it
carries a projection row under R-GEO-LOCALITY-1, so it is the smallest end-to-end proof that the
rule catalog, `RuleOutcome` and the provenance writer agree with the release.

## One infelicity in the shipped basis vocabulary, reproduced deliberately

`duplicate_of_admin1_suppressed` covers every blank `locality` — including **2,048 records with no
`/geo_loc_name` at all**, where there was never a locality to suppress. The label overstates what it
distinguishes for those rows. It is reproduced exactly rather than split into a third basis, because
this increment exists to prove the machinery against the release, and a more honest vocabulary here
would break the only clean 6-column gate available. `tests/test_projection_provenance.py` pins the
2,048 so the infelicity is visible rather than merely inherited; splitting it belongs with the
release that can afford to move a published basis value.
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
    parameters=(),
    evidence_bases=(BASIS_PARSED, BASIS_SUPPRESSED),
)
def locality(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    raw = view.qualifier(GEO_QUALIFIER)
    parsed = parse_geo_loc_name(raw)
    return RuleOutcome(
        value=parsed.locality,
        evidence_basis=BASIS_PARSED if parsed.locality else BASIS_SUPPRESSED,
        source_field=LOCALITY_SOURCE_FIELD,
        source_value=unsuppressed_locality(raw),
    )
