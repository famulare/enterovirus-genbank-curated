# D2 re-adjudication under the simplified `engineered` definition

**Status: proposal only. Nothing decided, nothing modified.** No file in
`enterovirus-genbank-curated` or the private curation repository was changed. Every disposition below is a
recommendation for the curator to accept, modify or reject.

**Governing definition (curator, verbatim):**

> "the column should just be simplified to engineered. Engineered means someone assembled that
> specific genotype for some purpose and it is not a genotype that occurred in nature. Other
> genotypes associated with engineered projects that are in replicate of naturally occurring
> references or etc. etc. should get the label that belongs to that reference."

Operative test: **(a) did someone assemble this specific genotype, and (b) is it a genotype that
did not occur in nature?** Both must hold. A re-deposit / clone / replicate of an existing
reference genotype fails (b) and takes the reference's label.

---

## 0. Method, tooling, and what I did not verify

**Tooling.** All searching used `command grep` (BSD grep; no `-P`, so `-E` where needed), never the
`ugrep --ignore-files` shim. Data work used
this repository's `.venv/bin/python` reading
`final/source/normalized_tsv/*.tsv.gz` and `final/canonical/*.gz` directly.

**Alignment method.** Biopython `PairwiseAligner`, `mode='global'`, match `+1`, mismatch `-2`,
gap open `-10`, extend `-0.5`, **both end-gap scores 0** (end-gap-free, so a fragment aligns inside
a genome without terminal-gap penalty). I then trim all columns where either sequence is in a
terminal gap and report:

