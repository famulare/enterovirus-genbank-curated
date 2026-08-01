# Every `poliovirus_classification` difference from 2.4.1, accounted for

`poliovirus_classification` is the one column where a shipped value can encode a judgement that no
input in this clone contains. The distinction between `VDPV`, `cVDPV` and `iVDPV` is
**epidemiological** — ambiguous, circulating, or immunodeficient — and no property of a sequence
carries it. `wild` on a record with no VP1 is the same kind of claim.

Those calls are hard-won. They were made against published phylogenies and outbreak
investigations, and 1,506 of the ledger's active rows already cite a PMID for exactly this reason.
**A coarsened value is a lost judgement, not a conservative one**, and this file names precisely
which ones are still lost so they can be migrated rather than rediscovered.

`docs/classification-migration-gap.tsv` is the machine-readable list — **all 666 differing
records**, one row each, with the value 2.4.1 ships, the value this pipeline emits, the
`unresolved_reason` if it declined, and a category. Every row has a category; the count of
uncategorised rows is asserted to be zero, because "we looked at the big buckets" is how a residue
of unexplained differences survives a review.

Over the 24,299 records both datasets carve, the column now **agrees on 23,633 (97.3%)**.

An earlier version of this file covered only the 1,161 rows where 2.4.1 ships a *refinement* or
`wild`. That was the interesting subset, not the whole difference, and scoping a reconciliation to
the interesting subset is how the remaining 998 would have gone unnoticed.

## All 666, by category

| category | n | what it means |
|---|---:|---|
| `declined_too_little_sequence` | 422 | too little usable sequence, by VP1 or the capsid fallback, to measure divergence over, and no text or sibling to fall back to |
| `declined_membership_undecided` | 153 | organism name cannot settle poliovirus membership |
| `sequence_band_disagrees_with_release` | 42 | both resolved, divergence lands in a different band |
| `declined_no_serotype_in_name` | 33 | no serotype in the organism name to pick a Sabin reference |
| `record_text_refines_beyond_the_release` | 8 | the record's own text is *finer* than 2.4.1 |
| `ledger_refines_beyond_the_release` | 4 | the ledger is *finer* than 2.4.1 |
| `shipped_class_outside_sequence_reach` | 4 | shipped `chimera` — a Sabin/wild recombination junction, computed by 2.4.1, not read from text |

The last two categories are worth noticing: on twelve records this pipeline is **more** specific than
the release, not less. A reconciliation that only counted losses would have reported them as noise.

`declined_too_little_sequence` fell from 1,409 to 422 over 2026-07-31 — 28 closed by decisions, 60 by
lowering the divergence floor, 708 by a reference-title text fallback, and 191 by isolate-linked
inference, all four traced by decomposing this single largest category into MAD-VDPV's own named
mechanisms; see
"[Inside the largest block: what MAD-VDPV's own mechanism labels show](#inside-the-largest-block-what-mad-vdpvs-own-mechanism-labels-show)".

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

### Inside the largest block: what MAD-VDPV's own mechanism labels show

`declined_too_little_sequence` is 85% of every difference in this file, so it earns its own look
rather than a single category row. MAD-VDPV's working tree carries a `classification_reconciled_basis`
column naming exactly how it reached its own value for every record, and joining that column against
this pipeline's 1,409 declines (the count before the 2026-07-31 work below) resolves the whole block
into seven named, traceable mechanisms:

| mechanism | n | what it is |
|---|---:|---|
| `needs_other_data_text_fallback` | 548 | no capsid signal either; falls back to a label mined from the **cited paper's title**, not the deposit's own fields |
| `text_wild_override` | 219 | sequence *is* tierable, but the paper-title label overrides it outright |
| `isolate_linked_inference` | 167 | no usable signal of its own; inherits the call from a **sibling accession** sharing the isolate name |
| `group_B_sequence_newly_classified` / `group_B_sequence_tier` | 173 | MAD-VDPV's own sequence-only capsid comparison, over a window shorter than this pipeline's floor allowed |
| `unresolved_*` (four reason codes) | 274 | 2.4.1 also declines — ships the literal string `unresolved`, not a text/sibling fallback |
| `reference_or_lab_text` | 24 | strain-identity/patent text, the same kind of call as the 20 already migrated, just a population not yet found |
| `group_A_text_owned` | 4 | hard-won `cVDPV` epi calls, same category as the 95 above |

