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
5. Otherwise the divergence band, VP1 if at least 50 nt of VP1 was compared (below 300 nt, only if
   it also clears the chunked-homogeneity guard), else the capsid fallback over the same floor and
   guard (`derive/evidence.compare_capsid_nt`).
6. No serotype in the organism name to pick a reference with: decline.
7. No divergence measurement by either basis: fall back to `wild`/`VDPV`/`Sabin-like` named in the
   record's own text or the cited paper's title (`_group_b_text_fallback`) — MAD-VDPV's own
   `needs_other_data_text_fallback`. `iVDPV`, `cVDPV` and the reference/lab labels are excluded from
   this fallback on purpose; see `_GROUP_B_TEXT_PATTERNS`.
8. Otherwise decline — too little usable sequence by either basis, and no text label to fall
   back to.

`unresolved` is a value in the shipped vocabulary and this rule never emits it. A cell the pipeline
cannot decide is an unresolved *cell*, carrying its reason into the provenance table and the
curation queue; writing "unresolved" into the column would record a non-answer as an answer.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
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
# Both carried on the `source` feature, which is the only feature `derive/apply.py` collects
# qualifiers from — so these are record-level statements by the depositor about this deposit, the
# same standing as `strain` and `isolate` and not the same standing as a study title.
ISOLATION_SOURCE_QUALIFIER = "isolation_source"
NOTE_QUALIFIER = "note"
# Not `DEFINITION_FIELD`: the text-refinement branch already uses that `source_field` for a
# `source_value` that is a divergence citation (a real measurement exists on that branch, and the
# text only picks a refinement within its band). The fallback below has no measurement to cite —
# its `source_value` is the matched substring itself — and giving it a different field name is what
# keeps `test_the_real_build_writes_the_measurement_r_class_2_cited` from mistaking one for the
# other.
REFERENCE_TITLES_FIELD = "reference_titles"

EVIDENCE_DIVERGENCE = "divergence_pct"
EVIDENCE_COMPARED = "compared_nt"
EVIDENCE_REFERENCE = "reference_version"
EVIDENCE_BASIS = "basis"
EVIDENCE_REFERENCE_SEROTYPE = "reference_serotype"

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
BASIS_TEXT_FALLBACK = "text_classification_no_sequence_signal"

UNRESOLVED_FOLLOWS_PARTITION = "follows_unresolved_virus_group"
UNRESOLVED_NO_SEROTYPE = "no_serotype_in_organism_name_to_choose_a_reference"
# Covers both a VP1 measurement that never reached MIN_VP1_NT and a capsid fallback that either
# could not reach MIN_CAPSID_NT or failed the homogeneity guard — one reason, matching the existing
# grain of this rule's other reasons: `compare_vp1` already collapses several distinct failures
# (no diagonal, too short, implausible) into the one outcome of returning `None`.
UNRESOLVED_INSUFFICIENT_SEQUENCE = "too_little_sequence_compared_to_measure_divergence"
UNRESOLVED_UNCONTROLLED_VALUE = "curated_value_outside_the_controlled_vocabulary"

# Refinements a depositor may state outright. Longest-first, so `cVDPV` is not read as `VDPV`.
#
# `iVDPV` matches an immunodeficient *host* as well as the token, because the refinement is a claim
# about the host and a depositor who writes `isolation_source="... from an immunodeficient
# individual who received OPV and developed paralysis"` has stated it as plainly as one who writes
# `iVDPV`. This is the same record-level standard MAD-VDPV settled on: its own text miner gates
# `iVDPV` on immunodeficiency evidence in record-level fields specifically, after a title-only match
# was found stamping `iVDPV` onto a paper's wild comparators.
#
# `cVDPV` gets no matching widening, and the asymmetry is deliberate. Circulation is a claim about a
# transmission chain reconstructed across isolates, so no single record's own text can establish it,
# and there is no `cVDPV` equivalent of "immunodeficient individual" for a depositor to state. A
# record that says `cVDPV` outright is honoured; nothing is inferred on its behalf.
#
# `aVDPV` was here and is deliberately gone. It is not in this column's controlled vocabulary, so
# emitting it shipped a value the column does not declare — see `_stated_refinement`.
_REFINEMENTS = (
    (re.compile(r"\bcvdpv[123]?-?n\b", re.IGNORECASE), "cVDPV-n"),
    (re.compile(r"\bcvdpv", re.IGNORECASE), "cVDPV"),
    (re.compile(r"\bivdpv|immunodeficien|immunocompromised", re.IGNORECASE), "iVDPV"),
)