- `mismatch` = columns where both sides have a base and they differ,
- `internal_gap_cols` = columns inside the trimmed overlap with a gap on either side,
- **denominator = trimmed aligned overlap columns** (not the shorter sequence's length, not the
  longer's). Gaps are reported separately and are *not* in the mismatch numerator.

This is a raw p-distance over the overlap, consistent with the project's `raw_pdist_nt()`
convention. Where a record is a verbatim excerpt I also ran an exact `str.find()` substring test,
which is assumption-free and stronger than any alignment.

**Population screen.** For all 506 canonical PAT records I built a hashed-subsample k-mer index
(k=21, keep-if `hash(kmer) % 24 == 0`) over all 24,040 non-PAT canonical records, took the
best-matching non-PAT record per PAT record, then re-measured that pair by full alignment. This is
a *screen*: it can miss a true nearest neighbour, so distances are upper bounds on divergence to the
true nearest relative. 80 short records (mostly 15–60 nt primers) shared no sampled k-mer and are
unmeasured.

**What I verified independently:** every number in the D2 rationale, the CS406433 substring claim,
the "506 PAT all TRUE" claim, the ledger contents, the shipped values, and the code path (via a
read-only subagent sweep). Two independent confirmations of the 506/all-TRUE join.

**What I did NOT verify:** I made **no live network fetch**. I did not open patent WO2006042156,
patent US 12090197 B2, or Burns et al. 2006 (PMID 16537593). All patent/paper attribution below
comes from the `references` table inside the shipped source layer — i.e. from GenBank's own
metadata, not from the primary documents. `docs/review-backlog.md:432-438` states a previous review
verified the patent and PMID live; I am relying on that record, not on my own fetch. **Any claim
about what the patent or paper *says* is therefore second-hand and should be re-checked before it
is written into a `reason` field.** My restriction-site interpretation (§5) is inference from
sequence, not a citation.

---

## 1. The records — established facts

All five originally-implicated records are **Poliovirus 2** (taxid 12083). MEF-1 is the PV2 wild
reference, so that is consistent.

| accession | definition | div | `mol_type` | len | other source quals |
|---|---|---|---|---|---|
| CS406433 | Sequence **3** from Patent WO2006042156 | PAT | `unassigned DNA` | 2745 | — (partial CDS, `protein_id=CAL40863.1`) |
| CS406436 | Sequence **6** from Patent WO2006042156 | PAT | `unassigned DNA` | 6621 | — (CDS, `protein_id=CAL40864.1`) |
| CS406482 | Sequence **52** from Patent WO2006042156 | PAT | `unassigned DNA` | 7439 | none |
| CS406483 | Sequence **53** from Patent WO2006042156 | PAT | `unassigned DNA` | 7439 | none |
| DQ205099 | Human poliovirus 2 **clone S2R9**, complete genome | VRL | `genomic RNA` | 7439 | `/clone=S2R9`, `/note=infectious clone` |

The `mol_type` asymmetry the review flagged is confirmed exactly as stated.

**Shipped values (`final/canonical/sequence_metadata.tsv.gz`):**

| accession | `poliovirus_classification` | `sample_origin` | `surveillance_stream` | `engineered_or_construct` | `sequence_scope` |
|---|---|---|---|---|---|
| CS406433 | `Sabin-like` | `non-human` | `engineered/lab` | **TRUE** | other_fragment |
| CS406436 | `wild` | `human` | `vaccine/reference` | **TRUE** | other_fragment |
| CS406482 | `wild` | `human` | `vaccine/reference` | **TRUE** | complete_genome |
| CS406483 | `wild` | `human` | `vaccine/reference` | **TRUE** | complete_genome |
| DQ205099 | `Sabin-like` | `non-human` | `engineered/lab` | **TRUE** | complete_genome |

**Parent references, for "the label that belongs to that reference":**

| reference | `poliovirus_classification` | `sample_origin` | `surveillance_stream` | `engineered_or_construct` |
|---|---|---|---|---|
| AY184220 Sabin 2 | `Sabin` | `vaccine` | `vaccine/reference` | FALSE |
| AY238473 MEF-1 | `wild` | `human` | `vaccine/reference` | FALSE |

### 1a. A fourth finding the adversarial review did not name: D2 is not in force

The three D2 rows are `status=active` in `registry/decisions.tsv` asserting
`engineered_or_construct=FALSE`, **yet all three records ship `TRUE`.** This is not a precedence
bug — it is staleness. `final/canonical/` was written exactly once, in commit `82f2966`
(2026-07-29 **00:54**); the ledger was migrated in `ce1504b` (**07:57**) and the D2 rows carry
`source_artifact=curator_adjudication_2026-07-29`. `git log -- final/canonical` shows no later
commit. `docs/pipeline.md:116-128` documents this as a known pending delta, and
`src/enterovirus_genbank_curated/` contains **no** producer for this column at all — the public
package builds only the source layer.

Consequence for this adjudication: **no shipped value changes until `final/` is rebuilt**, so
correcting the ledger now is cheap and reversible. It also means the D2 trio's `classification=wild`
etc. *did* land (those came from `manual_review_overrides.csv`, which existed at build time), while
the `engineered_or_construct=FALSE` did not.

---

## 2. The population actually at risk — far larger than four

### 2a. Patent WO2006042156 contributes exactly four records, and CS406433 is one

Confirmed: `command grep`-equivalent scan of all 25,727 source records for `WO2006042156` in
`definition` returns exactly `{CS406433, CS406436, CS406482, CS406483}`. `CS406433` has **zero
rows in the ledger** (verified: 0 matches in `registry/decisions.tsv`) and ships `TRUE`. The
review's boundary complaint is correct.

`CS406433` also fell through a *second*, independent net: the upstream C1 review universe required
`seq_length >= 6000` (`infer_genbank_metadata.py:899`), and CS406433 is 2,745 nt. Two reviews, two
different universe definitions, same record missed.

### 2b. The same four sequences are deposited a second time, and D2 would have missed all four

The 2024 US continuation **US 12090197 B2** deposits the identical quartet:

| 2006 (WO2006042156) | 2024 (US 12090197 B2) | seq no. | len | sha256 identical? |
|---|---|---|---|---|
| CS406433 | **PU749280** | 3 | 2745 | **yes** (`cd100cfa6478a8f1`) |
| CS406436 | **PU749305** | 6 | 6621 | **yes** (`58e272ca1106771c`) |
| CS406482 | **PU749297** | 52 | 7439 | **yes** (`7a0457fadb532677`) |
| CS406483 | **PU749298** | 53 | 7439 | **yes** (`9375f73394900bbb`) |

Byte-identical, matching `sequence_sha256`. And the ledger blind spot is mirrored precisely:
`PU749280` has **zero** ledger rows (exactly like CS406433); `PU749297/298/305` have the same five
C1 rows as their CS twins (`classification=wild`, `reference_label=MEF1`, …) but **not** the D2
`engineered_or_construct=FALSE`.

**So D2 as written, once built, would make four pairs of byte-identical sequences ship contradictory
`engineered_or_construct` values.** That is a hard internal inconsistency, and it is testable.

The affected patent-family population is therefore **8 records, not 3**.

### 2c. Repo-wide: identical sequences already disagree

24,546 canonical rows collapse to 20,495 distinct sequences (release 2.1.5; 24,301 → 20,291 at 2.3.0). **12 identical-sequence groups already
disagree on `engineered_or_construct`**, and in every case the PAT member says TRUE while the
non-PAT member says FALSE. These include verbatim copies of the vaccine and wild references:

| PAT record (TRUE) | byte-identical to (FALSE) | that is |
|---|---|---|
| DD214220 | AY184219 (`Sabin`) | Sabin 1 |
| DD214222 | AY184220 (`Sabin`) | Sabin 2 |
| DD214224 | AY184221 (`Sabin`) | Sabin 3 |
| DD214223 | X00596 (`Sabin`) | Sabin 3 (Leon 12a1b) |
| DD214221 | X00595 (`Sabin`) | Sabin (see Q6 — has an explicit human TRUE) |
| DD214218 | K01392 (`wild`) | Leon/37 |
| DD214216, DI499146, FV537074, HC025129, HV932178, JC013103, LY501106, LZ216101 | NC_002058 / V01149 (`wild`) | Mahoney |
| DD214217 | M12197 (`wild`) | — |
| DD214219, DI499147, HV202313, JC013104 | V01150 (`Sabin`) | Sabin 1 |
| PE314016, PH149759 | AF111984 (`wild`) | — |
| HW349523, LP131905, MA783942, MP510547 | AF499636 | — |
| A09260 | 234 VRL records (`Sabin`/`Sabin-like`) | — |

**26 of the 506 PAT records are byte-identical to at least one non-PAT record**, and all 26 ship
TRUE against a FALSE twin.

### 2d. The measured PAT population: 367 of 506 are re-deposits

| bucket | n | length profile |
|---|---|---|
| **A** exact substring of, or zero-mismatch/zero-gap against, a non-PAT record | **358** | 45 ≥900 nt (31 ≥3000 nt); 278 in 200–899; 35 <200 |
| **B** ≤0.1% divergent | **9** | all ≥6621 nt |
| **C** 0.1–1% divergent | 35 | 16 in 200–899, 9 in 900–2999, 7 ≥3000 |
| **D** >1% divergent | 23 | 21 are <200 nt (median 70); only PI448373/PL188417 (746 nt, 1.64%) are longer |
| **E** unmeasured (overlap 0) | 1 | FV537075, 7440 nt |
| — no shared sampled k-mer (screen limit) | 80 | 15–60 nt primers, plus 2×629 and 2×7440 |

**A+B = 367 of 506 (72.5%).** In every one of the 426 measured cases the nearest non-PAT neighbour
ships `engineered_or_construct=FALSE`. Note the shape: essentially **no long PAT record is
genuinely divergent** — the >1% bucket is almost entirely short oligos. The genuinely engineered
polio constructs in this database live in `SYN`/`VRL` (nOPV2-CD `MN654096`, the S19 set
`PP068131-136`, DI-particle records), not in PAT.

### 2e. 27 records the curator has *already* adjudicated as re-deposits still ship TRUE

36 accessions carry ledger rows whose `reason` says "non-canonical … reference re-deposit". The 9
that are VRL ship FALSE. **All 27 that are PAT ship TRUE** — including `LY501110`/`LZ216105`
(reason: "0nt/7439 vs Sabin 2") and `LY501109`/`LZ216104` ("0nt/7441 vs Sabin 1"). C1 relabelled
`classification`/`origin_class`/`sampling_frame`/`reference_label` but **`engineered_or_construct`
was not a column in `c1_construct_reference_resolution.csv` at all**, so the flag was never touched.

This is the cleanest, highest-confidence remediation set, because the scientific judgment is
already the curator's own:

```
AX348183 CS406436 CS406482 CS406483 DI499146 DI499147 E01570 E01571 E01572
FV537074 JC013103 JC013104 LY501104 LY501105 LY501106 LY501108 LY501109 LY501110
LZ216099 LZ216100 LZ216101 LZ216103 LZ216104 LZ216105 PU749297 PU749298 PU749305
```

### 2f. Non-PAT clone/construct records — and the DQ205099 rule was never in force

- 110 canonical records carry a source `/clone` qualifier: **107 FALSE, 3 TRUE.**
- `/note=infectious clone` appears on **9** records: `DQ205099` (TRUE), `MN654096` (TRUE, nOPV2-CD
  — genuinely engineered), and **`MN781627`–`MN781633` (7 records, all FALSE).**

So the shipped table **already** does not apply "an infectious cDNA clone is a construct" as a
rule. DQ205099's TRUE is an outlier against 107/110 clone records and against 7 other records
carrying the identical `/note`. The rationale was never a rule; it was a one-record justification.

---

## 3. Measurements

Exact substring test (assumption-free):

| record | result |
|---|---|
| **CS406433** | **exact substring of Sabin 2 AY184220 at 0-based `[639:3384]`** (1-based 640–3384), 2745 nt, **0 mismatches** |
| **PU749280** | identical result (byte-identical to CS406433) |
| CS406436/482/483, DQ205099 | no exact substring in the reference panel |

The review's `AY184220[640:3384]` is right; 640 is the 1-based start (0-based 639). This span is
108 nt of 5'UTR plus the complete P1 capsid (Sabin 2 CDS starts at 748; 748–3384 = 2637 nt = 879
codons), i.e. **the entire parental capsid cassette**, as claimed.

