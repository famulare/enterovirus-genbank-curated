# Every `poliovirus_classification` difference from 2.4.1, accounted for

`poliovirus_classification` is the one column where a shipped value can encode a judgement that no
input in this clone contains. The distinction between `VDPV`, `cVDPV` and `iVDPV` is
**epidemiological** — ambiguous, circulating, or immunodeficient — and no property of a sequence
carries it. `wild` on a record with no VP1 is the same kind of claim.

Those calls are hard-won. They were made against published phylogenies and outbreak
investigations, and 1,506 of the ledger's active rows already cite a PMID for exactly this reason.
**A coarsened value is a lost judgement, not a conservative one**, and this file names precisely
which ones are still lost so they can be migrated rather than rediscovered.

`docs/classification-migration-gap.tsv` is the machine-readable list — **all 1,649 differing
records**, one row each, with the value 2.4.1 ships, the value this pipeline emits, the
`unresolved_reason` if it declined, and a category. Every row has a category; the count of
uncategorised rows is asserted to be zero, because "we looked at the big buckets" is how a residue
of unexplained differences survives a review.

Over the 24,299 records both datasets carve, the column now **agrees on 22,650 (93.2%)**.

An earlier version of this file covered only the 1,161 rows where 2.4.1 ships a *refinement* or
`wild`. That was the interesting subset, not the whole difference, and scoping a reconciliation to
the interesting subset is how the remaining 998 would have gone unnoticed.

## All 1,649, by category

| category | n | what it means |
|---|---:|---|
| `declined_too_little_sequence` | 1,409 | too little usable sequence, by VP1 or the capsid fallback, to measure divergence over |
| `declined_membership_undecided` | 153 | organism name cannot settle poliovirus membership |
| `sequence_band_disagrees_with_release` | 38 | both resolved, divergence lands in a different band |
| `declined_no_serotype_in_name` | 33 | no serotype in the organism name to pick a Sabin reference |
| `record_text_refines_beyond_the_release` | 8 | the record's own text is *finer* than 2.4.1 |
| `ledger_refines_beyond_the_release` | 4 | the ledger is *finer* than 2.4.1 |
| `shipped_class_outside_sequence_reach` | 4 | shipped `chimera` — a Sabin/wild recombination junction, computed by 2.4.1, not read from text |

The last two categories are worth noticing: on twelve records this pipeline is **more** specific than
the release, not less. A reconciliation that only counted losses would have reported them as noise.

Three categories that appeared in earlier versions of this file are gone entirely, all closed by
decisions landed 2026-07-31 rather than by a rule:

* **`coarsened_attribution_not_in_sequence`** (was 348, then 95) — see below.
* **`declined_ledger_value_out_of_vocabulary`** (was 3) — `AJ416942` (`CHAT`), `DQ205099`
  (`engineered`) and `FJ517648` (`iVPDV`) were the only active decisions asserting a value the
  controlled vocabulary does not contain, so the rule declined all three and the release masked it
  by projecting a reconciled field instead of the ledger. Each is now repaired by a decision that
  carries the same verdict in a token the column accepts — see
  [`registry/README.md`](../registry/README.md#status-vocabulary) for why the malformed rows are
  `superseded` rather than `retired`.
* **20 of the 24 `shipped_class_outside_sequence_reach` records** (12 `Sabin`, 5 `vaccine`, 3
  `engineered/lab`) — see below. Only the 4 `chimera` records remain, because they are computed, not
  read from text, and this pipeline has no recombination-detection rule to compute them the same way.

### Reading the whole record cut the coarsening from 348 to 95, then decisions closed the rest

`coarsened_attribution_not_in_sequence` was **348** (302 `cVDPV`, 46 `iVDPV`). The rule was reading
only `definition`, `strain` and `isolate`, and **248 of those records state the release's own
refinement in one of the two other record-level `source` qualifiers**, `isolation_source` or `note`.
That is not epidemiology this pipeline cannot see; it is epidemiology it was not looking at.

* 202 via `note` — the largest block is the Angola 2019–2020 cVDPV2 set, whose `note` reads
  `type: cVDPV2 VP1` on all 192 records.
* 36 via `isolation_source` and 13 via `note` for `iVDPV`, e.g. `stool specimen from immunodeficient
  infant`, `genotype: iVDPV`.
* 5 via `note` reading `Single recombinant cVDPV2-n`, which is *finer* than the `cVDPV` 2.4.1 ships.

`iVDPV` matches an immunodeficient host as well as the literal token, because the refinement is a
claim about the host and a depositor who writes `isolation_source="... from an immunodeficient
individual who received OPV and developed paralysis"` has stated it as plainly as one who writes
`iVDPV`. This is the same record-level standard MAD-VDPV settled on for its own text miner, after it
found a title-only match stamping `iVDPV` onto a paper's wild comparators.

**`cVDPV` gets no matching widening, and the asymmetry is deliberate.** Circulation is a property of
a transmission chain reconstructed across isolates, so no single deposit's own text can establish it,
and there is no `cVDPV` equivalent of "immunodeficient individual" for a depositor to state. A record
that says `cVDPV` outright is honoured; nothing is inferred on its behalf.

The remaining 95 were two published studies, and their circulation claim lives in the paper rather
than in any deposit's own text:

| n | accessions | evidence | own `note` / `isolation_source` |
|---:|---|---|---|
| 68 | `PQ740659`–`PQ824229` | *Detection of circulating vaccine-derived poliovirus type 2 (cVDPV2) in wastewater samples: a wake-up call, Finland, Germany, Poland, Spain, the United Kingdom, 2024* — PMID **39850005** on 20 of the 68, the same title on all 68 | `wastewater` / `Sewage` |
| 27 | `KP143045`–`KP143072` | *Circulating vaccine-derived polioviruses in the Extreme North region of Cameroon* — PMID **25542478** on all 27 | `genotype: OPV2-like` |

The Cameroon set is the sharper illustration: `OPV2-like` is Sabin-2 descent with **no** circulation
claim, so the record's own text supports `VDPV` and it is the paper that supports `cVDPV`. That is
exactly the shape of a curation decision, not a rule, and both studies are now recorded as active
`manual_override` decisions (`source_artifact=curator_adjudication_2026-07-31`), `confirmed_by=Mike`,
each citing its PMID and stating plainly that the record's own text does not and cannot carry a
circulation claim — see the next section for why that provenance is not the same as the release's.

### Why these needed a decision and not a migration

MAD-VDPV ships 1,970 `cVDPV`/`iVDPV` records from two disjoint sources, traced through its working
tree on 2026-07-31:

| source in MAD-VDPV | n | provenance it carries | present here? |
|---|---:|---|---|
| `manual_review_overrides.csv` — the hand ledger | 1,601 | `confirmed_by=Mike`, a `source`, and a per-record `note`; a PMID or DOI on 1,512 | **all of it**, migrated, and 2.4.1 already ships it in `audit/manual_decisions.tsv.gz` |
| `classification_label_normalized_genbank` — regex text mining | 369 | a verbatim regex match string, `confidence=high`, `review_status=locked_from_genbank`; **no** `confirmed_by`, `curation_rule`, `curation_notes` or `source_artifact_id` | the 348 this file originally counted |

The two sets do not intersect: **not one of the 348 had a row in the hand ledger**, and not one hand
ledger row was ever lost here. Nor is there commit-message provenance to recover — `git log
-S<accession>` on a sample of the 348 returns only release-regeneration commits. Nothing was ever
written *about* any of them.

MAD-VDPV's own methodology document is explicit about the risk in that second row
(`gpln_classification_rules.md`): literature `cVDPV` usage "is unreliable. Surface those cases for
review rather than blindly inheriting the label." Its curation log records the bulk being accepted
anyway, "No carve-out." Both statements are on disk; the tension between them is not reconciled
anywhere. So the 95 records above were curation, not migration — a fresh per-record review against
the cited papers, added here with the confirmation the automated tail never received. Do not
synthesise a value like this without that review: a `cVDPV` written without the phylogeny that
established it is indistinguishable in the artifact from one that was earned, which would make the
whole column untrustworthy rather than merely incomplete.

### The capsid (P1) nucleotide fallback recovered 148 of these

`declined_too_little_sequence` was 1,557 before `derive/evidence.compare_capsid_nt` landed — the
same VP1-first / P1-fallback precedence MAD-VDPV's own `classify_sequence_tier.py` states outright,
applied because 1,911 carved, name-serotyped records have no usable VP1 at all. Of those, 159 clear
the fallback's own guards (300 nt minimum, and a homogeneity check described below), 11 already had
an active ledger decision that would have resolved them regardless, and **148 newly resolve** —
every one agreeing with the shipped classification wherever 2.4.1 has one to compare against.

The fallback needed a guard `compare_vp1` does not, and three records found it before it shipped.
VP1 in poliovirus has no indels relative to Sabin — a measured fact, and the reason an ungapped
single-offset comparison is exact there — but that fact does not extend to VP4, VP2 or VP3. Two
records (`AB162760.1`, `AB162761.1`) read >18 percentage points more divergent than MAD-VDPV's own
alignment reports for the same accessions, with mismatches beginning at one exact position and
running at the unrelated-sequence rate for the rest of the window; shifting the query by **one
nucleotide** from that position on restores 98-100% identity. A real indel in a coding, actively
replicating poliovirus genome must be a multiple of three to preserve the reading frame, so a 1-nt
break is a single bad base call in the deposit, not biology — and the single fixed diagonal has no
way to know it crossed one. `derive/evidence.py` splits the compared span into 150 nt chunks and
declines the whole comparison unless every chunk of at least 30 compared positions sits within 15
percentage points of the whole window's own divergence; measured over every record that reaches any
capsid-nt comparison, the three broken windows sit at 21.5, 21.8 and 55.2 points of internal
deviation and the next-highest genuine one sits at 8.1 — the floor sits in that gap, not fitted to
the three cases that found it.

### Membership is fully understood, and it is a cleaner story

`virus_group` and `curation_status` differ on 1,588 shared rows each, and **every single one is a
decline** — `organism_name_does_not_determine_membership`, and `follows_unresolved_virus_group`
downstream of it. There is not one row where this pipeline asserts a membership that contradicts
2.4.1. 1,435 of them the release calls `non_polio_enterovirus` and 153 `poliovirus`.

## What is already recovered, and how

Nothing here should be migrated twice. Three mechanisms already carry curated classifications:

1. **The ledger's `classification` / `verified_classification` rows** — 2,162 of them. R-CLASS-2
   emits these outright, ahead of any sequence evidence.
2. **The membership entailment** (`derive/partition.py`). A curated classification value comes from
   a poliovirus-only vocabulary, so asserting it asserts poliovirus membership. This recovered **259
   calls** that an earlier ordering discarded: their organism names are `Enterovirus C` or
   `Enterovirus coxsackiepol`, the partition declined on that, and the classification then declined
   for "following" the partition — throwing away a paper-based judgement because a *weaker* signal
   was silent. All 259 ship as `poliovirus`/`vouched` in 2.4.1.
3. **The 2026-07-31 decisions** — 115 rows, the 95 cVDPV records above and the 20 strain-identity
   decisions below, both traced and confirmed rather than inherited.

## The 20 that used to be miscategorised as "outside sequence reach"

The 24 `shipped_class_outside_sequence_reach` records were originally described here as classes "the
release took from text". That was wrong for a quarter of them, and the correction changed what the
right instrument was for each:

| shipped | n | how 2.4.1 actually produced it | resolved how |
|---|---:|---|---|
| `Sabin` | 12 | strain identity — the record *is* an OPV seed-strain deposit, not merely close to one in divergence | decision, 2026-07-31 |
| `vaccine` | 5 | a documented hardcoded strain-family map (`Cox`, `Lederle`, `CHAT`), matched on the GenBank `strain` field | decision, 2026-07-31 |
| `engineered/lab` | 3 | patent division plus the definition `Modified Microbial Nucleic Acid` (patent JP 2009538603-A) | decision, 2026-07-31 |
| `chimera` | 4 | **computed, not text** — recombinant-junction detection, shipped as its own rule | still open, see below |

The 12 `Sabin` decisions include this pipeline's own three canonical references — `AY184219`,
`AY184220`, `AY184221` already carried `canonical_reference=TRUE` rows naming them canonical Sabin
1/2/3, so asserting `classification=Sabin` for them states the same fact the ledger already had.
`X00595` is the sharpest of the twelve: it is Sabin 2 — the ledger's own `AX348183` row notes the
GenBank cross-reference saying so — and it reads `VDPV` at 0.664% over 879 nt of VP1 against a
0.600% ceiling. That is 6 mismatches where the threshold allows 5. Divergence cannot distinguish the
seed strain from its own descendants, and one nucleotide decides the band.

The 5 `vaccine` decisions have ledger precedent already: `AJ293918` (USOL-D-bac), `AY359875` (Fox)
and `AJ416942` (CHAT) are all classified `vaccine` on the same strain-family reasoning.

### `chimera`: an attempted rule, reverted

A recombination-detection rule was built and tested against these four records
(`OR208593`, `OR208600`, `OR208605`, `OR208612`) — none of the four contains "chimera" or
"recombinant" anywhere in its record text, so this is a measurement 2.4.1 makes, not a text read, and
a window scan against each record's own name-serotype Sabin reference correctly located the same
recombination breakpoint 2.4.1's own `recombination_breakpoint_ref` names for `OR208593` (position
2991, inside VP1 itself).