Of these, 274 are not a loss at all — 2.4.1 declines too, just with a different vocabulary (a literal
`unresolved` string instead of a blank cell carrying a reason). The other 1,135 are where 2.4.1 really
is more specific, and four of the seven mechanisms have now been closed:

**`reference_or_lab_text` (24) and `group_A_text_owned` (4) — migrated as decisions, 2026-07-31.**
Verified per record against GenBank directly, the same standard as the 95-record cVDPV work: 12
`Sabin` and 10 `engineered/lab` deposits traced to two patent families (`EP 0197772-A2` and
`EP 0383434-A1`/`EP 0383433-A1`, 15-24 nt fragments naming `Sabin` or `strain Leon` outright), a
handful more `Sabin` from PMID-cited 5′UTR/defective-interfering-particle papers, `M14761`
(`recombinant/lab`, PMID 3021340, a constructed Lansing-strain recombination junction) and `M17494`
(`reference/lab`, PMID 6267593, the Mahoney P3-1b region) — none a divergence measurement, all
strain-identity or patent facts a bare band cannot state. The 4 `group_A_text_owned` records
(`EU004575`, `KM233675`, `KM235192`, `KM235193`) trace to unpublished GenBank submitter references
rather than peer-reviewed papers — no PMID exists to check independently, which is recorded plainly
in the decisions rather than dressed up as equivalent to the PMID-cited work above.

**The VP1/capsid floor — lowered to MAD-VDPV's own 50 nt, 2026-07-31, with a new guard.**
`MIN_SEROTYPE_COMPARED_NT = 50` is MAD-VDPV's own published floor (`build_reference_alignments.py`),
well below this pipeline's 300 nt, and Mike validated by inspection that MAD-VDPV's calls at that
floor are sound. Matching it directly, with no guard beyond the floor itself, recovered 175
newly-filled records: 139 agreeing with the shipped value, 33 disagreeing in the shape of the
`text_wild_override` policy question below (not a measurement error), and **3 genuinely wrong** —
`AY320423`, `JN092124`, `AY365233` read 15-24 percentage points more divergent than MAD-VDPV's own
alignment, each a single bad base call in the deposited read (not a real indel — VP1 has none
relative to Sabin, but that fact never protected against an error in the read itself) corrupting a
171-225 nt window, the same failure class the capsid-fallback's own homogeneity guard was built to
catch — just never tested in VP1 before, because 300 nt was always enough sequence to dilute one bad
call rather than be defined by it.

`compare_vp1` now shares `compare_capsid_nt`'s chunked-homogeneity guard for windows under the old
300 nt floor (unchanged at or above it, so none of the 7,728 VP1 comparisons this stage already
shipped are at risk). With the guard in place, the floor drop recovers exactly **60** records — 45
VP1, 17 capsid, minus one (`AJ783799`) that already had a capsid-based value and simply moved to a
now-reachable VP1 window without changing it — and **every one of the 60 agrees with the shipped
classification.**

**`needs_other_data_text_fallback` — built 2026-08-01.** Reads the record's cited-paper title, a
signal `derive/classification._record_text` never reached (it reads `definition`, `strain`,
`isolate`, `isolation_source`, `note` — all record-level qualifiers, never the GenBank `REFERENCE`
block). `RecordView.reference_titles` is the new input, threaded from `tables["references"]`
through `derive/apply.py`; `_group_b_text_fallback` mines it (plus the existing record-level fields)
for `wild`/`VDPV`/`Sabin-like` only, fires only when this pipeline's own `compare_vp1`/
`compare_capsid_nt` measured nothing at all, and deliberately excludes `iVDPV`, `cVDPV` and the
reference/lab labels — those were traced and migrated as individual decisions this session, not
automated, because circulation and strain identity are curator calls with no automated input here.