End-gap-free alignment, mismatches / aligned overlap (best parent only; all reproduce D2 exactly):

| record | parent | mismatches | overlap | p-dist |
|---|---|---|---|---|
| CS406436 | AY238473 MEF-1 | 4 | 6621 | 0.060% |
| CS406482 | AY238473 MEF-1 | 4 | 7439 | 0.054% |
| CS406483 | AY238473 MEF-1 | **6** | 7439 | 0.081% |
| DQ205099 | AY184220 Sabin 2 | 3 | 7439 | 0.040% |
| CS406433 | AY184220 Sabin 2 | 0 | 2745 | 0.000% |

Next-nearest parent for every one of these is ≥16.8% away, so parentage is unambiguous.

**Independent corroboration that the MEF-1 4-nt signature is lab-stock lineage, not engineering.**
`CS406436/482/483` and `PU749297/298/305` all share exactly `T2580C, C2781T, T3685C, T6805C`
relative to AY238473. So do `LY501105` and `LZ216100` — deposits from the **unrelated** CAVA
cold-adaptation patents (KR 1020170012566-A / JP 2017519506-A), which carry those same four plus
seven others. Four independent patent families sharing the same four deviations means **AY238473 is
the outlier deposit and this is the common MEF-1 laboratory stock.** Three of the four are
synonymous; one (`T3685C`) is non-synonymous (2A residue 99, Y→H). That is an ordinary lab-lineage
profile.

---

## 4. Applying the definition — per record

### 4a. CS406433 / PU749280 → NOT engineered; take Sabin 2's label

Test (a) "someone assembled this genotype": no — it is a verbatim, zero-mismatch excerpt of Sabin 2.
Test (b) "did not occur in nature": fails outright. This is the *most* clearly parental record of
the eight, and it is more clearly parental than the three D2 flipped.

