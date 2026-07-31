"""Epidemiological context: what kind of specimen, from what origin, under what surveillance.

These are the columns the release's value is worth most and its provenance least: `sample_origin`,
`surveillance_stream` and `specimen_type` all shipped as `canonical_projection` of a curated-master
field, so 24,301 values carry no record of *how* they were decided. Recovering that is the point of
this module.

## What is here: `specimen_type`

A keyword rule over `/isolation_source`, with the patterns declared in the catalog rather than
buried here. Measured over the 24,285 records the carve produces, it resolves 11,608 and declines
12,677 rather than guessing, agreeing with the release on all but one of the resolved rows.

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

## `sample_origin`, and the release inconsistency behind it

The release gives **different values to records with byte-identical inputs**: `/host=Homo sapiens`
alone ships 3,177 `human`, 55 `unknown` and 3 `vaccine`; adding `/isolation_source=human stool`
ships 46 `human` and 64 `unknown`; `sewage` ships 383 and 36. So `sample_origin` is not a function
of its declared inputs, and the measured "ceiling" was mostly the release contradicting itself — a
rule scoring at that ceiling would be reproducing the contradiction by accident.

Curator decision, 2026-07-30: **a human host means a human-origin sample.** R-ORIGIN-2 reads `/host`
first and falls back to human-specimen keywords in `/isolation_source`, so the 228 records where the
release says otherwise are a declared correction rather than a failure to reproduce. Two are worth
naming: three the release calls `vaccine` on a `/host=Homo sapiens` deposit — the vaccine-derived
fact belongs in `poliovirus_classification`, which already records it — and one `/host=nonhuman
primate` the release calls `human`, which is simply wrong.

The rule is **partition-scoped**, which is load-bearing rather than tidy. `sample_origin` was
curated for poliovirus only, so a non-poliovirus record projects `unknown` under its own basis, and
a record whose membership is *undecided* declines rather than being scoped either way. That scoping
removes 23 of the 34 defects an unscoped draft had: the `/isolation_source=opv` records are
`Enterovirus C`, whose membership no organism name can settle, so no epi rule should have been asked
about them at all.

Note what `unknown` is *not* doing here. It carries both "never curated outside poliovirus" and
"curated but undetermined", and unlike the `locality` basis that is not a conflation to fix in the
value: both really are "not determined". The difference is *why*, and why belongs in
`evidence_basis`, which is where it now lives.

## What is not here, and the measurement that says why

`surveillance_stream` remains pending. Its ceiling was measured over progressively richer feature
sets, and the honest reading is narrower than the headline:

| feature set | groups | `surveillance_stream` ceiling |
|---|---|---|
| host + isolation_source + environmental_sample | 160 | 90.3% |
| + lab_host + collected_by | 176 | 92.3% |
| + note | 442 | 93.5% |
| + definition | **9,951** | 99.9% |

The last row is worthless and nearly went in as a success. 9,951 groups over 10,084 poliovirus
records means `definition` is a near-unique key: the "ceiling" is measuring how well a record can
predict itself, not how well a rule could generalize. Any rule built on it would be memorizing the
oracle, which is precisely the failure `docs/pipeline.md` calls out. On the feature sets that do
generalize, roughly 650 records are irreducibly ambiguous and belong in a curation queue.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.derive.partition import POLIOVIRUS, resolved_partition
from enterovirus_genbank_curated.registry.rules import rule_implementation

ISOLATION_SOURCE_QUALIFIER = "isolation_source"
SPECIMEN_SOURCE_FIELD = "specimen_type"

BASIS_ISOLATION_SOURCE = "isolation_source_keyword"
UNRESOLVED_NO_KEYWORD = "no_specimen_keyword_in_isolation_source"
UNRESOLVED_AMBIGUOUS = "multiple_specimen_keywords"
# Distinct from "no keyword matched": a record that deposited nothing cannot be resolved by any
# pattern change, so it must not be advised as a rule-parameter fix. See `curate/queue.py`.
UNRESOLVED_NO_SOURCE = "no_isolation_source_deposited"
LEDGER_SPECIMEN_FIELD = "specimen_type"


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
    # The ledger wins outright, as for every other rule that reads it. Seven active `specimen_type`
    # assertions exist and all seven deposit no `/isolation_source`, so the first version of this
    # rule declined all of them and the queue then asked the curator for a decision the ledger
    # already contained. That is the D2 failure inside the mechanism built to prevent it.
    asserted = view.decisions.get(LEDGER_SPECIMEN_FIELD)
    if asserted:
        return RuleOutcome(
            value=asserted,
            evidence_basis=BASIS_ISOLATION_SOURCE,
            source_field=SPECIMEN_SOURCE_FIELD,
            source_value=asserted,
            manual_override=True,
        )

    source = view.qualifier(ISOLATION_SOURCE_QUALIFIER)
    matched = matching_specimen_types(parameters["patterns"], source)

    if not source.strip():
        reason = UNRESOLVED_NO_SOURCE
    elif not matched:
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


HOST_QUALIFIER = "host"
ORIGIN_SOURCE_FIELD = "origin_class"

BASIS_HOST_SPECIES = "host_species"
BASIS_HUMAN_SPECIMEN = "human_specimen"
BASIS_OUTSIDE_POLIOVIRUS = "not_determined_outside_poliovirus"
UNRESOLVED_NO_ORIGIN_EVIDENCE = "no_host_or_specimen_evidence"
UNRESOLVED_FOLLOWS_PARTITION = "follows_unresolved_virus_group"
LEDGER_ORIGIN_FIELD = "origin_class"


@rule_implementation(
    "derive.epi.sample_origin",
    parameters=("human_host_pattern", "human_specimen_pattern", "origins", "outside_scope_value"),
    evidence_bases=(BASIS_HOST_SPECIES, BASIS_HUMAN_SPECIMEN, BASIS_OUTSIDE_POLIOVIRUS),
)
def sample_origin(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Who was sampled, scoped by the partition that decides whether the question was asked.

    `/host` is authoritative when present: a human host means a human-origin sample, and a named
    non-human host means it is not. Only when no host was deposited does the specimen text stand in.
    """
    # The ledger wins outright. 247 active `origin_class` decisions exist, and a text rule that
    # overrode them would make the curation ornamental — the D2 failure. Checked before the
    # partition scope: a curator asserting an origin has implicitly answered the scoping question.
    asserted = view.decisions.get(LEDGER_ORIGIN_FIELD)
    if asserted:
        return RuleOutcome(
            value=asserted,
            evidence_basis=BASIS_HOST_SPECIES,
            source_field=ORIGIN_SOURCE_FIELD,
            source_value=asserted,
            manual_override=True,
        )

    partition = resolved_partition(view)
    if not partition:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_HOST_SPECIES,
            source_field=ORIGIN_SOURCE_FIELD,
            source_value=view.record.get("organism_name", ""),
            unresolved_reason=UNRESOLVED_FOLLOWS_PARTITION,
        )
    if partition != POLIOVIRUS:
        return RuleOutcome(
            value=parameters["outside_scope_value"],
            evidence_basis=BASIS_OUTSIDE_POLIOVIRUS,
            source_field=ORIGIN_SOURCE_FIELD,
            source_value=partition,
        )

    origins = parameters["origins"]
    host = view.qualifier(HOST_QUALIFIER).strip().lower()
    if host:
        human = re.search(parameters["human_host_pattern"], host) is not None
        return RuleOutcome(
            value=origins["human"] if human else origins["non_human"],
            evidence_basis=BASIS_HOST_SPECIES,
            source_field=ORIGIN_SOURCE_FIELD,
            source_value=host,
        )

    specimen = view.qualifier(ISOLATION_SOURCE_QUALIFIER).strip().lower()
    if specimen and re.search(parameters["human_specimen_pattern"], specimen):
        return RuleOutcome(
            value=origins["human"],
            evidence_basis=BASIS_HUMAN_SPECIMEN,
            source_field=ORIGIN_SOURCE_FIELD,
            source_value=specimen,
        )
    return RuleOutcome(
        value="",
        evidence_basis=BASIS_HOST_SPECIES,
        source_field=ORIGIN_SOURCE_FIELD,
        source_value=specimen,
        unresolved_reason=UNRESOLVED_NO_ORIGIN_EVIDENCE,
    )