Because this pipeline's own sequence-measurement method draws the "no signal at all" boundary in a
different place than MAD-VDPV's (a weaker, ungapped fixed-diagonal search against MAD-VDPV's real
aligner), the fallback fires on 708 records, not MAD-VDPV's 548. 705 agree with the shipped
classification; **3 are wrong** — `AF083938`, `HM537010`, `MG212473` all cite a paper title naming
`vaccine-derived poliovirus` (a VDPV-emergence study that also sequenced its own Sabin-like
parental/reference isolate), while MAD-VDPV's own alignment measures each at 0.000–0.333% over VP1.
This pipeline's `compare_vp1` cannot reach any of the three itself: each finds a diagonal with enough
anchor support to pass `MIN_DIAGONAL_ANCHORS`, but the offset is wrong (44% mismatches on
`MG212473`, the unrelated-sequence rate, over a *complete genome* where a real alignment reads
near-zero) — a gap in the diagonal search, not investigated further since it affects only these 3 of
24,308 carved records and fixing a seed-and-vote aligner is a different project than the text
fallback. For these 3, text answers a study-level question rather than a record-level one; the other
705 are the reason it is asked at all.

**`isolate_linked_inference` — built 2026-08-01.** A whole-corpus post-processing pass
(`derive/isolate_linkage.py`), not a per-record rule — it runs once, after every
`poliovirus_classification` row has already been projected, and inherits a classification from a
sibling accession sharing the same `isolate` (preferred) or `strain` qualifier and serotype,
mirroring MAD-VDPV's own `resolve_isolate_linked_inference.py`: a sibling counts only if its own
classification came from a real divergence measurement (not a decision, and not the fallback above —
propagating either would compound whichever one is wrong rather than carry forward an actual
measurement), applied only when every qualifying sibling agrees on one label, and a short key (three
alphanumeric characters or fewer — `L1`, `P05`, `V14`) is honoured only with the same batch-accession
corroboration MAD-VDPV uses (same prefix, same digit width, within 200 accession numbers).

Of 192 candidates, 191 link. 190 agree with the shipped classification; **1 does not** — `X70506`
links to `V01149.1` (Mahoney) among its qualifying siblings and inherits `Sabin-like`, the same known,
unfixable-by-sequence trap already on record two sections below (Sabin 1 *is* attenuated Mahoney, so
VP1 distance to Sabin cannot separate the wild parent from its own vaccine derivative) — not a new
failure mode, the existing one reaching a second record through a new path.

### `text_wild_override`: investigated, not reproduced

Mike asked for this one to be checked rather than ported outright, since MAD-VDPV's own rule is a
blanket policy — `text == wild` always wins, regardless of what the sequence says — and this pipeline
does not otherwise let text override a measurement it can make itself.

Of the 219 records under this basis, **175 are not actually a disagreement**: MAD-VDPV's own
sequence tier also reads `wild` there, so "override" is just how its bookkeeping labels every
`text == wild` record, whether or not anything was actually overridden. The remaining **44** are
genuine: MAD-VDPV's own VP1-based sequence tier computes `VDPV` (36) or `Sabin-like` (8), and the
paper-title text overrides it to `wild` anyway.

Every one of the 44 is a short VP1/2A-junction fragment — nearly all ~90-150 nt (`bases 3296-3445` on
the classic 1980s-90s AFP-surveillance deposits, e.g. `M19582`, `M19594`, the `AJ2485xx` India series)
— where the measured divergence sits close to the 15% wild threshold purely because the window is so
short that a handful of mismatches swings the percentage a long way: `AJ248523` reads 12.222% over 90
nt, six mismatches from the 15% line. This is not a new problem. It is the same population and the
same shape of trap already documented above in "the two that are a known, unfixable-by-sequence trap"
(`V01149.1`/`V01540.1`, where Sabin 1 *is* attenuated Mahoney and divergence alone cannot separate the
wild parent from its own vaccine derivative) and in the pre-fallback "lowering the VP1 floor" finding
that a no-floor VP1 call at ~90 nt gets **72 right and 33 wrong** — a coin weighted toward the answer,
not a threshold. MAD-VDPV's own 2026-06-26 locked review of this exact discordance class reached the
same conclusion by a different route: "short VP1 fragments (30-100 cod, distance uninformative —
text stands)."