Proposed values, mirroring the existing `LY501110`/`LZ216105` precedent (Sabin 2 patent re-deposits
already curated by the curator) — **four shipped values change on each record**:

| field | ships | proposed | rationale |
|---|---|---|---|
| `engineered_or_construct` | TRUE | **FALSE** | verbatim Sabin 2 excerpt |
| `poliovirus_classification` | `Sabin-like` | **`Sabin`** | Sabin 2's own label; `Sabin-like` implies a divergent field isolate |
| `sample_origin` | `non-human` | **`vaccine`** | Sabin 2 ships `vaccine` |
| `surveillance_stream` | `engineered/lab` | **`vaccine/reference`** | Sabin 2 ships `vaccine/reference` |
| `reference_label` | (none) | **`Sabin2`** | matches precedent |
| `canonical_reference` | (none) | **FALSE** | non-canonical re-deposit; AY184220 is canonical |

### 4b. CS406436 / PU749305 and CS406482 / PU749297 → NOT engineered; MEF-1's label

4 nt / 6621 and 4 nt / 7439; signature independently shared with two unrelated patent families
(§3). No engineered site created (I checked all four positions for restriction-site gain; the hits
are only degenerate/frequent-cutter noise, nothing canonical or unique). **D2's conclusion is
correct for these four records** — though its *reasoning* was a non-sequitur, and the correct
reasoning is "shared lab-stock lineage confirmed across independent depositors", not "too few
substitutions for deoptimization".

Only `engineered_or_construct` changes (TRUE→FALSE); `wild`/`human`/`vaccine/reference` already
match MEF-1's label. **PU749305/PU749297 need the same rows as their CS twins.**

### 4c. CS406483 / PU749298 → **ENGINEERED. D2 got this one wrong.**

CS406483 = CS406482 + two extra changes, `G1773A` and `A1776G`. These are:

- both **synonymous**, both at **third codon position**, in **adjacent codons**,
- landing exactly at the **VP2/VP3 junction** (VP3 residues 1 and 2),
- converting MEF-1 `GGTT**G**CC**A**GT` → `GGTT**A**CC**G**GT`, which creates **AgeI (`ACCGGT`)**,
- **unique in the genome**: `ACCGGT` occurs 0× in MEF-1 and 0× in CS406482, exactly **1×** in
  CS406483,
- and the 13-nt context `GGTTACCGGTCTT` occurs in **exactly 2 of 24,546 records of release 2.1.5** — CS406483 and
  PU749298, i.e. the same patent sequence deposited twice. It is absent from every other MEF-1
  deposit including the independent CAVA ones.

Two synonymous third-position changes in adjacent codons, at a protein-domain boundary, creating a
unique canonical cloning site, present in Seq 53 but absent from the otherwise-identical Seq 52, is
the signature of a **deliberately engineered restriction site for cassette exchange**. Under the
curator's definition someone assembled that specific genotype for a purpose, and that genotype does
not occur in nature.

Proposed: `engineered_or_construct` **stays TRUE** for CS406483 and PU749298, with the reasoning
replaced. This means **D2 should be partially reversed**: the trio is not a trio. CS406436 and
CS406482 are parental; CS406483 is the engineered derivative.

*Counter-reading to carry:* two nucleotides is a thin basis, and I cannot exclude that Seq 53
simply came from a differently-passaged subclone. The AgeI coincidence is strong but is inference,
not a citation — the patent text would settle it and I did not read it. See Q2.

### 4d. DQ205099 → see §5. Proposed: **NOT engineered** (reverses the earlier disposition).

---

## 5. DQ205099 re-examined — the new definition reverses the earlier disposition

The old rationale was: `/clone=S2R9` + `/note=infectious clone`, therefore a construct, therefore
`engineered_or_construct=TRUE` stands. **That is exactly the reasoning the curator's simplification
removes** — the column no longer means "or construct-derived", and "someone made a clone of it" is
not the test. The test is whether the *genotype* did not occur in nature.

I attempted to rescue the TRUE call on better evidence, and the evidence went the other way.

All three differences from Sabin 2 are **synonymous, third-codon-position** (VP1 res 44, VP1 res
273, 3C res 66) — as `docs/review-backlog.md:435` already noted. Two of them create canonical unique
cloning sites, which initially looked decisive for "engineered":

- `A2616G` creates **EagI (`CGGCCG`)**, 0× in Sabin 2 → 1× in DQ205099
- `A3303T` creates **XhoI (`CTCGAG`)**, 0× in Sabin 2 → 1× in DQ205099
- `T5640A` creates only `AccX` (degenerate) — no canonical site

**But the natural-occurrence test refutes the engineered reading.** Searching all 24,546 records of release 2.1.5 for
the exact 13-nt context around each change:

| change | site | exact 13-mer context found in | verdict |
|---|---|---|---|
| `A2616G` | EagI | **45 records**, including many natural PV2 field isolates: cVDPV2 `JX275055/275177/275301/275373`, VDPV2 `AB467725`, `FJ436998`, `HM134108`, `OR365422`, Sabin-like `AB467812`, `JX274882`, plus coxsackiepol `PX000236`… | **occurs in nature** |
| `A3303T` | XhoI | **3 records**: DQ205099, **`JX275341` (natural cVDPV2, PV2 strain NIE1011688, Nigeria)**, and `MN654096` (nOPV2-CD, built on this backbone) | **occurs in nature** |
| `T5640A` | — | n/a | no site |
| *contrast:* CS406483 `G1773A+A1776G` | AgeI | **2 records** — CS406483 and its own byte-identical twin PU749298, nowhere else | **does not occur in nature** |

