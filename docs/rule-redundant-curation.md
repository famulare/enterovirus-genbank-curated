# The 531 decisions the rules now reach unaided

**This document asks for a ruling and does not make one.** Nothing here changes a shipped value —
that is what `applied_unchanged` *means*, and it is the reason this can be decided calmly after
5.0.0 rather than inside it.

`final/audit/decision_applications.tsv.gz` records, per decision, what the build would have produced
with the ledger withheld (`curate/apply.project_without_decisions`). 531 rows come back
`applied_unchanged`: the rule reaches the value the curator asserted, without the curator. That is
the ledger asserting what the pipeline already derives.

The machine-readable list is [`rule-redundant-curation.tsv`](rule-redundant-curation.tsv) — one row
per decision, with the rule that now derives it, that rule's version, the counterfactual evidence
basis, and the curator's own reason.

## Why this is a question and not a chore

There is precedent: 162 rows were retired on 2026-07-30 under exactly this reasoning, and 11 more
on 2026-08-14. `tests/test_decision_ledger.py`'s `RULE_REDUNDANT_RETIREMENTS` already carves out
"retired because a rule now derives the value" as a distinct meaning of `retired`. So the mechanism
exists.

What that precedent cost is the thing to weigh. An `applied_unchanged` decision is a human having
confirmed the value independently — 530 of the 531 carry `confirmed_by = Mike`. Retire it and a
later rule change moves that cell silently, with no curator record that anyone ever looked. The
2026-07-30 batch accepted that trade for 162 rows; whether it holds for 531 is a judgement about how
settled *these particular rules* are, which is why the table below is grouped by rule and basis
rather than presented as one number.

The count itself is already watched: `tests/test_decision_application.py`'s `EXPECTED_TALLY` pins
`applied_unchanged` at 531, so it cannot drift without a test failing. Leaving these active is
therefore a live, measured position rather than a backlog item quietly accumulating.

## The twelve groups

Grouped by the counterfactual basis — *what would have settled the cell* — because that, not the
column, is what says whether the redundancy is solid.

| # | canonical field | rule | basis that would have decided it | n | rule/basis last moved |
|---:|---|---|---|---:|---|
| 1 | `poliovirus_classification` | R-CLASS-2 | `vdpv_refinement_in_record_text` | 251 | 2026-07-31 and again in 5.0.0 |
| 2 | `poliovirus_classification` | R-CLASS-2 | `vp1_divergence_at_or_above_wild_threshold` | 241 | measurement changed in 5.0.0 |
| 3 | `engineered_or_construct` | R-CONSTRUCT-2 | `no_structural_synthetic_signal` | 7 | 2026-07-31 |
| 4 | `poliovirus_classification` | R-CLASS-2 | `isolate_linked_inference` | 6 | 5.0.0 |
| 5 | `engineered_or_construct` | R-CONSTRUCT-2 | `synthetic_division_or_organism` | 6 | 2026-07-31 |
| 6 | `sample_origin` | R-ORIGIN-2 | `genbank_division` | 5 | **new in 5.0.0** |
| 7 | `poliovirus_classification` | R-CLASS-2 | `vp1_divergence_below_sabin_like_threshold` | 5 | measurement changed in 5.0.0 |
| 8 | `poliovirus_classification` | R-CLASS-2 | `named_wild_reference_strain` | 4 | **new in 5.0.0** |
| 9 | `surveillance_stream` | R-SURVEILLANCE-2 | `environmental_sample_flag` | 2 | **new in 5.0.0** |
| 10 | `collection_date` / `_precision` | R-DATE-2 / R-DATE-PRECISION-2 | `surveillance_identifier_year` | 2 | **new in 5.0.0** |
| 11 | `poliovirus_classification` | R-CLASS-2 | `text_classification_no_sequence_signal` | 1 | 2026-07-31 |
| 12 | `virus_type` | R-TYPE-2 | `enterovirus_type_in_definition_line` | 1 | **new in 5.0.0** |

The ledger sources concentrate: 293 rows come from `manual_review_overrides.csv` and 231 from
`vdpv_wild_reconciliation.csv`; the other 7 are spread across four artifacts.

## Recommended disposition, per group

**Groups 6, 8, 9, 10, 12 (14 rows) — keep, without argument.** Every one of these bases *first
shipped in 5.0.0*. A rule agreeing with a curator two weeks after the rule was written is one
observation, not evidence the rule is settled. Retiring on it would discard the only independent
check these branches have.

**Group 3, and arguably 5 (7 and 6 rows) — keep, and note that the redundancy is not real.**
`no_structural_synthetic_signal` is R-CONSTRUCT-2 reporting that it found *no* signal, which yields
`FALSE`. The curator also concluded `FALSE`. Those are not the same act: the rule declined to see
something, the curator looked and decided. `applied_unchanged` cannot tell the two apart, and this
is the group where that limitation bites. This is worth recording as a limitation of the status
rather than acting on.

**Group 2 (241 rows) — the one defensible retirement, and I still recommend keeping it this
round.** These are records the sequence puts at or above the 15% wild threshold, which is the
release's own published parameter over a measurement rather than a text read. That is the most
rule-like of the twelve. But `compare_vp1` changed in 5.0.0 — it now skips ambiguous positions —
so the measurement underneath these 241 moved in the release that would be retiring them. One
release of stability first.

**Group 1 (251 rows) — keep.** R-CLASS-2 is the most-changed rule in the catalog: widened from three
qualifier fields to five on 2026-07-31, and given the transmission-attestation exception in 5.0.0.
It is at version 1.1.0 and moving. This is the group where a silent later change would do the most
damage, and the largest.

**Net recommendation: retire nothing this cycle; revisit groups 1 and 2 at 6.0.0**, split by whether
R-CLASS-2 changed in the interval. That keeps `applied_unchanged` non-zero and informative — a
rising count means rules are absorbing curation, which is the direction of travel this rewrite
wants — and it costs nothing, because none of these 531 decisions is doing anything to the data
today.

If the ruling goes the other way for any group, the mechanics are the C4 ones: derived
`decision_id`s, `status = retired`, a reason naming the rule that now derives the value, and
`RULE_REDUNDANT_RETIREMENTS` updated from 173 (`162 + 11`).

## Reproducing this

The counterfactual is computed on every build but not written out. The table here was produced by
re-running `curate/apply.project_without_decisions` against the same views the build assembles and
joining its `evidence_basis` onto the `applied_unchanged` rows of
`final/audit/decision_applications.tsv.gz`. If this becomes a recurring question rather than a
one-off, the honest fix is to write the counterfactual basis into that audit table so the grouping
is a column rather than a script.
