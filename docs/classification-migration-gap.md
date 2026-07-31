# Every `poliovirus_classification` difference from 2.4.1, accounted for

`poliovirus_classification` is the one column where a shipped value can encode a judgement that no
input in this clone contains. The distinction between `VDPV`, `cVDPV` and `iVDPV` is
**epidemiological** — ambiguous, circulating, or immunodeficient — and no property of a sequence
carries it. `wild` on a record with no VP1 is the same kind of claim.

Those calls are hard-won. They were made against published phylogenies and outbreak
investigations, and 1,506 of the ledger's active rows already cite a PMID for exactly this reason.
**A coarsened value is a lost judgement, not a conservative one**, and this file names precisely
which ones are still lost so they can be migrated rather than rediscovered.

`docs/classification-migration-gap.tsv` is the machine-readable list — **all 2,159 differing
records**, one row each, with the value 2.4.1 ships, the value this pipeline emits, the
`unresolved_reason` if it declined, and a category. Every row has a category; the count of
uncategorised rows is asserted to be zero, because "we looked at the big buckets" is how a residue
of unexplained differences survives a review.

An earlier version of this file covered only the 1,161 rows where 2.4.1 ships a *refinement* or
`wild`. That was the interesting subset, not the whole difference, and scoping a reconciliation to
the interesting subset is how the remaining 998 would have gone unnoticed.

## All 2,159, by category

| category | n | what it means |
|---|---:|---|
| `declined_too_little_vp1` | 1,557 | under 300 nt of VP1 to measure divergence over |
| `coarsened_attribution_not_in_sequence` | 348 | `cVDPV`/`iVDPV` → `VDPV`: the epidemiology is not in the sequence |
| `declined_membership_undecided` | 153 | organism name cannot settle poliovirus membership |
| `declined_no_serotype_in_name` | 33 | no serotype in the organism name to pick a Sabin reference |
| `sequence_band_disagrees_with_release` | 31 | both resolved, VP1 divergence lands in a different band |
| `shipped_class_outside_sequence_reach` | 24 | shipped `engineered/lab`, `chimera`, `vaccine`, `unresolved` — claims about construction or provenance, not distance |
| `curated_refinement_vs_sequence_band` | 6 | shipped a refinement, we emit a band that is not `VDPV` |
| `declined_ledger_value_out_of_vocabulary` | 3 | an active decision asserts a value outside the controlled list |
| `ledger_refines_beyond_the_release` | 3 | the ledger is *finer* than 2.4.1 |
| `record_text_refines_beyond_the_release` | 1 | `PP481414.1`: the record text says `aVDPV`, 2.4.1 ships `VDPV` |

The last two categories are worth noticing: on four records this pipeline is **more** specific than
the release, not less. A reconciliation that only counted losses would have reported them as noise.

### Membership is fully understood, and it is a cleaner story

`virus_group` and `curation_status` differ on 1,588 shared rows each, and **every single one is a
decline** — `organism_name_does_not_determine_membership`, and `follows_unresolved_virus_group`
downstream of it. There is not one row where this pipeline asserts a membership that contradicts
2.4.1. 1,435 of them the release calls `non_polio_enterovirus` and 153 `poliovirus`.

## What is already recovered, and how

Nothing here should be migrated twice. Two mechanisms already carry curated classifications:

1. **The ledger's `classification` / `verified_classification` rows** — 2,066 of them. R-CLASS-2
   emits these outright, ahead of any sequence evidence.
2. **The membership entailment** (`derive/partition.py`). A curated classification value comes from
   a poliovirus-only vocabulary, so asserting it asserts poliovirus membership. This recovered **259
   calls** that an earlier ordering discarded: their organism names are `Enterovirus C` or
   `Enterovirus coxsackiepol`, the partition declined on that, and the classification then declined
   for "following" the partition — throwing away a paper-based judgement because a *weaker* signal
   was silent. All 259 ship as `poliovirus`/`vouched` in 2.4.1.

## The 1,161 where a curated refinement or `wild` is the thing lost

| 2.4.1 ships | this pipeline emits | why | n |
|---|---|---|---:|
| `wild` | *(blank)* | under 300 nt of VP1 to measure over | 781 |
| `cVDPV` | `VDPV` | transmission attribution is not in the sequence | 302 |
| `iVDPV` | `VDPV` | immunodeficiency is not in the sequence | 46 |
| `wild` | `VDPV` | VP1 divergence lands in the 1–15% band | 13 |
| `wild` | *(blank)* | partition undecided | 5 |
| `wild` | `Sabin-like` | VP1 divergence under 1% | 4 |
| `cVDPV` | *(blank)* | under 300 nt of VP1 | 4 |
| `iVDPV` | `wild` | VP1 divergence at or above 15% | 4 |
| `cVDPV` | `Sabin-like` | VP1 divergence under 1% | 2 |

Every one is a distinct accession, so 1,161 ledger rows would close this subset; the
full 2,159 is in the TSV, and the categories above say which of them a ledger row is even
the right instrument for.

### Lowering the VP1 floor does not help — measured

`MIN_VP1_NT = 300` is this pipeline's own measurement-quality floor, not a published parameter, so
it was fair to ask whether relaxing it would recover the 785 blocked by it. Measured with the floor
removed entirely:

* **680 of the 785 have no VP1 overlap at all.** No threshold reaches them. They are 5′UTR, VP4/VP2
  or 3D fragments, and the question is not how confidently VP1 is measured but whether VP1 is
  present.
* Of the 105 that do overlap, the median window is **90 nt**. A no-floor call gets **72 right and 33
  wrong** — 25 would ship `VDPV` and 8 `Sabin-like` against a shipped `wild`.

69% is not a threshold, it is a coin weighted toward the answer. The floor stays at 300 and these
records stay declined, which is the same reasoning that keeps `sequence_scope` pending rather than
fitted to 86.7%.

### The four that are a known, unfixable-by-sequence trap

`wild → Sabin-like` includes **V01149.1 (Mahoney)** and **V01540.1**. Sabin 1 *is* attenuated
Mahoney — about 1% divergent across VP1 — so VP1 distance to Sabin cannot separate the wild parent
from its own vaccine derivative. No parameter choice fixes this; it needs the ledger.

## How to migrate

The path is the documented one in [`registry/README.md`](../registry/README.md#migration), and its
one hard rule applies here too: extract the private registries **at the release's own build commit**,
never at the private tip, because curation continues there and a tip migration silently absorbs rows
that belong to a later release.

```bash
rm -rf /tmp/evgc-registries && mkdir -p /tmp/evgc-registries
git -C ../MAD-VDPV archive <release-build-commit> data/genbank/working \
  | tar -x -C /tmp/evgc-registries --strip-components=3
```

What to look for once extracted: none of the 1,161 accessions carries a `classification` row in any
of the twelve registries the current migration reads, so the calls live either in a registry file not
yet in `SOURCES` or in a derived working table rather than a decision registry. Which of those it is
determines whether this is a migration or a curation task, and it is the first thing to establish —
if it is a derived table, the provenance question is what evidence stands behind each row, and a
row without an `evidence_reference` is exactly the D2 failure this ledger exists to prevent.

Do not synthesise these values. A `cVDPV` written without the phylogeny that established it is
indistinguishable in the artifact from one that was earned, which would make the whole column
untrustworthy rather than merely incomplete.