Both of DQ205099's putative markers are observed in independent natural field isolates. The
restriction sites are coincidental consequences of ordinary Sabin-2 lineage variation, not designed
features. (`MN654096` sharing both states is expected either way — nOPV2-CD was built on the S2R9
backbone by the same CDC group.)

So DQ205099's genotype is Sabin 2 to within 3 nt, and each of those 3 nt is separately attested in
nature. It is a replicate of a naturally occurring reference associated with an engineered project —
precisely the case the curator's second sentence assigns the reference's label.

**Plain answer: yes, the new definition reverses the earlier disposition.** Proposed values,
identical in shape to CS406433:

| field | ships | proposed |
|---|---|---|
| `engineered_or_construct` | TRUE | **FALSE** |
| `poliovirus_classification` | `Sabin-like` | **`Sabin`** |
| `sample_origin` | `non-human` | **`vaccine`** |
| `surveillance_stream` | `engineered/lab` | **`vaccine/reference`** |
| `reference_label` | (none) | **`Sabin2`** |

This also *removes* an existing undocumented contradiction: `D-76ece1bbec32` is `active` asserting
`classification=engineered` while canonical ships `Sabin-like` (backlog B33).

**The residual tension, stated honestly.** DQ205099 *is* a plasmid-derived infectious cDNA clone —
someone did assemble it, and no single natural record carries all three substitutions together. The
definition's clause (a) pulls toward TRUE; clause (b) pulls firmly toward FALSE. I propose FALSE
because clause (b) is the discriminating clause (clause (a) is true of every cloned sequence,
including all 107 `/clone` records that ship FALSE), and because the curator's second sentence
addresses this exact situation. But this is the one call in this document that turns on reading the
definition rather than on measurement. See Q1.

Two collateral corrections to the DQ205099 record, both already in the backlog and both confirmed by
the shipped `references` table: the patent (priority 2004-10-08, published 2006-04-20) **precedes**
the paper (J. Virol. April 2006), so "the parental control clone of the study the patent derives
from" is backwards (B33); and calling a Sabin-2 clone "the wild-type control" is hazardous in a
database where `wild` is a controlled value distinct from `Sabin` (B42) — the paper's word is
"unmodified".

---

## 6. What the definition does not settle — surfaced, not resolved

1. **Sabin strains are themselves lab-derived.** Sabin 1/2/3 were produced by deliberate serial
   passage to attenuate. "Occurred in nature" has to mean something like "arose as a replicating
   biological lineage rather than being assembled", not "existed before humans intervened" —
   otherwise Sabin, and every OPV-derived record in the database, is engineered. The proposals above
   assume the former. This boundary is load-bearing for ~10,000 records.
2. **Passage-derived vs assembled.** nOPV2 (`MN654096`) was designed then grown; cVDPVs arose by
   replication. Both are "not the parental genotype". The distinction the definition needs is
   *assembly*, not *novelty* — but then a serially-passaged cold-adapted mutant (CAVA) is not
   assembled either, while it is plainly an engineering product.