# The band a record's own text may state when no sequence measurement of any kind exists to ask
# instead — `derive.evidence` never got a comparison to make, not "made one and a decision
# overrides it". Longest/most-specific first, matching MAD-VDPV's own `CLASS_PATTERNS` order and
# regexes (`infer_genbank_metadata.py`) for the three bands this pipeline can also reach by
# sequence: `VDPV` (`aVDPV` included and normalized, the same treatment `_stated_refinement`
# already gives it), `Sabin-like`, `wild`.
#
# `iVDPV`, `cVDPV` and the reference/lab labels (`Sabin`, `vaccine`, `engineered/lab`, ...) are
# deliberately absent, not merely lower-precedence: MAD-VDPV's own text miner reaches those too, but
# every record in *this* pipeline's corpus where it does was traced and migrated as an individual
# ledger decision (`reference_or_lab_text`, `group_A_text_owned`), not automated, because
# circulation and strain identity are curator calls this pipeline has no automated input for.
# Restricting the pattern list rather than filtering matches afterward means a record whose text
# says `cVDPV` is not matched at all here (`\bVDPV\b` does not match inside `cVDPV` — no word
# boundary precedes the `V`), so it falls through to decline exactly as it did before this rule
# existed, the same conservative default as finding no text at all.
_GROUP_B_TEXT_PATTERNS = (
    (re.compile(r"\bavdpv\b|\bvdpv\b|vaccine[- ]derived poliovirus", re.IGNORECASE), VDPV),
    (re.compile(r"sabin[- ]like", re.IGNORECASE), SABIN_LIKE),
    (re.compile(r"\bwild[- ]?type\b|\bwpv[123]?\b|wild poliovirus", re.IGNORECASE), WILD),
)


def _record_text(view: RecordView) -> str:
    return " ".join(
        (
            view.record.get(DEFINITION_FIELD, ""),
            view.qualifier(STRAIN_QUALIFIER),
            view.qualifier(ISOLATE_QUALIFIER),
            view.qualifier(ISOLATION_SOURCE_QUALIFIER),
            view.qualifier(NOTE_QUALIFIER),
        )
    )


def _stated_refinement(text: str, controlled_values: Collection[str]) -> str:
    """The refinement the record states, or empty when it states none this column can carry.

    The vocabulary check is applied here and not only on the ledger path. It used to guard the
    ledger alone, so `aVDPV` — which the vocabulary does not contain — shipped on `PP481414` from
    the text path while the identical string asserted by a decision would have been declined. One
    rule cannot hold two standards for the same column, and the release ships `VDPV` there, which is
    true of every record in the band.
    """
    for pattern, value in _REFINEMENTS:
        if pattern.search(text):
            return value if value in controlled_values else ""
    return ""


def _group_b_text_fallback(text: str, controlled_values: Collection[str]) -> tuple[str, str]:
    """`(value, matched substring)` for the `wild`/`VDPV`/`Sabin-like` named in the text, for a
    record with no divergence measurement at all — MAD-VDPV's `needs_other_data_text_fallback`. See
    `_GROUP_B_TEXT_PATTERNS` for why `iVDPV`, `cVDPV` and the reference/lab labels are not in scope
    here. `("", "")` when nothing matches or the match is outside the controlled vocabulary.
    """
    for pattern, value in _GROUP_B_TEXT_PATTERNS:
        if match := pattern.search(text):
            return (value, match.group(0)) if value in controlled_values else ("", "")
    return "", ""


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
        BASIS_TEXT_FALLBACK,
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

    # The name is not the only source of a serotype. A record whose organism name is one of
    # `derive.partition.UNINFORMATIVE_ORGANISMS` has none to read here, but
    # `derive.evidence.measure_sequence_evidence` may already have identified one from the same
    # capsid-AA membership band that settled its `virus_group` — see that function's docstring. Only
    # a genuine VP1/capsid-nt measurement reaches `view.evidence` this way, never a guess standing
    # in for the declined name.
    serotype = serotype_from_name(view.record.get(ORGANISM_FIELD, "")) or view.evidence.get(
        EVIDENCE_REFERENCE_SEROTYPE, ""
    )
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
        # No sequence signal of any kind — not "measured, and a decision overrides it" (step 3
        # already returned for that), and not "measured, and the record's own text names a finer
        # refinement" (step 4, below, is the divergence band's business). MAD-VDPV's own text
        # miner reaches for the cited paper's title here, and so does this: `reference_titles`
        # is the one field genuinely absent from `_record_text`'s scope, because nowhere else
        # does this rule read the study rather than the deposit.
        fallback_text = " ".join(
            (_record_text(view), view.record.get(ORGANISM_FIELD, ""), view.reference_titles)
        )
        stated, matched_text = _group_b_text_fallback(
            fallback_text, parameters["controlled_values"]
        )
        if stated:
            return RuleOutcome(
                value=stated,
                evidence_basis=BASIS_TEXT_FALLBACK,
                source_field=REFERENCE_TITLES_FIELD,
                source_value=matched_text,
            )
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
    if stated := _stated_refinement(_record_text(view), parameters["controlled_values"]):
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
