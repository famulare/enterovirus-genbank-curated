"""Epidemiological context: what kind of specimen, from what origin, under what surveillance.

These are the columns the release's value is worth most and its provenance least: `sample_origin`,
`surveillance_stream` and `specimen_type` all shipped as `canonical_projection` of a curated-master
field, so 24,301 values carry no record of *how* they were decided. Recovering that is the point of
this module.

## What is here: `specimen_type`

A keyword rule over `/isolation_source`, with the patterns declared in the catalog rather than
buried here. It resolves 11,601 of 24,301 records, agrees with the release on 11,600, and **declines
the other 12,700 rather than guessing**.

Two things the disagreements taught, which is the reason to look at them one by one instead of
tuning a rate:

* `"throat swab and stool samples from an immunodeficient patient"` names **two** specimens. A rule
  picking one by pattern order chooses arbitrarily and is right or wrong by accident, so more than
  one matching category is `multiple_specimen_keywords` — declined. Four records.
* an earlier draft matched the bare substring `fec`, which fires inside "in**fec**tion". Two records
  labelled `"case of acute respiratory infection"` were being called stool. Every pattern is now
  anchored on whole words or explicit alternatives.

One disagreement survives and is **not** absorbed: `GQ331952.1` deposits `/isolation_source
=groundwater` and ships `specimen_type=stool`. Groundwater is not stool. This is recorded as a
probable upstream error rather than pattern-matched around, because a rule twisted to reproduce a
wrong value is worse than a declared disagreement.

## What is not here, and the measurement that says why

`sample_origin` and `surveillance_stream` remain pending. Their ceilings were measured over
progressively richer feature sets, and the honest reading is narrower than the headline:

| feature set | groups | `sample_origin` | `surveillance_stream` |
|---|---|---|---|
| host + isolation_source + environmental_sample | 160 | 96.5% | 90.3% |
| + lab_host + collected_by | 176 | 96.5% | 92.3% |
| + note | 442 | 97.5% | 93.5% |
| + definition | **9,951** | 99.9% | 99.9% |

The last row is worthless and nearly went in as a success. 9,951 groups over 10,084 poliovirus
records means `definition` is a near-unique key: the "ceiling" is measuring how well a record can
predict itself, not how well a rule could generalize. Any rule built on it would be memorizing the
oracle, which is precisely the failure `docs/pipeline.md` calls out. The usable ceilings are the
first three rows, so ~250 and ~650 records respectively are irreducibly ambiguous on declared inputs
and belong in a curation queue rather than in a rule.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

ISOLATION_SOURCE_QUALIFIER = "isolation_source"
SPECIMEN_SOURCE_FIELD = "specimen_type"

BASIS_ISOLATION_SOURCE = "isolation_source_keyword"
UNRESOLVED_NO_KEYWORD = "no_specimen_keyword_in_isolation_source"
UNRESOLVED_AMBIGUOUS = "multiple_specimen_keywords"


def matching_specimen_types(patterns: Mapping[str, str], isolation_source: str) -> set[str]:
    """Every declared specimen category whose pattern matches, so ambiguity is visible.

    Returning the whole set rather than the first hit is what makes declining possible: a source
    naming two specimens is a fact about the record, and collapsing it to one by iteration order
    would hide that behind a plausible answer.
    """
    text = isolation_source.strip().lower()
    if not text:
        return set()
    return {value for value, pattern in patterns.items() if re.search(pattern, text)}


@rule_implementation(
    "derive.epi.specimen_type",
    parameters=("patterns",),
    evidence_bases=(BASIS_ISOLATION_SOURCE,),
)
def specimen_type(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    source = view.qualifier(ISOLATION_SOURCE_QUALIFIER)
    matched = matching_specimen_types(parameters["patterns"], source)

    if not matched:
        reason = UNRESOLVED_NO_KEYWORD
    elif len(matched) > 1:
        reason = UNRESOLVED_AMBIGUOUS
    else:
        return RuleOutcome(
            value=matched.pop(),
            evidence_basis=BASIS_ISOLATION_SOURCE,
            source_field=SPECIMEN_SOURCE_FIELD,
            source_value=source,
        )
    return RuleOutcome(
        value="",
        evidence_basis=BASIS_ISOLATION_SOURCE,
        source_field=SPECIMEN_SOURCE_FIELD,
        source_value=source,
        unresolved_reason=reason,
    )