3. **Chimeras and recombinants.** Sabin/EV-C recombinants occur naturally and constantly
   (`recombinant_junction`, GH #8). Lab chimeras are assembled. The sequence signature can be
   similar. `poliovirus_classification=recombinant/lab` already exists as a separate value — does
   `engineered` also fire?
4. **Synthetic re-synthesis of a natural genotype.** If someone chemically synthesises Mahoney
   exactly, clause (a) holds and clause (b) fails. The definition as written says not engineered.
   Is that intended? (This is not hypothetical — de-novo poliovirus synthesis is published work.)
5. **Distance is not the test, and near-identity does not imply parental.** `LY501108`/`LZ216103`
   sit **1 nt** from Sabin 3 inside a cold-adaptation patent — that single nucleotide could be the
   entire claimed invention. `CS406483` sits 6 nt from MEF-1 and 2 of those 6 are, on my reading, the
   invention's cloning site. Meanwhile `CS406482` at 4 nt is parental. So a divergence threshold
   cannot implement this definition; the *character* of the differences has to be inspected.
6. **What "the label that belongs to that reference" means when the reference is a fragment or has no
   label.** 303 of the 358 exact-substring PAT records have a *blank* `poliovirus_classification`
   (they are non-polio enterovirus). Inheriting a blank is fine, but `sample_origin` and
   `surveillance_stream` still need values.
7. **Does the flag describe the sequence or the record's provenance?** A patent deposit of Sabin 2 is
   a real fact about a patent. If `engineered` becomes purely a property of the genotype, the
   "this came out of a patent filing" signal survives only in `surveillance_stream`. Flipping
   `surveillance_stream` from `engineered/lab` to `vaccine/reference` (as §4a proposes, following
   precedent) erases it. That may be a loss worth avoiding.

---

## 7. Proposed changes

### 7a. Column rename

Rename `engineered_or_construct` → **`engineered`**, and change the dictionary definition from
"Whether the record is engineered or construct-derived." to something like: *"Whether someone
assembled this specific genotype for a purpose and it is not a genotype that occurred in nature.
Re-deposits, clones and replicates of an existing reference genotype are FALSE and take that
reference's labels."* This is a breaking change to a shipped column name in
`final/canonical/sequence_metadata.tsv.gz`, `sequence_metadata_vouched.tsv.gz`,
`canonical_projection_provenance.tsv.gz` and `canonical_data_dictionary.tsv`. See Q7 on whether to
rename or keep the name and only redefine.

### 7b. Ledger changes

**Supersede** (reason: the mechanism refutation does not establish the conclusion, and the record is
split):

- `D-af2020a60681` (CS406436, FALSE) — re-assert FALSE on corrected reasoning
- `D-994cc6c2078f` (CS406482, FALSE) — re-assert FALSE on corrected reasoning
- `D-2bb2c3e9786e` (CS406483, FALSE) — **reversed to TRUE**
- `D-76ece1bbec32` (DQ205099, legacy `classification=engineered`, currently `active`) — supersede;
  the recorded mechanism is false *and* the label is now wrong

**Add** (new `source_artifact`, e.g. `curator_readjudication_2026-07-29`):

| accession | field | new_value | reason (proposed) |
|---|---|---|---|
| CS406436, CS406482 | `engineered` | FALSE | parental MEF-1 lab-stock deposit; the 4-nt signature `T2580C/C2781T/T3685C/T6805C` vs AY238473 is shared by the independent CAVA patent deposits LY501105/LZ216100, so it is lab-stock lineage, not engineering |
| PU749305, PU749297 | `engineered` | FALSE | byte-identical (sha256) to CS406436/CS406482 respectively; US 12090197 B2 re-deposit of the same patent sequences |
| CS406483, PU749298 | `engineered` | TRUE | engineered AgeI (`ACCGGT`) cloning site created by two synonymous third-position changes `G1773A/A1776G` at the VP2/VP3 junction; unique in the genome, absent from MEF-1, from CS406482 and from all other MEF-1 deposits; 13-mer context `GGTTACCGGTCTT` occurs in only these 2 of 24,546 records of release 2.1.5 |
| CS406433, PU749280 | `engineered` | FALSE | verbatim excerpt of Sabin 2 AY184220 1-based 640–3384 (0 mismatches / 2745 nt) = parental capsid cassette |
| CS406433, PU749280 | `classification` | `Sabin` | takes Sabin 2's label |
| CS406433, PU749280 | `origin_class` | `vaccine` | takes Sabin 2's label |
| CS406433, PU749280 | `sampling_frame` | `vaccine/reference` | takes Sabin 2's label |
| CS406433, PU749280 | `reference_label` | `Sabin2` | per LY501110/LZ216105 precedent |
| CS406433, PU749280 | `canonical_reference` | FALSE | non-canonical re-deposit |
| DQ205099 | `engineered` | FALSE | Sabin 2 re-deposit; 3 nt/7439 all synonymous third-position, and each state is attested in natural field isolates (A2616G in 45 records incl. cVDPV2 JX275055/JX275177; A3303T in cVDPV2 JX275341) — lineage variation, not engineered markers |
| DQ205099 | `classification` | `Sabin` | takes Sabin 2's label |
| DQ205099 | `origin_class` | `vaccine` | takes Sabin 2's label |
| DQ205099 | `sampling_frame` | `vaccine/reference` | takes Sabin 2's label |
| DQ205099 | `reference_label` | `Sabin2` | — |
| the other 23 of the §2e set | `engineered` | FALSE | already curated as non-canonical reference re-deposits; `engineered_or_construct` was absent from `c1_construct_reference_resolution.csv` so the flag was never updated |

`evidence_reference`: a new measurement note, since `c1_construct_reference_resolution.md` does not
contain CS406433/PU749280 and its 7,435 denominators are wrong for CS406436 (backlog B25).

Row-count impact: the ledger's pinned `2756` and `EXPECTED_STATUS = {active: 2736, retired: 17,
superseded: 3}` both move, as does `contracts.py: EXPECTED_BASELINE_COUNTS["manual_decisions"] =
2753`.

### 7c. Rule change

`R-CONSTRUCT-1` is **not** what the review (or I) initially assumed. It is a **1:1 pass-through
projection** in the private repo (the private repository’s `data/genbank/working/build_release_v2.py:195`):
`ProjectionSpec("engineered_or_construct", "engineered_or_construct", "R-CONSTRUCT-1", …)`. The
string `R-CONSTRUCT-1` does not appear in `enterovirus-genbank-curated` source at all — only inside
shipped compressed data. So **changing R-CONSTRUCT-1 fixes nothing.**

The real predicate is the private repository’s `data/genbank/working/infer_genbank_metadata.py:898`:

```python
engineered_or_construct = bool(construct) and not real_human_capture(row)
```

where `construct = search_any(CONSTRUCT_PATTERNS, blob(row))` and `blob()` concatenates 20 text
fields **including `division`**. `CONSTRUCT_PATTERNS` (`:409-428`) contains `r"\bPAT\b"`,
`r"\bpatent\b"`, `r"\bclone\b"`, `r"\bmutant\b"`, `r"\boligo(?:nucleotide)?\b"`, `r"\bvector\b"`,
`r"\bplasmid\b"`, … all case-insensitive.

This is the defect. `division=PAT` sets the flag by an **incidental case-insensitive substring hit
on a concatenated text blob** — not a structured field test, and not a claim about the genotype.
`\bclone\b` is how DQ205099 became TRUE. This predicate cannot implement the curator's definition,
because "was deposited in a patent" and "somebody assembled this genotype" are different
propositions, and the measurement in §2d shows they disagree for at least 367 of 506 PAT records.

Proposed direction (needs curator sign-off — Q4): the flag should default **FALSE** and be set TRUE
only by (i) explicit curation, or (ii) a narrow, structured signal such as
`organism`/taxonomy = synthetic construct, or `division=SYN`. Patent deposition should express
itself in `surveillance_stream`, which already has a *structured* PAT test
(`infer_sampling_frame:727`), not in `engineered`. Removing `\bPAT\b`, `\bpatent\b`, `\bclone\b`,
`\bmutant\b` and `\boligo\b` from `CONSTRUCT_PATTERNS` would flip on the order of 500 records; that
should be done as a measured, gate-diffed change, not a patch.

Also worth noting as a latent hazard: the `real_human_capture()` veto (`:540-570`) forces FALSE
whenever `collection_date` merely parses. So the current flag is partly a function of metadata
completeness.

### 7d. Tests that must change

In `tests/test_legacy_registry.py`, four tests take their universe from
`engineered_accessions(legacy_dir)` — the set of rows in
`registry/legacy/legacy_accession_classification_overrides.csv` with `classification == "engineered"`.
That file has exactly 4 such rows and **CS406433 is not among them**, so no change to CS406433's
data can turn these red. This is R4 in the backlog, and it is structural, not incidental:

- `test_the_legacy_file_asserts_engineered_for_four_accessions` (`:146`) — hard-codes the 4-member
  set; actively cements the wrong denominator.
- `test_only_three_of_the_four_engineered_calls_are_patent_deposits` (`:159`) — reads the full
  shipped `records.tsv.gz`, then filters through the legacy CSV at `:174-178`, discarding 25,723 of
  25,727 rows **including CS406433, which is right there with `division=PAT` and
  `definition="Sequence 3 from Patent WO2006042156"`**. Its assertion
  `patent == {"CS406436","CS406482","CS406483"}` reads as "the patent deposits are exactly these
  three" but only means "of the four rows the 2015 CSV named, three are PAT".
- `test_the_fourth_engineered_call_is_annotated_and_still_active` (`:211`) — pins DQ205099 to
  `status=active`, `new_value=engineered`, and requires the phrase
  `"engineered_or_construct=TRUE stands"` in `notes`. **Reversing DQ205099 breaks this test by
  design.**
- `test_dq205099_is_the_only_ledger_decision_for_its_subject` (`:318`) — asserts exactly one
  decision for DQ205099; adding rows breaks it.
- `test_the_stated_divergences_are_recomputable_from_the_shipped_sequences` (`:237`) — genuinely
  realigns sequences, but from a literal `wanted` set and a literal `expected` list of 4 tuples.
  **CS406433 belongs here** (0 mismatches / 2745 nt vs AY184220), as do PU749280/297/298/305.

The fix is to change what these tests are *about*: derive the universe from a property of the data —
records whose `definition` matches `Patent WO2006042156|US 12090197`, or records shipping
`engineered=TRUE`, or `division=PAT` — rather than from a 2015 CSV. Also add: **an invariant that
byte-identical sequences (`sequence_sha256`) may not disagree on `engineered`**, which would have
caught both the CS/PU contradiction and the 12 groups in §2c automatically.

Also affected: `tests/test_decision_ledger.py` (`D2_ADDITIONS`, `EXPECTED_STATUS`, `rows == 2756`,
the superseded-subject set at `:141`, the `curator_adjudication_2026-07-29` count at `:354`),
`tests/test_migration_legacy.py` (`len(superseded) == 3`, `len(added) == 3`, the
`"engineered_or_construct=TRUE stands"` phrase pin at `:307`, `D2_ACCESSIONS`), and
`scripts/migrate_legacy_registries.py` (`D2_ACCESSIONS`, `EXPECTED_BASELINE_DECISIONS = 2753`,
`apply_dq205099_annotation`). **Nothing anywhere currently pins a count of `engineered=TRUE`
records** — the 543/506 numbers are unpinned, which is why this drifted silently.

Note one ledger-invariant gap: the uniqueness test keys on `(subject_key, field_name)`, so a
`classification` row and an `engineered_or_construct` row for the same accession can contradict each
other invisibly. That is the shape of the live DQ205099 problem.

---

## 8. Questions for Mike — numbered, most consequential first

**Q1. Is an infectious cDNA clone of a natural strain `engineered`?**
Everything about DQ205099 turns on this, and so do ~110 `/clone` records. Clause (a) of your
definition (someone assembled it) says TRUE; clause (b) (genotype occurred in nature) says FALSE.
The shipped table currently answers FALSE 107 times out of 110 and TRUE once — DQ205099.
*If clause (b) governs (my proposal):* DQ205099 → FALSE + Sabin 2's labels; the earlier disposition
is reversed; the table becomes self-consistent.
*If clause (a) governs:* DQ205099 stays TRUE, but then `MN781627`–`MN781633` (also
`/note=infectious clone`) and much of the `/clone` set must flip TRUE, and "engineered" becomes a
statement about how a sequence was obtained rather than about the genotype. I'd want that said
explicitly in the dictionary.

**Q2. Do you accept the AgeI evidence splitting CS406483 from CS406482 — reversing part of D2?**
CS406483/PU749298 gain a unique AgeI site from two synonymous third-position changes at the VP2/VP3
junction, found in only those 2 of 24,546 records of release 2.1.5. I read that as a designed cloning site → TRUE.
It is 2 nucleotides and an inference; the patent text would settle it and I did not read it.
*If you accept:* D2 becomes "two parental, one engineered", and CS406483 keeps TRUE with new
reasoning. *If you'd rather not split on 2 nt:* all six MEF-1-family records go FALSE uniformly,
which is simpler and defensible, but knowingly labels a probable construct as parental. *Third
option:* hold CS406483 pending a read of the patent's sequence listing.

**Q3. How wide should this go — the 4, the 8, the 29, or the 367?**
These are nested and I can defend any of them, but they have very different blast radii.
(a) *8*: the WO2006042156 + US 12090197 quartets. Fixes the named defect and the byte-identical
contradiction.
(b) *29*: (a) plus the 27 records you have **already** adjudicated as non-canonical reference
re-deposits that still ship TRUE only because `engineered_or_construct` wasn't a column in the C1
CSV. This is the set where the judgment is already yours; I'd recommend at least this.
(c) *367*: every PAT record measured as an exact-substring or ≤0.1% re-deposit. Correct under the
definition, but this is a rule change, not a ledger change, and needs a gated rebuild + diff.
My recommendation: do (b) as ledger rows now, and schedule (c) as the `CONSTRUCT_PATTERNS` fix.

**Q4. Do I have your approval to propose editing `CONSTRUCT_PATTERNS` in the private repo?**
The `\bPAT\b` / `\bpatent\b` / `\bclone\b` / `\bmutant\b` / `\boligo\b` patterns are the actual
cause; `R-CONSTRUCT-1` is only a pass-through and changing it does nothing. But that file is in
the private curation repository, which is read-only reference for this task, and the change moves ~500
shipped values. I have made no change and will not without your word. Also: do you want patent
provenance to survive somewhere explicit once `engineered` stops encoding it (see Q8)?

**Q5. Sabin as "occurred in nature" — confirm the boundary.**
I assumed Sabin 1/2/3 count as naturally-occurring lineages (they are passage-attenuated, not
assembled), so a Sabin re-deposit is FALSE and takes `Sabin`. If instead deliberate attenuation
counts as assembly, Sabin and every OPV-derived record becomes engineered and ~10,000 records are
affected. I'm confident you mean the former but it should be written down, because it is the
load-bearing premise for most of §4.

**Q6. `DD214221` — your own earlier explicit TRUE conflicts with the new definition.**
It has an `active` human `engineered_or_construct=TRUE` from `manual_review_overrides.csv`, yet it
is **byte-identical** to `X00595`, which ships `Sabin`/FALSE. Same for `DD214215` (7 nt/7440 from
Mahoney NC_002058, explicit TRUE, from a defective-interfering-particle patent — the *sequence*
looks like the parental Mahoney plasmid, not a DI construct). Under the new definition both flip
FALSE. Do you want them flipped, or is there context behind those calls that the sequence doesn't
show? I did not touch them.

**Q7. Rename the column, or keep the name and only change the definition?**
Renaming `engineered_or_construct` → `engineered` is a breaking change to a shipped column name in
four artifacts plus the dictionary and every consumer. Keeping the name while redefining it is
non-breaking but leaves a name that says "or construct-derived" when the semantics no longer do.
I lean rename, with the old name recorded in the dictionary as a former alias — but it's your call
on public-interface churn.

**Q8. Should `surveillance_stream` still say `engineered/lab` for a Sabin re-deposit found in a
patent?** My §4a/§5 proposals follow your existing `LY501110`/`LZ216105` precedent and set
`vaccine/reference`, which erases the "this came from a patent filing" signal from the canonical
table (it survives only in `division` in the source layer). Alternative: keep
`surveillance_stream=engineered/lab` (it is a true statement about the *record*) and let `engineered`
alone carry the genotype claim. That would make CS406433 inconsistent with LY501110, so it needs a
deliberate choice.

**Q9. Two `E01571`-shaped cases I did not resolve.** `LY501105`/`LZ216100` are curated as MEF-1
re-deposits (`classification=wild`) but carry 7 changes beyond the shared MEF-1 lab-stock signature
— those 7 could be the CAVA cold-adaptation invention, which would make them engineered. Likewise
`LY501108`/`LZ216103` sit 1 nt from Sabin 3 in the same patent family, and you already curated that
1 nt as lineage. Do you want me to characterise those extra changes (synonymy, clustering,
attestation in nature) the way I did for CS406483, before anything in the §2e set is flipped?

**Q10. Should I add the byte-identical-sequence invariant as a test?**
A check that records sharing a `sequence_sha256` may not disagree on `engineered` would have caught
the CS/PU contradiction, the 12 groups in §2c, and would prevent the next per-accession adjudication
from creating the same class of defect. Cheap, and it fails loudly on exactly the mistake that made
this re-adjudication necessary. It would currently fail on 12 groups, so it needs the §2e/§2d work
landed first — or an explicit allowlist of known-pending groups.
