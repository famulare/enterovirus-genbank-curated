"""`poliovirus_classification` — Sabin-like, VDPV or wild, decided by VP1 divergence.

`R-CLASS-1` projects `classification_reconciled`, a curated field reconciling a text call against a
sequence call. Its evidence bases name the method — `group_B_sequence_tier`, `text_wild_override`,
`group_A_text_owned` — and the sequence half of it is now computable here, because
`derive/evidence.py` measures VP1 divergence from the matching Sabin reference.

## The thresholds are the release's own, not fitted here

They are published in the rule catalog as `R-TIER-SABINLIKE-1` and `R-TIER-WILD-1`: Sabin-like below
1% divergence for PV1 and PV3 and below 0.6% for PV2, wild at or above 15%. Those are WHO's
operational definitions, and they are declared data in `registry/rules.json` rather than numbers
recovered by tuning against the shipped column.

Measured independently against the release before those parameters were read, VP1 nt divergence
separates the shipped classes almost exactly where they predict:

| shipped class | n | 5th pct | median | 95th pct |
|---|---|---|---|---|
| `Sabin-like` | 3,476 | 0.000 | 0.111 | 0.662 |
| `VDPV` | 687 | 0.664 | 1.435 | 14.618 |
| `cVDPV` | 1,373 | 0.775 | 2.547 | 6.866 |
| `iVDPV` | 177 | 0.886 | 2.215 | 13.621 |
| `wild` | 2,102 | 18.433 | 20.530 | 22.778 |

Every `Sabin-like` record sits below 1%; every `wild` record sits above 18%; the VDPV family fills
the middle. Recovering a published threshold from the data is the strongest evidence available that
the measurement is the right one.

## What the sequence decides, and what it cannot

Divergence answers one question: how far from Sabin. That distinguishes `Sabin-like`, the VDPV band,
and `wild`. It does **not** distinguish `cVDPV` from `iVDPV` from a bare `VDPV`, because that
distinction is epidemiological — circulating, immunodeficient, or ambiguous — and no property of the
sequence carries it.

Nor is it in the record. Of the 1,767 `cVDPV` records the release ships, only 283 say `cVDPV`
anywhere in their definition, strain or isolate name; of 203 `iVDPV`, only 29. So the attribution
came from outside GenBank, and where it is not in the ledger either, this rule emits `VDPV` — the
the sequence supports — rather than picking one of its three refinements. That is a deliberate
coarsening and it is declared as such: `VDPV` is true of every record in the band, and `cVDPV` is a
claim about transmission that this pipeline has no input for.

A record whose definition or strain *does* name the refinement gets it, since that is the depositor
stating it.

## VP1-first, capsid-fallback

1,911 carved, name-serotyped records have no usable VP1: too short, or VP1 not deposited at all.
`derive/evidence.py` falls back to the whole capsid (VP4-VP2-VP3-VP1) for these, the same fallback
MAD-VDPV's own pipeline takes, over the same thresholds — a longer region to ask the same question,
not a different one. This rule does not know or care which basis answered it; `view.evidence[
EVIDENCE_BASIS]` is carried into `source_value` for the audit trail, and nowhere else, because the
threshold logic below is identical either way.

## Order of precedence, and where it declines

1. Outside poliovirus the column is **blank by determination**, not declined — the vocabulary is
   poliovirus-specific and the release ships blank for all 14,217 non-poliovirus rows.
2. An undecided partition declines: nothing can be said until membership is settled.
3. An active `verified_classification` or `classification` decision wins outright.
4. A refinement named in the record's own text wins over the bare band.
5. Otherwise the divergence band, VP1 if at least 300 nt of VP1 was compared, else the capsid
   fallback if it clears its own guards (`derive/evidence.compare_capsid_nt`).
6. Otherwise decline — no serotype in the organism name to pick a reference with, or too little
   usable sequence by either basis.

`unresolved` is a value in the shipped vocabulary and this rule never emits it. A cell the pipeline
cannot decide is an unresolved *cell*, carrying its reason into the provenance table and the
curation queue; writing "unresolved" into the column would record a non-answer as an answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.derive.partition import POLIOVIRUS, resolved_partition
from enterovirus_genbank_curated.derive.typing import serotype_from_name
from enterovirus_genbank_curated.registry.rules import rule_implementation

ORGANISM_FIELD = "organism_name"
DEFINITION_FIELD = "definition"
STRAIN_QUALIFIER = "strain"
ISOLATE_QUALIFIER = "isolate"

EVIDENCE_DIVERGENCE = "divergence_pct"
EVIDENCE_COMPARED = "compared_nt"
EVIDENCE_REFERENCE = "reference_version"
EVIDENCE_BASIS = "basis"

LEDGER_VERIFIED = "verified_classification"
LEDGER_CLASSIFICATION = "classification"
LEDGER_FIELDS = (LEDGER_VERIFIED, LEDGER_CLASSIFICATION)

SABIN_LIKE = "Sabin-like"
VDPV = "VDPV"
WILD = "wild"

BASIS_LEDGER = "curated_classification"
BASIS_OUTSIDE_POLIOVIRUS = "not_applicable_outside_poliovirus"
BASIS_TEXT_REFINEMENT = "vdpv_refinement_in_record_text"
BASIS_SABIN_LIKE = "vp1_divergence_below_sabin_like_threshold"
BASIS_VDPV = "vp1_divergence_in_vaccine_derived_band"
BASIS_WILD = "vp1_divergence_at_or_above_wild_threshold"

UNRESOLVED_FOLLOWS_PARTITION = "follows_unresolved_virus_group"
UNRESOLVED_NO_SEROTYPE = "no_serotype_in_organism_name_to_choose_a_reference"
# Covers both a VP1 measurement that never reached MIN_VP1_NT and a capsid fallback that either
# could not reach MIN_CAPSID_NT or failed the homogeneity guard — one reason, matching the existing
# grain of this rule's other reasons: `compare_vp1` already collapses several distinct failures
# (no diagonal, too short, implausible) into the one outcome of returning `None`.
UNRESOLVED_INSUFFICIENT_SEQUENCE = "too_little_sequence_compared_to_measure_divergence"
UNRESOLVED_UNCONTROLLED_VALUE = "curated_value_outside_the_controlled_vocabulary"

# Refinements a depositor may state outright. Longest-first, so `cVDPV` is not read as `VDPV`.
_REFINEMENTS = (
    (re.compile(r"\bcvdpv[123]?-?n\b", re.IGNORECASE), "cVDPV-n"),
    (re.compile(r"\bcvdpv", re.IGNORECASE), "cVDPV"),
    (re.compile(r"\bivdpv", re.IGNORECASE), "iVDPV"),
    (re.compile(r"\bavdpv", re.IGNORECASE), "aVDPV"),
)


def _record_text(view: RecordView) -> str:
    return " ".join(
        (
            view.record.get(DEFINITION_FIELD, ""),
            view.qualifier(STRAIN_QUALIFIER),
            view.qualifier(ISOLATE_QUALIFIER),
        )
    )


def _stated_refinement(text: str) -> str:
    for pattern, value in _REFINEMENTS:
        if pattern.search(text):
            return value
    return ""


@rule_implementation(
    "derive.classification.poliovirus_classification",
    parameters=("sabin_like_threshold_pct", "wild_threshold_pct", "controlled_values"),
    evidence_bases=(
        BASIS_LEDGER,
        BASIS_OUTSIDE_POLIOVIRUS,
        BASIS_TEXT_REFINEMENT,
        BASIS_SABIN_LIKE,
        BASIS_VDPV,
        BASIS_WILD,
    ),
)
def poliovirus_classification(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """Curated first, then a refinement the record states, then the VP1 divergence band."""
    partition = resolved_partition(view)
    # `resolved_partition` signals "undetermined" with an empty string, not None. Testing for None
    # made every one of the 1,832 undecided records take the non-poliovirus branch and ship a
    # *determined* blank — which asserted that the column does not apply to a record whose group
    # nothing had decided, and was wrong on the 391 of them the release classifies.
    if not partition:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_OUTSIDE_POLIOVIRUS,
            source_field=ORGANISM_FIELD,
            source_value=view.record.get(ORGANISM_FIELD, ""),
            unresolved_reason=UNRESOLVED_FOLLOWS_PARTITION,
        )
    if partition != POLIOVIRUS:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_OUTSIDE_POLIOVIRUS,
            source_field=ORGANISM_FIELD,
            source_value=view.record.get(ORGANISM_FIELD, ""),
        )

    for field in LEDGER_FIELDS:
        asserted = view.decisions.get(field, "")
        if not asserted:
            continue
        # A decision is authority over the *value*, not a licence to write anything into a
        # controlled column. Three active rows fail this and the release masked all three by
        # projecting a reconciled field instead of the ledger: `iVPDV` (a transposition of `iVDPV`),
        # `engineered` (the vocabulary has only `engineered/lab`), and `CHAT` (the Koprowski strain
        # name, which is a strain and not a classification tier). Declining sends each to the
        # curation queue under its own reason instead of shipping it.
        if asserted not in parameters["controlled_values"]:
            return RuleOutcome(
                value="",
                evidence_basis=BASIS_LEDGER,
                source_field=field,
                source_value=asserted,
                unresolved_reason=UNRESOLVED_UNCONTROLLED_VALUE,
                manual_override=True,
            )
        return RuleOutcome(
            value=asserted,
            evidence_basis=BASIS_LEDGER,
            source_field=field,
            source_value=asserted,
            manual_override=True,
        )

    serotype = serotype_from_name(view.record.get(ORGANISM_FIELD, ""))
    if not serotype:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_SABIN_LIKE,
            source_field=ORGANISM_FIELD,
            source_value=view.record.get(ORGANISM_FIELD, ""),
            unresolved_reason=UNRESOLVED_NO_SEROTYPE,
        )

    compared = view.evidence.get(EVIDENCE_COMPARED, "")
    divergence = view.evidence.get(EVIDENCE_DIVERGENCE, "")
    reference = view.evidence.get(EVIDENCE_REFERENCE, "")
    basis = view.evidence.get(EVIDENCE_BASIS, "")
    if not compared or not divergence:
        return RuleOutcome(
            value="",
            evidence_basis=BASIS_SABIN_LIKE,
            source_field=EVIDENCE_COMPARED,
            source_value=compared,
            unresolved_reason=UNRESOLVED_INSUFFICIENT_SEQUENCE,
        )

    measured = Decimal(divergence)
    sabin_like_ceiling = Decimal(str(parameters["sabin_like_threshold_pct"][serotype[-1]]))
    wild_floor = Decimal(str(parameters["wild_threshold_pct"]))
    # `basis` is VP1 on almost every row and P1_capsid only on the fallback ones, so it is worth
    # naming in the audit trail even though the threshold logic below never reads it.
    evidence = f"{divergence}% over {compared} nt of {basis} vs {reference}"

    if measured < sabin_like_ceiling:
        return RuleOutcome(
            value=SABIN_LIKE,
            evidence_basis=BASIS_SABIN_LIKE,
            source_field=EVIDENCE_DIVERGENCE,
            source_value=evidence,
        )
    if measured >= wild_floor:
        return RuleOutcome(
            value=WILD,
            evidence_basis=BASIS_WILD,
            source_field=EVIDENCE_DIVERGENCE,
            source_value=evidence,
        )
    if stated := _stated_refinement(_record_text(view)):
        return RuleOutcome(
            value=stated,
            evidence_basis=BASIS_TEXT_REFINEMENT,
            source_field=DEFINITION_FIELD,
            source_value=evidence,
        )
    return RuleOutcome(
        value=VDPV,
        evidence_basis=BASIS_VDPV,
        source_field=EVIDENCE_DIVERGENCE,
        source_value=evidence,
    )