The rule was **not shipped**: applied over the whole corpus, the chimera threshold it computed fired
on 196 records, 192 of them records 2.4.1 ships as ordinary `VDPV`, `cVDPV`, `iVDPV` or even
`Sabin-like` — a false-positive rate that makes the rule unsafe rather than merely imprecise.
Recombination between a Sabin-derived capsid and a more divergent non-structural region is the
ordinary shape of VDPV evolution, not an exception, so a threshold loose enough to catch these four
also catches a large fraction of every other recombinant VDPV in the corpus. Reproducing 2.4.1's own
chimera threshold precisely was not achievable from the one-paragraph rule description in
`registry/rules.json` alone — its own text hedges this ("the threshold rule has no defined input")
— and the source it implements, `resolve_recombinant_segments.py`, is not in this clone to check
against. The four records stay `wild`/`VDPV` here rather than risk a rule that would misclassify
roughly fifty times as many records as it fixes.

## The 787 where a curated refinement or `wild` is the thing lost

| 2.4.1 ships | this pipeline emits | why | n |
|---|---|---|---:|
| `wild` | *(blank)* | too little usable sequence, by either basis, to measure over | 750 |
| `wild` | `VDPV` | divergence lands in the 1–15% band | 13 |
| `wild` | *(blank)* | partition undecided | 5 |
| `cVDPV` | `cVDPV-n` | **finer**: the depositor's `note` says `cVDPV2-n` | 5 |
| `wild` | `Sabin-like` | divergence under 1% | 4 |
| `iVDPV` | `wild` | divergence at or above 15% | 4 |
| `cVDPV` | *(blank)* | too little usable sequence | 4 |
| `cVDPV` | `Sabin-like` | divergence under 1% | 2 |