**Recommendation: do not build a `text == wild` override rule.** It would resolve these 44 records
by re-introducing exactly the short-window coin-flip this pipeline already rejected once, just gated
on the shipped label agreeing with the flip rather than on anything this pipeline itself measured.
The 44 are better treated the same way `V01149.1`/`V01540.1` already are — a known, sequence-cannot-
decide population, closeable by individual or grouped ledger decisions if wanted, not by a rule that
would apply the same override logic to every future short fragment regardless of whether the paper
title is right.

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

## The 104 where a curated refinement or `wild` is the thing lost

| 2.4.1 ships | this pipeline emits | why | n |
|---|---|---|---:|
| `wild` | *(blank)* | too little usable sequence, by any basis, to measure or fall back over | 70 |
| `wild` | `VDPV` | divergence lands in the 1–15% band | 13 |
| `wild` | `Sabin-like` | divergence under 1% (includes `X70506`, the isolate-linked Mahoney trap) | 5 |
| `wild` | *(blank)* | partition undecided | 5 |
| `cVDPV` | `cVDPV-n` | **finer**: the depositor's `note` says `cVDPV2-n` | 5 |
| `iVDPV` | `wild` | divergence at or above 15% | 4 |
| `cVDPV` | `Sabin-like` | divergence under 1% | 2 |

Every one is a distinct accession, so 104 rows would close this subset (the 4 `chimera` records are
a separate mechanism, not this one, and are covered above); the full 666 is in the TSV, and the
categories above say which of them a ledger row is even the right instrument for. Five of the 104
are a gain rather than a loss (the `cVDPV-n` row). The `wild -> (blank)` row has fallen from 781
(before the capsid fallback) to 750 (after it) to 719 (after the 2026-07-31 decisions and the 50 nt
floor) to **70** (after the text fallback and isolate-linked inference) — the `cVDPV -> (blank)` row
that used to sit at 4 is gone entirely, closed by the `group_A_text_owned` decisions above.

The `cVDPV` and `iVDPV` rows that used to dominate this table are gone entirely: all 46 `iVDPV`
records stated immunodeficiency in their own record, and the 99 `cVDPV` records now trace to
decisions rather than to a coarsened band — 95 to the two published studies above, and 4 more
(`group_A_text_owned`) to unpublished GenBank submitter references. This pipeline now ships 1,761
`cVDPV`, 25 `cVDPV-n` and **205** `iVDPV`, against 2.4.1's 1,767, 20 and 203 — nearly the same totals
by a different route, with the two extra `iVDPV` being records whose `isolation_source` names an
immunodeficient host and which 2.4.1 left at `VDPV`.

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

What remains after the 2026-07-31/2026-08-01 work is `declined_too_little_sequence` (422 — 274
where 2.4.1 also declines under its own `unresolved_*` reason codes; 99 `group_B_sequence` records
neither the 50 nt floor nor a sibling link reaches, chiefly ones failing the chunked-homogeneity
guard below 180 nt; 45 `needs_other_data_text_fallback` and 4 `isolate_linked_inference` where
MAD-VDPV's own aligner or linkage reaches further than this pipeline's does), `declined_
membership_undecided` (153, needs the membership question settled first), `declined_no_serotype_
in_name` (33), `sequence_band_disagrees_with_release` (42, genuine threshold disagreements, now
including `X70506`) and the 4 `chimera` records above, which need a correctly validated
recombination rule rather than a decision.