Every one is a distinct accession, so 787 rows would close this subset (the 4 `chimera` records are
a separate mechanism, not this one, and are covered above); the full 1,649 is in the TSV, and the
categories above say which of them a ledger row is even the right instrument for. Five of the 787
are a gain rather than a loss (the `cVDPV-n` row). The `wild -> (blank)` row fell from 781 to 750
with the capsid fallback — only 31 of the 148 newly-resolved records shipped `wild`; most of the
rest shipped `Sabin-like` or a bare `VDPV`, which is why the fallback's headline number (148) and
this table's movement (31) differ.

The `cVDPV` and `iVDPV` rows that used to dominate this table are gone entirely: all 46 `iVDPV`
records stated immunodeficiency in their own record, and the 95 `cVDPV` records now trace to the two
studies above rather than to a coarsened band. This pipeline now ships 1,757 `cVDPV`, 25 `cVDPV-n`
and **205** `iVDPV`, against 2.4.1's 1,767, 20 and 203 — nearly the same totals by a different route,
with the two extra `iVDPV` being records whose `isolation_source` names an immunodeficient host and
which 2.4.1 left at `VDPV`.

### Lowering the VP1 floor does not help — measured

`MIN_VP1_NT = 300` is this pipeline's own measurement-quality floor, not a published parameter, so
it was fair to ask whether relaxing it would recover the 785 blocked by it (as measured before the
capsid fallback existed). Measured with the floor removed entirely:

* **680 of the 785 have no VP1 overlap at all.** No threshold reaches them. They are 5′UTR, VP4/VP2
  or 3D fragments, and the question is not how confidently VP1 is measured but whether VP1 is
  present.
* Of the 105 that do overlap, the median window is **90 nt**. A no-floor call gets **72 right and 33
  wrong** — 25 would ship `VDPV` and 8 `Sabin-like` against a shipped `wild`.

69% is not a threshold, it is a coin weighted toward the answer. The floor stays at 300 and these
records stay declined by *lowering it*, which is the same reasoning that keeps `sequence_scope`
pending rather than fitted to 86.7%. The capsid fallback above is a different move — not a lower bar
on the same short window, but a longer window over more sequence, guarded against exactly the new
failure mode a longer window introduces.

### The two that are a known, unfixable-by-sequence trap

`wild → Sabin-like` includes **V01149.1 (Mahoney)** and **V01540.1**. Sabin 1 *is* attenuated
Mahoney — about 1% divergent across VP1 — so VP1 distance to Sabin cannot separate the wild parent
from its own vaccine derivative. No parameter choice fixes this; it needs the ledger.

## How to migrate what remains

The path is the documented one in [`registry/README.md`](../registry/README.md#migration), and its
one hard rule applies here too: extract the private registries **at the release's own build commit**,
never at the private tip, because curation continues there and a tip migration silently absorbs rows
that belong to a later release.

```bash
rm -rf /tmp/evgc-registries && mkdir -p /tmp/evgc-registries
git -C ../MAD-VDPV archive <release-build-commit> data/genbank/working \
  | tar -x -C /tmp/evgc-registries --strip-components=3
```

What remains after the 2026-07-31 decisions is `declined_too_little_sequence` (1,409, a measurement
floor, not a migration target), `declined_membership_undecided` (153, needs the membership
question settled first), `declined_no_serotype_in_name` (33), `sequence_band_disagrees_with_release`
(38, genuine threshold disagreements) and the 4 `chimera` records above, which need a correctly
validated recombination rule rather than a decision.
