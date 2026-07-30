# Full-population re-adjudication of `engineered_or_construct` — all 58 records ≥3000 nt

**Status: proposal and evidence only. Nothing decided, nothing modified.** No file in
`enterovirus-genbank-curated` or the private curation repository was changed by this work. Every disposition below is a
recommendation for the curator to accept, modify or reject.

Continues `docs/engineered-readjudication.md` (the "D2 report"), extending its method from 8 named
records to the exhaustive population currently shipping `engineered_or_construct=TRUE` at
`sequence_length_nt >= 3000`.

**Governing definition (curator, verbatim — final, not re-litigated here):**

> "the column should just be simplified to engineered. Engineered means someone assembled that
> specific genotype for some purpose and it is not a genotype that occurred in nature. Other
> genotypes associated with engineered projects that are in replicate of naturally occurring
> references or etc. etc. should get the label that belongs to that reference."

Operative test: **(a) did someone assemble this specific genotype, and (b) is it a genotype that did
not occur in nature?** Both must hold for TRUE.

> **SUPERSEDED IN PART — read [Appendix B](#appendix-b-curator-answers-2026-07-29--decided) before
> acting on any number in this report.** The curator answered all ten §9 questions on 2026-07-29 and
> revised the operative test above: **directed selection under an applied selective pressure now
> counts as engineered**, not only physical assembly. That reverses `LY501107`/`LZ216102`, and the
> §4 disposition table is wrong for those two rows. Appendix B also carves `FV537075`–`FV537077` out
> of `final/` entirely rather than shipping them TRUE, and leaves `LY501105`/`LZ216100` **undecided**.
> Body-text totals below are the pre-Appendix-B figures and are retained as the record of what the
> evidence alone supported.

**Headline (as revised by Appendix B): of the 58, 42 flip FALSE, 14 stay TRUE, and 2 are open.**
The pre-revision figure was 46 FALSE / 12 TRUE. The set that actually lands is **42 + `A09260`
= 43 records**, because the two open records (`LY501105`/`LZ216100`) are not being implemented in
either direction until the curator rules. The records that stay TRUE are not the ones the prior
report guessed at.

---

## 0. Method, tooling, and what I did not verify

**Tooling.** All shell searching used `command grep` (BSD grep; `-E` where alternation was needed),
never the `ugrep --ignore-files` shim. All data work used
this repository's `.venv/bin/python` (Biopython 1.87; pandas
is **not** installed in that venv, so everything is `gzip` + `csv` + stdlib) reading
`final/canonical/sequence_metadata.tsv.gz`, `final/canonical/sequences.fasta.gz` and
`final/source/normalized_tsv/records.tsv.gz` directly.

**Alignment method** — identical to the prior report, and it reproduces every number that report
published. Biopython `PairwiseAligner`, `mode='global'`, match `+1`, mismatch `-2`, gap open `-10`,
extend `-0.5`, **both end-gap scores 0**. Columns where either sequence sits in a terminal gap are
trimmed; `mismatch` counts columns where both sides have a base and differ; the denominator is the
trimmed aligned overlap; internal gaps are reported separately and are not in the numerator.

**Four independent evidence layers, in decreasing strength:**

1. **`sequence_sha256` identity** — assumption-free. 25 of the 58 are byte-identical to a
   non-PAT/non-SYN canonical reference.
2. **Exact substring containment**, both directions, against all 4,273 non-PAT/non-SYN canonical
   records ≥3000 nt — assumption-free. Found 3 further verbatim cases the sha256 test cannot see
   (records that *contain* or are *contained by* a natural genome plus flanking).
3. **Nearest-natural-neighbour screen**: content-sampled k-mer index (k=31, keep-if
   `crc32(kmer) % 16 == 0`) over all 4,273 natural records ≥3000 nt, then full alignment of the top
   hits. Because the sampling is content-based rather than positional, matching substrings share
   sampled k-mers, so this is a much tighter screen than a positional stride — but it is still a
   *screen*, and a true nearest neighbour could in principle be missed. Reported divergences are
   therefore upper bounds on divergence to the true nearest relative.
4. **Windowed mosaic mapping** (k=25 exact, 250-nt windows, against a 25-member reference panel) to
   detect chimeras — this is what cracked the S19 series and nOPV2.

Plus, for every record whose disposition turned on a small number of nucleotides: a
**natural-occurrence test** (exact 13-mer context centred on each differing position, searched
across all 24,546 canonical records of release 2.1.5, partitioned into non-PAT/SYN vs PAT/SYN) and a
**canonical-restriction-site delta scan** (49 common cloning enzymes, whole-sequence counts plus
per-position ±9 nt attribution) — i.e. exactly the two tests that split CS406483 from CS406482 in
the prior report.

**What I verified independently.** The 58-record population (re-derived from scratch: 543 canonical
records ship TRUE, 58 of them at ≥3000 nt, and the list matches the one handed to me exactly). All
five D2 alignment numbers. The CS406483 AgeI control. The DQ205099 EagI/XhoI controls. The claim
that **0 of the 58 have a populated `strain_name`, `host_name` or `collection_date`** — confirmed,
all three are empty for all 58. The 12 disagreeing-sha256 groups. The 29-member Q5 exempt list
(all 29 exist in canonical and all 29 currently ship FALSE; **zero overlap with the 58**).

**What I did NOT verify.** I made **no live network fetch**. I did not open a single patent document
or paper. Every patent/publication attribution below comes from the `definition` field of the
shipped source layer — i.e. from GenBank's own metadata. **Any claim about what a patent *says* is
second-hand and must be re-checked before it is written into a `reason` field.** My
restriction-site, bisulfite-conversion and capsid-swap interpretations are inference from sequence,
not citations — though the sequence evidence for the capsid swaps and the bisulfite conversion is
arithmetically exact and I regard it as decisive on its own.

**One method limitation worth naming.** The natural-occurrence test asks whether a *single*
substituted state, in its immediate 13-nt context, is attested in a natural record. It does not ask
whether the *combination* of states is attested. A record every one of whose individual differences
occurs in nature may still be a genotype no natural organism carried. The prior report hit this same
wall on DQ205099 and resolved it by treating clause (b) as the discriminating clause; I follow that,
because the curator has now confirmed it (Q1). Where the combination question actually bites I flag
it rather than bury it (§5).

---

## 1. Population re-derivation — confirmed

> **Re-measured against release 2.3.0, 2026-07-30.** This report was originally written against
> 2.1.5. The 2.3.0 refresh removes 245 canonical records (all unaligned non-polio, none added), so
> the *denominators* here move — but **the engineered population does not**: 543 TRUE, 58 at
> ≥3000 nt, 50 PAT / 7 SYN / 1 VRL, and the same 58 accessions, all unchanged. The 12 same-sequence
> disagreement groups are identical in membership, not merely in count, and the PAT/SYN
> constrained-membership digest is byte-identical. Every conclusion in this report is therefore
> unaffected; only population-size figures were updated. Figures that record a *search performed
> against 2.1.5* are labelled as such rather than restated, because rewriting them would falsify
> what was actually measured.

`final/canonical/sequence_metadata.tsv.gz`: 24,301 rows; `engineered_or_construct` is `TRUE` on 543
and `FALSE` on 23,758 (no other values, no blanks). Filtering to `sequence_length_nt >= 3000` gives
**exactly 58**, matching the supplied list accession-for-accession.

By source `division`: **50 PAT, 7 SYN, 1 VRL.** And the complementary fact, which is the whole
story: there are **exactly 50 PAT records ≥3000 nt in the entire canonical set, and all 50 ship
TRUE**. Zero exceptions. That is not a curation outcome, it is `\bPAT\b` firing on a text blob.

The 7 SYN are `MN654096` and `PP068131`–`PP068136`. The 1 VRL is `DQ205099`.

`CS406433`/`PU749280` (2,745 nt) are correctly absent from this population — they are below the
3000-nt cut and were handled in the prior report.

---

## 2. The 58 resolve into seven families

| # | family | n | what it is | proposed |
|---|---|---|---|---|
| A | **Byte-identical re-deposits** | 25 | sha256-identical to a natural VRL reference | all **FALSE** |
| B | **Verbatim-containment re-deposits** | 8 | contain, or are contained by, a natural genome verbatim + flanking | all **FALSE** |
| C | **MEF-1 / Mahoney lab-stock deposits** | 5 | 4–7 nt from the reference, every difference attested in nature | all **FALSE** |
| D | **1980s JPO Sabin transcriptions** | 3 | Sabin 1/2/3 with a non-biological C↔G character artifact | all **FALSE** |
| E | **CAVA cold-adaptation deposits** | 4 | 11 and 24 nt from MEF-1 / Saukett; one unique position each | **FALSE**, flagged (§5) |
| F | **Genuinely engineered viral constructs** | 9 | AgeI cassette site; recoded-capsid nOPV2; six capsid-swap S19 chimeras | all **TRUE** |
| G | **Bisulfite-converted reference strings** | 3 | not viruses at all (§6.1) | **TRUE**, but see §6.1 |
| — | **`DQ205099`**, in no family | 1 | Sabin 2 cDNA clone; the one `VRL` record in the population | **FALSE** (§4) |

25 + 8 + 5 + 3 + 4 + 9 + 3 + 1 = 58. **46 FALSE, 12 TRUE** on the evidence alone —
**42 FALSE / 14 TRUE / 2 open after [Appendix B](#appendix-b-curator-answers-2026-07-29--decided)**,
which moves family E's `LY501107`/`LZ216102` to TRUE, leaves E's `LY501105`/`LZ216100` open, and
carve-excludes family G rather than shipping it TRUE.

**Two corrections to this table, 2026-07-30.** It previously gave family B as 6 and omitted
`DQ205099` entirely, so the stated sum was `25 + 6 + 5 + 3 + 4 + 9 + 3 = 58` — which is **55**. The
gap was not a typo in the addition: §3B's heading says 6 but its evidence covers **8** patent records
(`LY501104`/`LZ216099`, `LY501108`/`LZ216103`, `LY501109`/`LZ216104`, `LY501110`/`LZ216105`), and
§4 marks all eight VH FALSE by containment. Cross-checks against §4: 35 VH FALSE rows decompose as
family A (25) + family B (8) + `PU749305` + `PU749297`.

---

## 3. Family-by-family evidence

### 3A. Byte-identical re-deposits — 25 records, assumption-free FALSE

Every one shares a `sequence_sha256` with a non-PAT natural reference that ships
`engineered_or_construct=FALSE`. Clause (b) fails absolutely: the genotype demonstrably exists as a
separately-deposited natural/vaccine reference.

| natural parent (FALSE) | what it is | byte-identical PAT re-deposits (currently TRUE) |
|---|---|---|
| `NC_002058` / `V01149` | PV1 Mahoney, wild reference | `DD214216` `DI499146` `FV537074` `HC025129` `HV932178` `JC013103` `LY501106` `LZ216101` (8) |
| `M12197` | PV2 Lansing, wild reference | `DD214217` |
| `K01392` | PV3 Leon/37, wild | `DD214218` |
| `V01150` | Sabin 1 | `DD214219` `DI499147` `HV202313` `JC013104` (4) |
| `AY184219` | Sabin 1 | `DD214220` |
| `X00595` | Sabin 2 (P712, Ch, 2ab) | `DD214221` |
| `AY184220` | Sabin 2 (+ 8 natural ON596331-338 field isolates) | `DD214222` |
| `X00596` | Sabin 3 (Leon 12a1b) | `DD214223` |
| `AY184221` | Sabin 3 | `DD214224` |
| `AF499636` | **Coxsackievirus A11 strain Belgium-1** | `HW349523` `LP131905` `MA783942` `MP510547` (4) |
| `AF111984` | **PV1 wild isolate CHN-Jiangxi/89-1** (AFP/clinical) | `PE314016` `PH149759` (2) |

**Confidence: very high (assumption-free).** No alignment, no interpretation.

Two identifications the prior report left open are now closed:

- **`HW349523`/`LP131905`/`MA783942`/`MP510547` are Coxsackievirus A11 Belgium-1**, re-deposited
  byte-identically across four oncolytic-virus patents (`WO 2013157648-A/1` "Pharmaceutical
  composition"; `EP2851078`; `WO 2018182014-A/1` "Method for proliferation of oncolytic virus and
  Anti-tumor agent"; `EP3610870`). Not polio at all. All four currently carry
  `curation_status=provisional` and blank `poliovirus_classification`, which is right; only
  `engineered` is wrong.
- **`PE314016`/`PH149759` are the wild PV1 field isolate CHN-Jiangxi/89-1**, re-deposited in
  `KR 1020230019450-A/6` / `JP 2023528300-A/6` "ENCAPSULATED RNA REPLICONS AND METHODS OF USE" —
  i.e. the wild genome quoted as background in a replicon patent. Byte-identical to `AF111984`,
  which ships `wild`/`human`/`AFP/clinical`/FALSE.

**Q6 answered as asked.** The prior report flagged `DD214221` and `DD214215` and asked whether the
reasoning extends to their series-mates. It does, and more cleanly than expected: **9 of the 10
`DD2142xx` records are byte-identical to a natural reference** (`DD214216`–`DD214224`), and the
tenth (`DD214215`) is family C below. One correction to the prior report's §2c table: `X00595` is
**Sabin 2** ("strain Sabin 2 (P712, Ch, 2ab)"), not Sabin 1.

### 3B. Verbatim-containment re-deposits — 8 records, assumption-free FALSE

The sha256 test misses these because the patent deposit carries vector/flanking sequence around an
otherwise verbatim genome. Exact `str.find()` containment, both directions, settles them:

| record(s) | len | containment result | confidence |
|---|---|---|---|
| `LY501104` `LZ216099` | 7444 | **exact substring of `KP793687` (Brunenders) at offset 0**, 0 mm / 7444 | very high |
| `LY501109` `LZ216104` | 7462 | **contain `AY184219` (Sabin 1, 7441 nt) verbatim at offset 0**, 0 mm | very high |
| `LY501110` `LZ216105` | 7468 | **contain `AY184220` (Sabin 2, 7439 nt) verbatim at offset 0**, 0 mm — and also 8 natural ON596331-338 field-isolate genomes | very high |
| `LY501108` `LZ216103` | 7452 | **contain natural `KJ170591` (NIE1018488, Nigeria 2010) verbatim at offset 29**, 0 mm / 7379 — detailed below | very high |

**8 records, four pairs.** The heading and the §2 family table both said 6 for several revisions,
counting only the three pairs originally tabulated here while the `LY501108`/`LZ216103` pair was
established in the prose below and marked VH FALSE in §4. All four pairs are in the table now.

The first three reproduce the curator's own C1 ledger reasons exactly ("0nt/7441 vs Sabin 1", "0nt/7439 vs
Sabin 2") and add the previously-unstated Brunenders identification for `LY501104`/`LZ216099`
(currently classified `wild`; `KP793687` also ships `wild`/`human`/`vaccine/reference`, so the
inherited labels are already correct — only `engineered` is wrong).

**`LY501108`/`LZ216103` also belong here, and this is the single most useful new measurement in the
report.** The prior report's Q9 asked whether the 1 nt separating them from Sabin 3 could be the
claimed invention, and the curator (Q9) confirmed the flip without further characterisation. The
sequence evidence independently confirms it, assumption-free:

```
LY501108 (7452 nt) vs AY184221 (Sabin 3): 1 mismatch  — T2493C
LY501108 (7452 nt) vs KJ170591 (7379 nt): 0 mismatches, exact containment at offset 29
```

`KJ170591` is **`Human poliovirus 3 strain NIE1018488`, a natural Nigerian AFP/clinical
Sabin-like field isolate collected in 2010** (`host=Homo sapiens`, `date=2010`,
`stream=AFP/clinical`, FALSE). `LY501108` = 29 nt 5' flank + that entire natural field-isolate
genome + 44 nt 3' flank. Two further natural isolates (`KJ170592` = NIE1118478, `KJ170593` =
NIE1118468) are contained equally verbatim. So the one nucleotide is not the invention — it is
attested in nature three times over, in independent AFP surveillance samples. Clause (b) fails
outright. **Q9's flip is right and rests on data, not judgment.** (For bookkeeping I count these
two in family B rather than E; total unchanged.)

### 3C. MEF-1 / Mahoney lab-stock deposits — 5 records, FALSE

| record(s) | parent | mm / overlap | p-dist | positions |
|---|---|---|---|---|
| `CS406436` `PU749305` | `AY238473` MEF-1 | 4 / 6621 | 0.060% | T2580C C2781T T3685C T6805C |
| `CS406482` `PU749297` | `AY238473` MEF-1 | 4 / 7439 | 0.054% | same four |
| `DD214215` | `NC_002058` Mahoney | 7 / 7440, **0 gaps** | 0.094% | 2035 2133 2983 3043 3766 6261 6268 |

The four CS/PU records reproduce D2 exactly, and the curator's Q2 answer settles them: parental
MEF-1 lab-stock → FALSE. Nothing new needed.

`DD214215` is new evidence. Two findings:

1. **It is not a defective-interfering genome.** Zero internal gaps against Mahoney over the full
   7440-nt overlap. A DI particle is defined by a large internal deletion; there is none. The prior
   report's guess ("the *sequence* looks like the parental Mahoney plasmid, not a DI construct") is
   confirmed arithmetically. It is the full-length parental plasmid deposited alongside the DI
   constructs in the same patent ("Defective interfering particles, defective polioviral mutant
   RNAs, and plasmids").
2. **All 7 differences are attested in nature.** 13-mer context search across all 24,546 records of release 2.1.5:

   | pos | non-PAT/SYN records carrying the same context | notable |
   |---|---|---|
   | 2035 | 3 | incl. `V01148` (the other Mahoney deposit) |
   | 2133 | 443 | hundreds of iVDPV / Sabin-like / cVDPV field isolates |
   | 2983 | 57 | many cVDPV2 (`AF4056xx` series) |
   | 3043 | 8 | incl. `V01148`, iVDPV `AB1800xx`, VDPV `AF462418`, `DQ264279` |
   | 3766 | 266 | VDPV/cVDPV field isolates |
   | 6261 | 2 | incl. `V01148` |
   | 6268 | 106 | wild and VDPV field isolates |

   Three of the seven are shared with `V01148` — a second, independent Mahoney deposit. That is the
   same "independent depositors share the deviation, so the deviation is lab-stock lineage" argument
   the prior report used for the MEF-1 four-nt signature, and it holds here.

   `DD214215` gains one canonical restriction site vs Mahoney: **BamHI (`GGATCC`) 4→1×5, created at
   position 2133** — and that is precisely the position whose 13-mer context occurs in **443 natural
   records**. This is the DQ205099 pattern, not the CS406483 pattern: a canonical site created
   incidentally by variation that is abundant in nature. Not a designed site.

**Confidence: high.** `DD214215` → FALSE, and `Q6`'s proposed flip is confirmed on sequence evidence
rather than on the absence of contrary evidence.

### 3D. The 1980s JPO Sabin transcriptions — `E01570`/`E01571`/`E01572`, FALSE

Definitions: "RNA sequence of polio virus Sabin 1 / 2 / 3 type gene". Lengths 4677 / 4679 / 4670.

| record | best parent | mm | gaps | p-dist | **C↔G transversions** |
|---|---|---|---|---|---|
| `E01570` | `V01150` Sabin 1 | 8 | 0 | 0.171% | **7 / 8** |
| `E01571` | `X00595` Sabin 2 | 10 | 3 | 0.214% | **9 / 10** |
| `E01572` | `X00596` Sabin 3 | 14 | 0 | 0.300% | **11 / 14** |

**27 of the 32 differences are C↔G transversions.** In poliovirus evolution transitions outnumber
transversions roughly 4:1, and C↔G is the rarest transversion class of the four; the expected count
under any biological model is on the order of one, not 27. Full substitution-type census:

```
E01570: {C>G: 6, G>C: 1, A>G: 1}
E01571: {C>G: 7, G>C: 2, G>A: 1}
E01572: {C>G: 6, G>C: 5, A>G: 1, T>A: 1, A>T: 1}
```

This is a **systematic character-level transcription artifact** of the printed JPO patent sequence
listing (E-prefix = Japan Patent Office submissions, 1980s–90s era), not biology. Several of the
affected positions recur at homologous coordinates across all three independent records (521 /
519+521 / 524+526; 905 / 910 / 907; ~4390 in all three), which is the signature of a shared
mechanical artifact, not of shared descent.

Under any reading these are re-deposits of the Sabin 1/2/3 references with non-biological noise →
**FALSE**, taking the corresponding Sabin reference's labels. They already ship
`Sabin`/`vaccine`/`vaccine/reference`, so only `engineered` changes.

**Confidence: high.** The C↔G statistic is the argument; I did not fetch the patent to confirm the
artifact mechanism, and I am inferring "transcription error" rather than observing it.

### 3E. CAVA cold-adaptation deposits — `LY501105`/`LZ216100` and `LY501107`/`LZ216102`

These are the two pairs where the prior report explicitly declined to conclude (Q9's first half),
and they are the only two pairs in the FALSE column where I would accept a curator reversal without
argument. Both come from the same patent family (`KR 1020170012566-A` / `JP 2017519506-A`,
"Cold-Adapted-Viral-Attenuation (CAVA) and Novel Attenuated Poliovirus Strains").

**`LY501105`/`LZ216100`** (7502 nt, ships `wild`) vs `AY238473` MEF-1: **11 mm / 7440, 0 gaps.**
Four are the shared MEF-1 lab-stock signature (`T2580C C2781T T3685C T6805C`); seven are extra.
Natural-occurrence test on the seven:

| pos | non-PAT/SYN records | verdict |
|---|---|---|
| 3365 | 1 — `M12197` (Lansing, natural PV2 wild reference) | attested |
| 3535 | 3 — `EF015035` `EF015036` `PQ889405` | attested |
| **3784** | **0 — only `LY501105` and `LZ216100` themselves** | **not attested** |
| 3885 | 45 — incl. wild `AF111984`, many cVDPV2 | attested |
| 5658 | 5 — wild `AF111953` `AF111981` `AF111984`, `AY518730` | attested |
| 7147 | 17 | attested |
| 7440 | 20 | attested |

So 10 of 11 differences are attested; one is unique. Restriction-site test on that one: position
3784 changes MEF-1 `GCTTTC[T]CGGACA` → `GCTTTC[G]CGGACA`, which creates **no canonical site**. The
one canonical-site change in the whole record (NcoI `CCATGG` 2→3) is attributable to position
**3685** — a *lab-stock signature* position shared with CS406436/482/483 and PU749297/298/305.

So `LY501105` does **not** have the CS406483 signature. CS406483 had *two* changes creating a
*unique canonical cloning site* at a *protein-domain boundary*, absent from every other deposit of
the same strain. `LY501105` has one unattested nucleotide creating nothing.

**`LY501107`/`LZ216102`** (7471 nt, ships `engineered/lab`) vs `PP972258` **Saukett/A_NIBSC**
(PV3 wild reference, 1950): **24 mm / 7350, 0 gaps**, offset 51 (i.e. 51 nt 5' flank + genome + 70
nt 3'). Five of the 24 are IUPAC ambiguity codes in the deposit itself (`R` ×3, `Y` ×2 — the only
records in the 58 with ambiguity apart from a single `W` inherited from `AF499636`); ambiguity codes
in a patent listing are a population consensus or a deliberately-variable claimed position, not an
assembled construct. Natural-occurrence test on the 19 unambiguous positions:

| result | positions |
|---|---|
| attested in nature | 385 (1117 recs) · 1035 (20) · 2222 (2) · 2368 (7) · 2533 (3) · 2713 (1085) · 2742 (72) · 2903 (7) · 3019 (7) · 3309 (1) · 3433 (4) · 3470 (1) · 4255 (85) · 5285 (266) · 5575 (2) · 5644 (9) · 5690 (3) · 6184 (837) — **18 of 19** |
| **not attested** | **801 only** (`LY501107` + `LZ216102`) |

Restriction sites: the record gains ClaI at 5575 and BglII at 5690 — both positions attested in
nature (5575 in iVDPV `EF682348`, VDPV `FJ859189`; 5690 in VDPV `KY703697` and cVDPV-n
`PQ059264`/`PQ059265`). The unique position 801 (`GGCCT[A→C]CGGTGG`, in VP4) creates no canonical
site. Same shape as `LY501105`: no designed-site signature.

**Proposed: both pairs FALSE**, taking the reference's labels — `LY501105`/`LZ216100` already ship
`wild`/`human`/`vaccine/reference` (correct for MEF-1); `LY501107`/`LZ216102` ship
`engineered/lab`/`non-human`/`engineered/lab` and would need to move to Saukett's
`wild`/`human`/`AFP/clinical`-or-`vaccine/reference` (see Q3 below on which).

**Confidence: medium. This is the flagged call, and it is flagged twice over, because
`LY501107`/`LZ216102` carry an explicit active curator TRUE that I am proposing to reverse.** See
§5.1 — and read §5.1 before acting on this row, because the reason the curator's TRUE was recorded
turns out to rest on a reference-panel gap that has since closed.

### 3F. Genuinely engineered viral constructs — 9 records, TRUE

#### `CS406483` / `PU749298` — the AgeI cassette site (Q2, already accepted)

Reproduced exactly: 6 mm / 7439 vs MEF-1 (`G1773A A1776G` on top of the four-nt lab-stock
signature); whole-sequence restriction delta vs `CS406482` is **AgeI (`ACCGGT`) 0→1 and nothing
else**. Stays TRUE with the reasoning the curator accepted.

#### `MN654096` (nOPV2-CD) — recoded capsid, TRUE

127 mm / 7439 vs Sabin 2 (`AY184220`), 0 gaps; 126 mm vs `DQ205099`. Two independent structural
observations:

- **Every one of the 127 differences lies at position < 3500.** Binned by 500 nt: `{0:9, 500:19,
  1000:20, 1500:20, 2000:24, 2500:23, 3000:12, ≥3500:0}`. All differences are confined to the
  5'UTR + P1 capsid; the entire P2/P3 non-structural half is verbatim Sabin 2.
- The windowed mosaic map shows exact-25-mer identity to Sabin 2 of **100% from ~3500 nt to the 3'
  end**, but only **16–43% across 750–3250 nt** — a level of exact-substring loss that 127 scattered
  point substitutions in a 2,643-nt cassette produces exactly, and that no lineage variation does.

That is a designed, codon-modified capsid on a Sabin 2 backbone with an altered domain V. Both
clauses hold. **TRUE, confidence very high.** No natural-occurrence rescue is possible: no natural
record comes within 1.7% of it.

#### `PP068131`–`PP068136` (the S19 series) — six capsid-swap chimeras, TRUE

This is the most decisive result in the report, and it means these six are **correctly TRUE for
reasons entirely independent of this re-adjudication.**

`PP068133` ("Mutant Poliovirus 3 isolate USA/23-S19-3_PV3") is the base construct: **12 mm / 7432
vs `X00925` (P3/Leon 12a1b)**, and **10 of the 12 sit in two tight clusters at positions 477–482 and
529–537** — i.e. inside 5'UTR **IRES domain V**. Ten substitutions in two clusters inside one
stem-loop is a designed stem re-engineering, not lineage variation. (The other two are at 6304 and
7004.) Against Sabin 3 `AY184221` the same 10 domain-V changes appear plus 4 backbone positions.

The other five are the *same* construct with a different capsid cassette. Aligning each against
`PP068133`:

| record | strain (isolate_name) | mm vs `PP068133` | **mismatch position range** |
|---|---|---|---|
| `PP068131` | USA/23-S19-1_PV1 | 733 (+127 gap cols) | **754 – 3421** |
| `PP068132` | USA/23-S19-2_PV2 | 752 (+33) | **748 – 3415** |
| `PP068134` | USA/23-S19-Mah_PV1 | 738 (+83) | **754 – 3421** |
| `PP068135` | USA/23-S19-MEF1_PV2 | 733 (+15) | **790 – 3415** |
| `PP068136` | USA/23-S19-Skt_PV3 | 315 (+0) | **790 – 3412** |

**Zero differences outside 748–3421 in any of the five.** The PV3 CDS begins at ~745 and P1 ends at
~3385. This is a mathematically clean **P1 capsid cassette swap on a shared S19/Sabin-3 backbone** —
Sabin 1, Sabin 2, Mahoney, MEF-1 and Saukett capsids each dropped into the identical engineered
backbone. The windowed mosaic map shows it directly: `PP068131` reads `AY184221`(PV3) → `X00596`(PV3)
for windows 0–500, then `V01150` (**Sabin 1**) at 100% for windows 750–3250, then PV3 again from
3500 to the end.

Corroborating detail: `PP068131` and `PP068134` differ from each other by only 22 nt / 7441 — Sabin
1 vs Mahoney capsid, which are near-identical apart from the attenuating sites, exactly as expected.
`PP068132` vs `PP068135` differ by 462 nt — Sabin 2 vs MEF-1 capsid, also as expected.

Somebody assembled each of these six specific genotypes, and none of the six occurs in nature (a
Sabin-3 backbone carrying a Mahoney capsid and a re-engineered domain V is not a thing that
replicates in a child). **All six TRUE, confidence very high.**

One nuance to record: `PP068133`'s region downstream of position 742 contains `MN540979`
(a natural PV3 Sabin-like environmental isolate from China, 2018, 3717 nt) **verbatim**. So the
*backbone* is natural; the engineering is localised to the domain-V clusters. This does not rescue it
— domain V is where the invention is — but it is the kind of fact that makes a naive
natural-occurrence test say "attested" on the wrong region, and it is worth knowing that the S19
call rests on the *clustering* of the domain-V changes, not on their absence from nature.

**These six are already fully adjudicated and my measurement independently corroborates the
curator's own.** All six carry active `manual_review_overrides.csv` rows (`confirmed_by=Mike`,
`source = GenBank record; PMID:38888364`) and **18 active rows in `registry/decisions.tsv`**
(`D-fc9d0aaf2a11`, `D-451709cfd125`, `D-1dbf11fdb0f6`, `D-12d3eb6ceda2`, `D-b57ada559d1c`,
`D-8b60301d06bc` for `engineered_or_construct`, plus `classification` and `origin_class` rows),
landed in private commit `efb4067` (2026-07-27) after a per-segment mosaic probe. Three independent
reproductions now agree:

| quantity | private C1 / mosaic probe | my measurement |
|---|---|---|
| `PP068135` vs `PP068132`, P1 capsid vs rest | 5'NCR 21.4/21.4, **P1 17.5/0.1**, P2 17.2/17.2, P3 14.3/14.3, 3'UTR 2.9/2.9 | all 733 mm confined to 790–3415, zero outside |
| `PP068131` full-genome divergence from nearest PV1 ref | 9.8% (vs Brunhilde) | 10.25% vs Sabin 1 `AY184219` |
| `PP068134` | 9.76% | 10.28% vs Mahoney |
| `PP068133` from Sabin 3 | 14 nt / 7432 = 0.19% | 14 mm / 7432 vs `AY184221`; **12 mm vs `X00925`** |
| `PP068136` | 4.43% | 4.40% vs `X00925`, 4.24% vs `PP068133` |

Two things my measurement adds that were not previously in the repo:

1. **The domain-V mechanism is now attested from the sequence.** The curator's reason strings assert
   "rationally-designed, genetically-stabilized **domain-V** mutant", but that phrase is external to
   the record — the GenBank source features carry only `/organism`, `/mol_type`, `/isolate`,
   `/db_xref` (no `/note`, no `/clone`, no keyword), the two references are titled "Complete Genome
   Sequences of Six New S19 Poliovirus Reference Strains" / "Direct Submission" with `journal =
   Unpublished` and **empty `pubmed_id`**, and nothing anywhere in the record says "domain V". The
   10-substitution two-cluster signature at 477–482 / 529–537 is the first in-repo *sequence*
   evidence for the asserted mechanism. That is worth folding into the `evidence_reference`, because
   the current one (`"GenBank record; PMID:38888364"`) is the only support and the PMID is not in the
   record.
2. **One reason string is imprecise.** `PP068136`'s reason says "domain-V mutant on a **wild Saukett
   backbone**". The measurement says the *backbone* (everything outside 790–3412) is byte-shared with
   `PP068133`, i.e. Sabin-3/Leon-derived; what is Saukett is the **P1 capsid**. The other five reason
   strings say "capsid backbone", which is compatible. If the reason strings are being rewritten for
   the rename anyway, `PP068136`'s should say "Saukett capsid" to match its siblings and the data.

### 3G. `FV537075` / `FV537076` / `FV537077` — not viruses. See §6.1.

---

## 4. Per-record disposition table

`div` from `final/source/normalized_tsv/records.tsv.gz`. "cls" = shipped `poliovirus_classification`.
Confidence: **VH** = assumption-free (sha256 / exact substring / arithmetic), **H** = alignment +
natural-occurrence + restriction evidence all concordant, **M** = defensible either way, flagged.

| accession | div | len | cls | ships | **proposed** | evidence | conf |
|---|---|---|---|---|---|---|---|
| `CS406436` | PAT | 6621 | wild | TRUE | **FALSE** | MEF-1 lab-stock, 4 mm/6621; signature shared with 3 independent patent families | H |
| `PU749305` | PAT | 6621 | wild | TRUE | **FALSE** | sha256-identical to `CS406436` | VH |
| `CS406482` | PAT | 7439 | wild | TRUE | **FALSE** | MEF-1 lab-stock, 4 mm/7439 | H |
| `PU749297` | PAT | 7439 | wild | TRUE | **FALSE** | sha256-identical to `CS406482` | VH |
| `CS406483` | PAT | 7439 | wild | TRUE | **TRUE** | unique AgeI site, `G1773A`+`A1776G` (Q2 accepted) | H |
| `PU749298` | PAT | 7439 | wild | TRUE | **TRUE** | sha256-identical to `CS406483` | VH |
| `DD214215` | PAT | 7456 | engineered/lab | TRUE | **FALSE** | Mahoney +7 nt, **0 gaps** (not a DI genome); all 7 attested in nature, 3 shared with `V01148`; BamHI@2133 attested 443× | H |
| `DD214216` | PAT | 7440 | Sabin-like | TRUE | **FALSE** | = `NC_002058`/`V01149` Mahoney | VH |
| `DD214217` | PAT | 7440 | wild | TRUE | **FALSE** | = `M12197` Lansing | VH |
| `DD214218` | PAT | 7431 | Sabin-like | TRUE | **FALSE** | = `K01392` Leon/37 | VH |
| `DD214219` | PAT | 7441 | Sabin-like | TRUE | **FALSE** | = `V01150` Sabin 1 | VH |
| `DD214220` | PAT | 7441 | Sabin-like | TRUE | **FALSE** | = `AY184219` Sabin 1 | VH |
| `DD214221` | PAT | 7439 | engineered/lab | TRUE | **FALSE** | = `X00595` **Sabin 2** (Q6) | VH |
| `DD214222` | PAT | 7439 | Sabin-like | TRUE | **FALSE** | = `AY184220` Sabin 2 + 8 natural field isolates | VH |
| `DD214223` | PAT | 7434 | Sabin-like | TRUE | **FALSE** | = `X00596` Sabin 3 | VH |
| `DD214224` | PAT | 7432 | Sabin-like | TRUE | **FALSE** | = `AY184221` Sabin 3 | VH |
| `DI499146` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `DI499147` | PAT | 7441 | Sabin-like | TRUE | **FALSE** | = `V01150` Sabin 1 | VH |
| `DQ205099` | VRL | 7439 | Sabin-like | TRUE | **FALSE** | Sabin 2 +3 nt, all synonymous, each attested in nature (Q1) | H |
| `E01570` | PAT | 4677 | Sabin | TRUE | **FALSE** | Sabin 1 +8 nt, **7/8 C↔G artifact** | H |
| `E01571` | PAT | 4679 | Sabin | TRUE | **FALSE** | Sabin 2 +10 nt, **9/10 C↔G artifact** | H |
| `E01572` | PAT | 4670 | Sabin | TRUE | **FALSE** | Sabin 3 +14 nt, **11/14 C↔G artifact** | H |
| `FV537074` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `FV537075` | PAT | 7440 | engineered/lab | TRUE | **TRUE** | Mahoney with **every C→T** (bisulfite-converted top strand) — §6.1 | VH / see §6.1 |
| `FV537076` | PAT | 7440 | engineered/lab | TRUE | **TRUE** | **reverse complement** of Mahoney with every C→T — §6.1 | VH / see §6.1 |
| `FV537077` | PAT | 7440 | engineered/lab | TRUE | **TRUE** | sha256-identical to `FV537076` | VH / see §6.1 |
| `HC025129` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `HV202313` | PAT | 7441 | Sabin | TRUE | **FALSE** | = `V01150` Sabin 1 | VH |
| `HV932178` | PAT | 7440 | Sabin-like | TRUE | **FALSE** | = Mahoney (cls is also wrong — §6.3) | VH |
| `HW349523` | PAT | 7453 | (blank) | TRUE | **FALSE** | = `AF499636` **CVA11 Belgium-1** | VH |
| `JC013103` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `JC013104` | PAT | 7441 | Sabin-like | TRUE | **FALSE** | = `V01150` Sabin 1 | VH |
| `LP131905` | PAT | 7453 | (blank) | TRUE | **FALSE** | = `AF499636` CVA11 Belgium-1 | VH |
| `LY501104` | PAT | 7444 | wild | TRUE | **FALSE** | **exact substring of `KP793687` Brunenders** | VH |
| `LZ216099` | PAT | 7444 | wild | TRUE | **FALSE** | same | VH |
| `LY501105` | PAT | 7502 | wild | TRUE | **FALSE** | MEF-1 +11; 10/11 attested; unique pos 3784 creates no site | **M** — §5.1 |
| `LZ216100` | PAT | 7502 | wild | TRUE | **FALSE** | sha256-identical to `LY501105` | **M** — §5.1 |
| `LY501106` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `LZ216101` | PAT | 7440 | wild | TRUE | **FALSE** | = Mahoney | VH |
| `LY501107` | PAT | 7471 | engineered/lab | TRUE | **FALSE** | Saukett `PP972258` +24 (5 are IUPAC); 18/19 attested; unique pos 801 creates no site | **M** — §5.1 |
| `LZ216102` | PAT | 7471 | engineered/lab | TRUE | **FALSE** | sha256-identical to `LY501107` | **M** — §5.1 |
| `LY501108` | PAT | 7452 | Sabin-like | TRUE | **FALSE** | **contains natural `KJ170591` (NIE1018488, Nigeria 2010) verbatim**, 0 mm/7379 | VH |
| `LZ216103` | PAT | 7452 | Sabin-like | TRUE | **FALSE** | same | VH |
| `LY501109` | PAT | 7462 | Sabin | TRUE | **FALSE** | **contains `AY184219` Sabin 1 verbatim** | VH |
| `LZ216104` | PAT | 7462 | Sabin | TRUE | **FALSE** | same | VH |
| `LY501110` | PAT | 7468 | Sabin | TRUE | **FALSE** | **contains `AY184220` Sabin 2 verbatim** | VH |
| `LZ216105` | PAT | 7468 | Sabin | TRUE | **FALSE** | same | VH |
| `MA783942` | PAT | 7453 | (blank) | TRUE | **FALSE** | = `AF499636` CVA11 Belgium-1 | VH |
| `MN654096` | SYN | 7439 | nOPV | TRUE | **TRUE** | 127 mm vs Sabin 2, **all at pos <3500**; capsid exact-identity 16–43% = recoded cassette | VH |
| `MP510547` | PAT | 7453 | (blank) | TRUE | **FALSE** | = `AF499636` CVA11 Belgium-1 | VH |
| `PE314016` | PAT | 7443 | wild | TRUE | **FALSE** | = `AF111984` wild PV1 CHN-Jiangxi/89-1 | VH |
| `PH149759` | PAT | 7443 | wild | TRUE | **FALSE** | = `AF111984` | VH |
| `PP068131` | SYN | 7441 | engineered/lab | TRUE | **TRUE** | Sabin-1 capsid on S19/Sabin-3 backbone; all 733 mm in 754–3421 | VH |
| `PP068132` | SYN | 7434 | engineered/lab | TRUE | **TRUE** | PV2 capsid swap; all 752 mm in 748–3415 | VH |
| `PP068133` | SYN | 7432 | engineered/lab | TRUE | **TRUE** | S19 base: 10 of 12 mm vs Leon 12a1b clustered in 5'UTR domain V (477–482, 529–537) | VH |
| `PP068134` | SYN | 7441 | engineered/lab | TRUE | **TRUE** | Mahoney capsid swap; all 738 mm in 754–3421 | VH |
| `PP068135` | SYN | 7434 | engineered/lab | TRUE | **TRUE** | MEF-1 capsid swap; all 733 mm in 790–3415 | VH |
| `PP068136` | SYN | 7432 | engineered/lab | TRUE | **TRUE** | Saukett capsid swap; all 315 mm in 790–3412 | VH |

**Totals on the evidence alone: 46 → FALSE (35 VH, 7 H, 4 M), 12 stay TRUE.**

**After [Appendix B](#appendix-b-curator-answers-2026-07-29--decided): 42 → FALSE (35 VH, 7 H),
14 stay TRUE, 2 open.** Three corrections to the table above, all from Appendix B:

- **`LY501107`/`LZ216102` read TRUE, not FALSE** (Q1 — directed cold-adaptation selection satisfies
  the revised criterion). They were 2 of the 4 confidence-**M** rows, so the FALSE set's confidence
  split becomes 35 VH / 7 H / **0 M**. (Extracted programmatically from the table above on
  2026-07-30; two earlier statements of this split said 36/6, which the table does not support.)
- **`LY501105`/`LZ216100` are open, not FALSE.** They are the other 2 M rows and the only remaining
  M in the population; not implemented in either direction until the curator rules.
- **`FV537075`/`FV537076`/`FV537077` are carve-excluded, not TRUE** (Q5). They stay inside the 14
  "not FALSE" count here because they are not flips, but they leave `final/` entirely rather than
  shipping any `engineered` value.

The flip set that actually lands is therefore **42 + `A09260` = 43 records**.

Label inheritance (Q8), where a flipped record's other fields disagree with its parent's, is
tabulated in §6.3 — **16 of the 25 byte-identical records** need one or more of
`poliovirus_classification`/`sample_origin`/`surveillance_stream` moved as well, and two of those
inheritances are themselves questionable (Q3). Both figures are counted from §6.3's own table:
16 accessions across its first nine rows need a move, 9 already match, 16 + 9 = 25. Earlier drafts
said "18 of the 46" (wrong denominator) and then "18 of the 25" (wrong numerator).

**Partly overtaken by concurrent private curation, 2026-07-29.** A separate curation pass in the
private repository (its commit `f848530`, "Fix 19 patent-deposit reference-strain
misclassifications") has since moved co-fields on six records in this table. It changed **no**
`engineered_or_construct` value, so every disposition above stands, but the `cls` and "ships"
columns are now stale for those six:

| accession | what moved privately | effect here |
|---|---|---|
| `DD214216`, `HV932178` | `cls`→`wild`, `origin`→`human`, `stream`→`vaccine/reference` | exactly what §6.3 planned — **already done**, only the `engineered` flip remains |
| `DD214218` | `cls`→`wild` (agrees with parent `K01392`) | `stream` still needs the §6.3 move |
| `DD214223` | `cls`→`wild`, `reference_label`→`Leon37` | **attributed to the wrong parent** — it is byte-identical to `X00596` (Sabin 3, 7,434 nt), not to `K01392` (7,431 nt). Flag for private-side correction; does not change the FALSE call |
| `PE314016`, `PH149759` | `cls`→`engineered/lab`, `origin`→`non-human` | the private pass concluded these are codon-recoded constructs, i.e. the **opposite** of the FALSE call here. **Adjudicated by the curator 2026-07-29 in favour of FALSE**: they are `sequence_sha256`-identical to `AF111984`, a named wild PV1 field isolate, and the 20.2% figure the private note relies on is divergence from *Sabin*, not from that byte-identical relative. The private values need correcting, not this table |

---

## 5. Where I am not confident — carried, not forced

### 5.1 `LY501105`/`LZ216100` and `LY501107`/`LZ216102` — the cold-adaptation problem (confidence M)

Two readings are genuinely defensible and the sequence evidence does not choose between them.

*Reading A (my proposal: FALSE).* Clause (b) governs, per the curator's Q1 answer. 10 of 11 and 18
of 19 differences are independently attested in natural field isolates; the unique positions create
no canonical cloning site and are not clustered; the CS406483 signature (unique canonical site,
domain boundary, absent from all sibling deposits) is absent. `LY501105` is already curated `wild`
as a MEF-1 re-deposit. The IUPAC ambiguity codes in `LY501107` point to a passaged population
consensus, not an assembled clone.

*Reading B (TRUE).* The CAVA patent's whole subject is *novel attenuated poliovirus strains*. A
cold-adapted variant selected by low-temperature passage is a purpose-built strain — and 24 nt from
Saukett is a lot more than 1 nt from Sabin 3. If the 24 mutations *are* the cold-adaptation
phenotype, then this is the invention, and calling it a Saukett re-deposit hides a real engineered
strain in the `wild` bucket.

#### The material new fact: `LY501107`/`LZ216102`'s existing TRUE rests on a closed panel gap

`LY501107` and `LZ216102` are **not** unadjudicated. They carry two active curator artefacts in the
private repo:

- `data/genbank/working/manual_review_overrides.csv`, `confirmed_by=Mike`,
  `source = Patents KR1020170012566-A / JP2017519506-A (Janssen/Crucell)`, note verbatim:
  *"CAVA (Cold-Adapted-Viral-Attenuation) patent construct."* — `origin_class=non-human`,
  `classification=engineered/lab`, `engineered_or_construct=TRUE`.
- `data/genbank/working/metadata_review_decisions.md`, the C1 pass, verbatim:
  *"**12/37 remain engineered/construct:** CAVA-3 LY501107/LZ216102 (**12.3% from all PV3**), S19
  engineered series PP068131–136 …"*

**That 12.3% figure is measurable, and it is measured against the wrong panel.** I reproduce it
exactly: `LY501107` vs `X00925` (Leon 12a1b) = **12.31%**. But `LY501107` vs `PP972258`
(**Saukett/A_NIBSC**) = **0.327%**. `PP972258` is a `PP`-prefix accession — deposited in 2024,
*after* the C1 adjudication (2026-06-24 per `c1_construct_reference_resolution.md`) built its
reference panel. The C1 conclusion "12.3% from all PV3 references → engineered construct, not a
reference re-deposit" was correct on the data available; it is no longer correct on the data now in
the database.

That does not by itself make the disposition wrong — Reading B survives intact, and 24 nt from
Saukett is exactly what a cold-adaptation patent should look like. But it does mean **the recorded
reason for the TRUE is now false**, in the same way D2's "too few substitutions for deoptimization"
reasoning was false while its conclusion was right. At minimum the reason needs replacing. Whether
the conclusion also flips is the curator's call.

The same C1 methodological note anticipates this: *"the CAVA mutations (which the paper places in
5'UTR + non-structural 2C/3D) are invisible in VP1-only comparison."* My 24 differences are spread
385–6184 with hits in both the 5'UTR (385) and 2C/3D (4255, 5285, 5575, 5644, 5690, 6184) — i.e.
they sit where the paper reportedly places the cold-adaptation mutations. **That is evidence for
Reading B**, and I record it against my own proposal. It is also the only sequence-level support
for Reading B I found: the positions are in the right regions, even though 18 of 19 are individually
attested in nature.

#### Why I cannot settle it

The definition's clause (a) is "someone *assembled* that specific genotype". A serially-passaged cold
variant was **selected**, not assembled — so clause (a) arguably fails and the record is FALSE for a
reason unrelated to clause (b). But that same argument makes `engineered` silent about an entire
category of deliberate laboratory strain construction, which is almost certainly not what the curator
wants the column to do. The prior report raised this as its §6.2 and it was not among the ten
questions answered.

**And the category is larger than these four records.** The same "selected, not assembled" problem
governs seven more canonical records with explicit curator TRUEs — `JN105289`–`JN105295`,
in-vitro-selected drug-resistant variants whose field parents (`AF405625`, `AF448783`, `EU684056`)
are separate AFP/clinical records already in the carve (override note: *"Lab-selected derivative;
field parent … is a separate AFP/clinical record already in the carve"*). Those are below 3000 nt so
outside my adjudicated population, but they stand or fall with the same judgment. **This is Q1
below, and it governs at least 11 records.**

Note the asymmetry in blast radius: `LY501105`/`LZ216100` are already curated `wild` MEF-1
re-deposits by C1, so FALSE is the status-quo-consistent call and no curator decision is reversed.
`LY501107`/`LZ216102` are the opposite — flipping them FALSE reverses an explicit
`confirmed_by=Mike` override and moves three fields. **If the curator wants to be conservative on
exactly one pair, `LY501107`/`LZ216102` is the pair to hold** — but the reason string should be
corrected either way.

### 5.2 `FV537075`/`FV537076`/`FV537077` — TRUE on the letter of the definition, wrong category (see §6.1)

I propose TRUE because both clauses hold, but I have low confidence that TRUE is the *useful* answer,
because the record is not a virus genotype at all. **Q2 below.**

### 5.3 What the natural-occurrence test cannot tell you

For the six family-C/D records (`DD214215`, `CS406436/482`, `E01570/71/72`) I verified each
difference individually. I did **not** verify that the *combination* is attested — no single natural
record carries all 7 of `DD214215`'s differences, and none carries all 8/10/14 of `E0157x`'s. On the
curator's Q1 reading this does not matter (clause (b) is read as "this is a replicate of a naturally
occurring reference", and lab-stock passage variation does not make a new genotype). But it is the
same residual tension the prior report stated honestly for DQ205099, and it applies to six more
records here. It is not resolvable by measurement.

### 5.4 `E0157x`: artifact vs. real divergence

My C↔G argument is statistical, not mechanical. If those 27 C↔G differences were real, `E01570-72`
would be lab-stock variants at 0.17–0.30% from the Sabin references — still comfortably
re-deposits, still FALSE. So the disposition is robust to my being wrong about the mechanism; only
the wording of the `reason` field is at risk. I would keep "transcription artifact" out of a `reason`
field unless someone reads the patent.

### 5.5 Screen limits

The nearest-natural-neighbour search is a k-mer screen over 4,273 natural records ≥3000 nt. Records
below 3000 nt were excluded from the *parent panel*, so a fragmentary natural record that happened
to be a better parent would be missed. This matters nowhere in practice — every one of the 58
resolved to a full-length parent or to a demonstrably designed construct — but the two "not attested
in nature" positions (`LY501105`@3784, `LY501107`@801) were searched against **all** 24,546 records of release 2.1.5
including fragments, so those two claims are not subject to this limit.

---

## 6. Collateral findings the re-adjudication turned up

### 6.1 `FV537075/76/77` are bisulfite-converted reference strings, not poliovirus genomes

This is the most important collateral finding, and it is a live data-quality hazard, not just a
labelling question. The prior report bucketed `FV537075` as "unmeasured (overlap 0)" and speculated
that `FV537075/76/77` were "the genuine defective-interfering-particle constructs". They are not.
Base composition settles it arithmetically:

| record | A | C | G | T | GC% | relationship to Mahoney (`NC_002058`) |
|---|---|---|---|---|---|---|
| `NC_002058` | 2206 | 1737 | 1711 | 1786 | 46.3% | — |
| `FV537074` | 2206 | 1737 | 1711 | 1786 | 46.3% | **byte-identical** |
| `FV537075` | 2206 | **0** | 1711 | **3523** | 23.0% | Mahoney with **every C→T**. 3523 = 1786 + 1737 exactly |
| `FV537076` = `FV537077` | 1786 | **0** | 1737 | **3917** | 23.3% | **reverse complement** of Mahoney with every C→T. 3917 = 2206 + 1711 exactly |

Confirmations: `FV537075` vs Mahoney aligns at 1737 mismatches / 7440, **zero gaps, identical
length** — and 1737 is exactly Mahoney's C count. `FV537076`'s reverse complement vs Mahoney gives
1711 mismatches — exactly Mahoney's G count (= the revcomp's C count). Both numbers are exact, not
approximate. The patent is titled **"Modified Microbial Nucleic Acid"**; this is an in-silico (or
in-vitro) **bisulfite conversion** of the Mahoney genome — top strand, and bottom strand twice.

Consequences beyond `engineered`:

- All three ship `organism_name = Poliovirus 1`, `sequence_scope = complete_genome`, and are in
  `final/canonical/sequences.fasta.gz`. Any whole-genome MSA or phylogeny that ingests canonical
  PV1 complete genomes will pull in three 23%-divergent, C-less pseudo-genomes. Given the
  `POLIO_unified` / `EV_unified` MSA work in the private repo, this is a real contamination path.
- **`FV537076`/`FV537077` are stored in reverse-complement orientation** relative to every other
  poliovirus record in the database. That is a defect independent of everything else in this report.
- `engineered=TRUE` is *technically* correct (nobody's C-less poliovirus occurs in nature) but
  communicates the wrong thing: a reader will infer a lab-made virus. `sequence_scope` or
  `curation_status` is where this belongs. See Q2.

### 6.2 The `Q5` 29-record exempt rule does not reproduce its own list

The curator's Q5 operationalization is "canonical records with a populated `strain_name` matching a
known vaccine seed/production strain". I checked all 29 against canonical. **Seven of the 29 have a
BLANK `strain_name`:**

| accession | `definition` | why it's in the list |
|---|---|---|
| `J02283` | "poliovirus type 3 sabin vaccine strain 3' frag" | strain named only in `definition` |
| `X00595` | "Poliovirus type 2 genome (strain Sabin 2 (P712, Ch, 2ab))" | same |
| `X00596` | "Poliovirus type 3 mRNA (vaccine strain Sabin 3 (Leon 12a1b))" | same |
| `X00925` | "Poliovirus type 3 leon 12 a1b sequence (P3/Leon 12 a1b)" | same |
| `MZ245455` | "Human poliovirus 2, complete genome" (`cls=nOPV`) | **different category** — a designed nOPV |
| `OR253701` | "Poliovirus 1 isolate nOPV1, complete genome" (`cls=nOPV`) | **different category** |
| `OR253702` | "Poliovirus 3 isolate nOPV3, complete genome" (`cls=nOPV`) | **different category** |

Two separate problems:

1. **The stated test is not implementable as stated.** Four records (`J02283`, `X00595`, `X00596`,
   `X00925`) carry the strain identity only in `definition`, so a `strain_name` regex misses them.
   Conversely, a naive vaccine-seed regex over `strain_name` matches **653** canonical records —
   because hundreds of Sabin-like *field isolates* carry `strain_name` values like `Sabin`,
   `Sabin 1`, `vaccine`. So the 29 are **not** mechanically re-derivable either way: they need an
   explicit locked allowlist, in the same rule + locked-allowlist pattern the rest of the project
   uses.
2. **The 29 are two categories wearing one label.** 26 are direct vaccine-seed / production-strain
   deposits (Sabin, CHAT, Lederle I/II/III, USOL-D-bac, Cox, fox), which are TRUE only by the
   curator's CDC-convention "vaccine source" rule. Three (`MZ245455`, `OR253701`, `OR253702`) are
   **nOPV designed strains**, which are TRUE by the ordinary clause-(a)+(b) test — exactly like
   `MN654096` in this population, which already ships TRUE. Those three do not need the vaccine-source
   convention at all, and recording them under it would obscure why they are engineered.

Also, likely omission: `AY082681` (`strain_name='FOX3'`, `cls=vaccine`) is **byte-identical** to
`AY082682` (`strain_name='LederleIII'`) which *is* in the 29. If `AY082682` flips TRUE and
`AY082681` does not, that group becomes a new sha256 contradiction of exactly the kind §7 is
designed to catch.

### 6.3 Label-inheritance deltas for the flip set (Q8 input)

*"The 46" throughout this section and §8.7/§9 means the pre-Appendix-B flip set. The decided set is
**42**, plus `A09260`; see [Appendix B](#appendix-b-curator-answers-2026-07-29--decided). The
per-record content below is unaffected — only the count is.*

Of the 25 byte-identical records, **16** disagree with their parent on at least one of
`poliovirus_classification` / `sample_origin` / `surveillance_stream`; the other 9 already match.
(This sentence said 18 through three revisions. The count below it — 16 across the first nine rows,
9 in the last — has been right the whole time; two earlier corrections fixed the figure where it was
*cited* and left the figure at its *source*.)

| record | parent | fields that would move under "take the reference's label" |
|---|---|---|
| `DD214216`, `HV932178` | `NC_002058` | cls `Sabin-like`→**`wild`**; origin `unknown`→`human`; stream `not_applicable`→`vaccine/reference` |
| `HC025129` | `NC_002058` | origin `unknown`→`human`; stream `not_applicable`→`vaccine/reference` |
| `DD214217` | `M12197` | origin `unknown`→`human`; stream `not_applicable`→`vaccine/reference` |
| `DD214218` | `K01392` | cls `Sabin-like`→**`wild`**; origin `unknown`→`human`; stream `not_applicable`→**`AFP/clinical`** ⚠ |
| `DD214219`, `DD214220`, `DD214222`, `DD214223`, `DD214224` | Sabin refs | cls `Sabin-like`→`Sabin`; origin `unknown`→`vaccine`; stream `not_applicable`→`vaccine/reference` |
| `DD214221` | `X00595` | cls **`engineered/lab`→`Sabin`**; origin `non-human`→`vaccine`; stream `not_applicable`→`vaccine/reference` |
| `DI499147`, `JC013104` | `V01150` | cls `Sabin-like`→`Sabin` |
| `HV202313` | `V01150` | origin `non-human`→`vaccine`; stream **`engineered/lab`→`vaccine/reference`** |
| `PE314016`, `PH149759` | `AF111984` | origin `unknown`→`human`; stream `not_applicable`→**`AFP/clinical`** ⚠ |
| `DI499146`, `FV537074`, `JC013103`, `LY501106`, `LZ216101`, `HW349523`, `LP131905`, `MA783942`, `MP510547` | — | all three fields already match; only `engineered` changes |

⚠ **The two flagged rows are a problem with the inheritance rule itself, not with the records.**
`K01392` (Leon/37) and `AF111984` (CHN-Jiangxi/89-1) are natural field isolates shipping
`surveillance_stream=AFP/clinical`. Literally inheriting that would create three fake AFP
surveillance records out of patent deposits — which is worse than the `engineered/lab` value it
replaces. Q8's answer ("`vaccine/reference` for these re-deposits") reads as covering the
Sabin/MEF-1 case; it needs a decision for the field-isolate-parent case. See Q3.

### 6.4 `HV932178` and `DD214216`/`DD214218` carry contradictory classifications today

`HV932178` ships `organism_name=unidentified`, `poliovirus_classification=Sabin-like`, and is
**byte-identical to the wild PV1 Mahoney reference**. `DD214216` likewise (`Sabin-like` vs Mahoney's
`wild`), and `DD214218` (`Sabin-like` vs Leon/37's `wild`). These are pre-existing classification
defects independent of `engineered`; they are in §6.3's move list, but worth naming separately
because they would survive an `engineered`-only ledger patch.

---

## 7. Refined design for the `sequence_sha256` invariant (Q10)

The 3000-nt / blank-metadata heuristic in the brief was a good first pass but it is not needed, and
the metadata-blankness half of it does not work. Measured facts:

- 24,301 canonical rows → **20,291 distinct `sequence_sha256`**.
- **12 sha256 groups currently disagree on `engineered_or_construct`** (all lengths). 11 are ≥3000 nt
  covering 45 records; the twelfth is the 900-nt `A09260` group (235 records).
- **`blank_strict` (no `strain_name`, no `host_name`, no `collection_date`) does not separate
  re-deposits from references.** `AF111984` — a real wild PV1 AFP isolate — is blank on all three
  (it carries its identity in `isolate_name`). And in the other direction `X00595` and `X00596` are
  blank on all four provenance fields *and are the primary GenBank deposits of Sabin 2 and Sabin 3*.
  Under Q5 those two flip TRUE while their byte-identical patent twins `DD214221`/`DD214223` go
  FALSE — **both members metadata-blank, both full-length, and they must legitimately disagree.**
  No metadata-blankness predicate can separate them. The only structured signal that does is
  `division` (VRL primary deposit vs PAT re-deposit).

So I propose **two invariants instead of one**, split by whether an exemption can ever apply. This
is strictly better than one invariant with a length floor, because it lets the half that needs no
allowlist land immediately.

### Invariant A — `engineered` must agree among same-sequence patent/synthetic deposits

> For every `sequence_sha256` group, all members whose source `division` is `PAT` or `SYN` must carry
> the same `engineered` value. No exemptions, no length floor.

Rationale: two byte-identical patent (or synthetic) deposits of the same sequence cannot differ on
whether somebody assembled that genotype. The Q5 vaccine-source exemption applies to *primary VRL
deposits of vaccine seeds*, so it can never create a legitimate PAT/SYN-internal disagreement. This
makes the invariant unconditional.

Measured: it **constrains 178 sha256 groups covering 374 PAT/SYN records**, and it **currently passes
with 0 failures**. That is because every PAT record ≥3000 nt currently ships TRUE, so nothing
disagrees. Its value is as a *regression guard*, and it is exactly the guard that was missing: **D2
as written would have failed it** (`CS406482` FALSE while byte-identical `PU749297` stayed TRUE), and
so would any future per-accession adjudication that touches one twin. It is free to land today,
green, before any of this report's flips.

### Invariant B — no same-sequence TRUE/FALSE split without an explicit allowlist entry

> For every `sequence_sha256` group that contains at least one member with `engineered=FALSE`, no
> member may have `engineered=TRUE` unless that member appears in an explicit, reviewed
> `engineered_same_sequence_exemptions` allowlist carrying a reason.

Rationale: clause (b) is a property of the genotype. If any member of a byte-identical group is
labelled "this genotype occurred in nature", every other member inherits that fact. The allowlist is
the escape hatch for the CDC-convention case (Q5) and for any future genuinely-engineered record
that coincidentally matches a natural one — and it makes every such exception visible and
reviewable, which is the failure mode that produced this re-adjudication.

Measured: **12 failures today** — exactly the prior report's 12:

```
len 7453 (n=5)   TRUE: HW349523 LP131905 MA783942 MP510547
len 7443 (n=3)   TRUE: PE314016 PH149759
len 7441 (n=2)   TRUE: DD214220
len 7441 (n=5)   TRUE: DD214219 DI499147 HV202313 JC013104
len 7440 (n=10)  TRUE: DD214216 DI499146 FV537074 HC025129 HV932178 JC013103 LY501106 LZ216101
len 7440 (n=2)   TRUE: DD214217
len 7439 (n=10)  TRUE: DD214222
len 7439 (n=2)   TRUE: DD214221
len 7434 (n=2)   TRUE: DD214223
len 7432 (n=2)   TRUE: DD214224
len 7431 (n=2)   TRUE: DD214218
len  900 (n=235) TRUE: A09260
```

**All 12 resolve to zero under this report's proposed flips** — 11 of them via §4, and the twelfth
(`A09260`, 900 nt, PAT, a VP1 fragment byte-identical to 234 natural Sabin-like records) is exactly
the same class of re-deposit and should also flip FALSE. It is below the 58-record cut only because
of the 3000-nt filter, not because it differs in kind. **I recommend adding `A09260` to the flip
set** — that makes Invariant B land green with an *empty* allowlist.

### On the length floor: don't use one

The brief's 3000-nt floor was proposed to protect the short-VP1-fragment case
(`AY082679`/`82`/`83`/`88`, in the Q5 exempt set, ~900–906 nt, coincidentally matching hundreds of
field isolates). I tested that case directly. If the Q5 29 flip TRUE, the groups that would then
disagree are:

| Q5 member | len | sharers | needs an allowlist entry? |
|---|---|---|---|
| `AY082679` | 903 | 252 | yes |
| `AY082682` | 900 | 1 (`AY082681` FOX3) | yes — or flip `AY082681` too (§6.2) |
| `AY082683` | 900 | 234 (incl. `A09260`) | yes |
| `AY082688` | 906 | 150 | yes |
| `AY184219` | 7441 | 1 (`DD214220`) | yes |
| `AY184220` | 7439 | 9 (`DD214222` + 8 `ON5963xx`) | yes |
| `AY184221` | 7432 | 1 (`DD214224`) | yes |
| `V01150` | 7441 | 4 | yes |
| `X00595` | 7439 | 1 (`DD214221`) | yes |
| `X00596` | 7434 | 1 (`DD214223`) | yes |

That is **10 allowlist entries, not a threshold** — and note that half of them are *full-length*, so
a 3000-nt floor would not have avoided the allowlist anyway; it would only have hidden four of the
ten. An explicit 10-row allowlist with reasons is loud, greppable and reviewable; a magic constant is
the same silent mechanism that let the 543/506 counts drift unpinned in the first place. **Recommend:
no floor, explicit allowlist.**

### Also recommend: pin the counts

Nothing anywhere currently pins the number of `engineered=TRUE` records (the prior report's R4
finding). Add pinned expectations for: total `engineered=TRUE` (543 today), `engineered=TRUE` at
≥3000 nt (58 today → **11 proposed**), and `PAT`-division records shipping TRUE (506 today). Those
three numbers moving silently is what made a full-population re-adjudication necessary.

**The 11 is worth deriving, because two earlier attempts at it made the same mistake in both
directions.** The value is the count of records that *survive the rewritten predicate*, not the count
the report calls TRUE. Of the 14 decided TRUE: 3 (`FV537075`–`FV537077`) are carve-excluded and carry
no value, leaving 11 — the 7 reachable by `division == "SYN"` plus `CS406483`/`PU749298` (needing a
corrected and an added row) plus `LY501107`/`LZ216102` (already held). The 2 open records
`LY501105`/`LZ216100` do **not** add to it: they are PAT-division, are not `synthetic construct`, and
have **no ledger row of any status**, so under the rewritten rule they flip FALSE mechanically
regardless of shipping TRUE today. An earlier draft said 14, then 13 on the grounds that the open pair
"currently ships TRUE" — which is precisely the confusion between *shipping* a value and *surviving*
the rule that this report retracted about `LY501107`/`LZ216102` two sections ago. If the curator rules
the open pair TRUE, the pin becomes 13 **and** two new curation rows are required; nobody has planned
those. The pin also assumes `DD214215`/`DD214221`'s contradicting TRUE rows are retired (§8.6).

**Done, and it went further than this section asked.** Implemented in
[`tests/test_engineered_invariants.py`](../tests/test_engineered_invariants.py), which pins those
three plus the SYN counts, Invariant A's scoped record count (513), and the constrained-group
membership *digest* — because an adversarial review demonstrated that the group counts alone
(178/374) survive both deleting `SYN` from the scope and a compensating scope swap. That file also
carries the mutation evidence proving each pin fires.

---

## 8. Refined design proposal for `CONSTRUCT_PATTERNS` / `real_human_capture()` (Q4)

**Proposal only. No file in the private curation repository was modified.** All code facts below were read verbatim from
the private repo (read-only) and the impact numbers were computed read-only against the *public*
source layer, which contains the same 25,727 records.

### 8.1 The current rule, exactly

the private repository’s `data/genbank/working/infer_genbank_metadata.py:898`:

```python
engineered_or_construct = bool(construct) and not real_human_capture(row)
```

where `construct = search_any(CONSTRUCT_PATTERNS, blob(row))`. `CONSTRUCT_PATTERNS` is 18 regexes
(`:409-428`); `blob()` (`:223-246`) concatenates **20** fields with `" | "` — including `division`,
`references`, `authors`, `pubmed_ids`, `first_title` and `all_titles`. `search_any` (`:514-519`) is
first-match-wins, case-insensitive, no anchoring.

So the rule is: **one case-insensitive regex hit anywhere in a 20-field text blob that includes the
database division code, the paper titles and the author list, AND-NOT a metadata-completeness
veto.** No length gate, no polio gate, no taxonomy gate, no structured field test.

Measured today (private repo, read-only replay of the module's own functions): **1,042 of 25,727
source records match `CONSTRUCT_PATTERNS`, 88 are vetoed, 954 emit TRUE** — matching
`genbank_metadata_inferred_from_genbank.csv` exactly. After the two override surfaces, 959 TRUE in
the curated master; after the carve, **543 TRUE in the public canonical set.**

### 8.2 Remove — five patterns that test provenance, not genotype

| line | pattern | why remove | measured driver |
|---|---|---|---|
| 424 | `r"\bPAT\b"` | fires on `division` **as free text** inside `blob()`. This is the single largest driver in the whole rule. | **all 862 PAT source records emit TRUE, 0 vetoed**; **506 PAT records are in canonical and all 506 ship TRUE** — the prior report's number, independently reproduced |
| 423 | `r"\bpatent\b"` | fires on the `Patent:` reference string and on the patent `COMMENT` block. Redundant with 424 and equally a provenance claim. | same population |
| 425 | `r"\bclone\b"` | fires on ordinary molecular cloning of a PCR product. **The curator has already overridden this exact false positive**: `FJ492823`–`FJ492827` carry `engineered_or_construct=FALSE` with the note *"molecular cloning of an environmental PCR product, NOT an engineered construct => engineered_or_construct=TRUE was a false positive"*. Removing the pattern generalises that override into a rule and lets those five rows retire. | ~110 canonical `/clone` records (107 already FALSE via other paths) |
| 419 | `r"\bmutant\b"` | fires on any definition, paper title or author-list token containing "mutant". It is the **entire** evidence token behind the S19 series' `sampling_frame` (recorded verbatim as `"Mutant"` at high confidence) — but those six are `division=SYN`, so they survive structurally without it. | the bulk of the 88 vetoed records are `mutant`-class matches |
| 426 | `r"\boligo(?:nucleotide)?\b"` | an oligo is a reagent, not a genotype. | the `<200 nt` band — 154 canonical records ship TRUE below 200 nt |

### 8.3 Remove — two patterns the curator's Q1 answer has already retired

| line | pattern | why |
|---|---|---|
| 412 | `r"\binfectious (?:cDNA )?clone\b"` | Q1: an infectious cDNA clone of a natural strain is **not** engineered. Keeping this pattern in the *engineered* list directly contradicts the settled answer. It belongs in `SYNTHETIC_MATERIAL_PATTERNS` (`:433-453`), which answers the different question `origin == non-human`, and it is already there (`:442`). |
| 413 | `r"\bcdna clone\b"` | same; already at `:443` in the origin list |

This is what makes `DQ205099` FALSE by rule rather than by ledger row, and it is also the right
answer for `E01570`/`E01571`/`E01572`, whose patent `COMMENT` blocks read
`CC *source: clone=pVS(1)EP plasmid` / `pVS(2) 2503` / `pVS(3) 2603` — Nomoto's classic Sabin cDNA
clones (JP 1988094980-A, filed 1986). Under Q1 those are clones of natural strains: FALSE.

### 8.4 Keep the remaining nine patterns — but *not* in this predicate

`\bsynthetic construct\b`, `\bsynthetic\b`, `\bplasmid\b`, `\bvector\b`, `\bmutagenesis\b`,
`site-directed`, `\bengineered\b`, `defective[- ]interfering`, `\breplicon\b`, `\btransfection\b`,
`modified microbial nucleic acid` are all genuine engineering vocabulary. But they are being read out
of a blob that includes **paper titles and author lists**, which means a record can be flagged
engineered because of what someone wrote in a title. My recommendation is to keep them **only as a
review-queue signal** (they already feed `review_genbank_reference_or_construct.csv` at `:1076-1079`)
and remove them from the shipped predicate. They generate candidates; a human converts candidates
into ledger rows.

If keeping any of them in the predicate is preferred, at minimum switch the input from `blob()` to
`blob_record_level()` (`:251-259`, already defined and unused for constructs) — that drops
`division`, `references`, `authors`, `pubmed_ids`, `first_title`, `all_titles` from the text, which
removes the two worst false-positive channels without touching the pattern list at all. That is the
smallest possible change with the largest correctness gain, and it is worth measuring as an
alternative to §8.2.

### 8.5 The structured replacement

```python
# proposed — replaces line 898
# Stage 1: per-record structured signal.
structural = (
    row.get("division") == "SYN"                              # structured field test, not text
    or clean(row.get("organism")) == "synthetic construct"    # exact match, not regex over a blob
)
# Stage 2: promote across byte-identical groups BEFORE curation is applied. `engineered` is a
# claim about a genotype, so it cannot depend on which depositor's metadata happened to be read.
structural_by_group = {
    digest: any(structural(r) for r in records)
    for digest, records in group_by(all_records, key="sequence_sha256").items()
}
engineered = (
    curated_true(accession)
    or structural_by_group[row["sequence_sha256"]]
) and not curated_false(accession)
```

**Stage 2 is not optional, and the reason is a measured defect in the stage-1 rule.**
`organism_name` is depositor metadata, not a genotype property, and it is **not consistent across
byte-identical records**. Measured on the shipped release:

| accession | `organism_name` | len | same `sequence_sha256`? |
|---|---|---|---|
| `JA792237` | `synthetic construct` | 70 | yes — with `FB743426` |
| `FB743426` | `Enterovirus C` | 70 | yes |
| `JA792249` | `synthetic construct` | 70 | yes — with `FB743423` |
| `FB743423` | `Poliovirus 3` | 70 | yes |

The same 70 nt, deposited in two different patents, carries two different organism names. So the
stage-1 rule alone assigns **different `engineered` values to identical genotypes** — violating the
very invariant §7 designs, and reproducing the *category* of the `\bPAT\b` bug it replaces:
a decision driven by who deposited the record rather than by what the sequence is.

Measured impact of the two forms (read-only against the shipped release and the active ledger):

| | TRUE after | new same-sequence splits |
|---|---|---|
| stage 1 only, as originally drafted | 27 | **7** |
| stage 1 + group promotion | 32 | **2** |
| stage 1 + promotion + the §8.6 curation remediation | **29** | **0** |

The two residual splits under promotion alone are `DD214221`/`X00595` and `JC013129`/`DI499172` —
both curation-row problems, not rule problems, and both already on §8.6's remediation list. With the
four contradicting TRUE rows retired, `CS406483` corrected and `PU749298` added, the rewritten rule
lands with **zero** byte-identical groups disagreeing. That is the check §7 exists to make, and it
now passes by construction rather than by luck.

Three further deliberate design choices in stage 1:

1. **`division == "SYN"` is a structured test, and it does not currently exist anywhere in the
   repo.** I checked exhaustively: the only three `division` tests in the entire private repo are
   `infer_genbank_metadata.py:588`, `:727` and `curate_origin_unknown.py:267`, and all three test
   `== "PAT"`. `\bSYN\b` is not in `CONSTRUCT_PATTERNS`. All 11 SYN records currently emit TRUE only
   *accidentally*, via `\bmutant\b` / `\bsynthetic\b` text. Making it structural is strictly more
   robust and it is the signal that carries the 7 genuine polio constructs.
2. **`organism == "synthetic construct"` as an exact match, not a regex.** In the source layer,
   `organism_name` matches `/synthetic/i` on exactly 105 records and **every one of them is the exact
   string `synthetic construct`** — the NCBI controlled organism name (taxid 32630). An exact match
   is therefore lossless here and cannot drift onto e.g. a paper title. (Note: the `taxonomy` column
   exists in `genbank_metadata.csv` but is **not** in `blob()` and is never read; 0 records have
   "synthetic" anywhere in their taxonomy lineage, so a taxonomy-based test would add nothing.)

   **This choice was originally justified too narrowly, and the gap is the reason stage 2 exists.**
   "Cannot drift onto a paper title" is true and was the only failure mode considered. It misses that
   the field is not a property of the sequence at all: a depositor chooses it, and two depositors of
   the same bytes chose differently. Exactness protects against matching the wrong *text*; it does
   nothing about matching the wrong *kind of thing*. Group promotion is what makes the signal a
   genotype claim.
3. **Drop `real_human_capture()` from this predicate.** Its `:563` branch fires on *any parseable
   `/collection_date`*, which makes `engineered` a function of metadata completeness — a genuinely
   synthetic construct carrying a collection date (an nOPV shedding study, say) would be silently
   FALSE. With a narrow structured positive test there is nothing to veto. **Leave the function
   itself alone** — `infer_origin` uses it legitimately; remove only the `and not
   real_human_capture(row)` conjunct at `:898`.

### 8.6 Measured impact

Computed read-only against `final/source/normalized_tsv/` (public), which is the same 25,727 records.

**Source layer:** `division == "SYN"` → 11 records; `organism == "synthetic construct"` → 105
records; union (3 overlap) → **113 records**. Current rule: **954**. So the rule change moves
**≈841 source records TRUE→FALSE**, plus however many are held TRUE by new ledger rows.

**Canonical layer** (the shipped 24,301):

**Re-measured 2026-07-30 against the shipped release and the active ledger.** Two earlier versions
of this table were derived rather than measured, and both were wrong — see the correction note below.
The predicate after the rewrite is `structurally reachable OR curated TRUE`, so the population that
survives is the union of those two sets, and it is measurable directly:

| | count |
|---|---|
| ships TRUE today | **543** |
| reachable by the new structured signal | **12** |
| — the 7 genuine polio constructs | `MN654096` `PP068131`–`PP068136` |
| — 70-nt `synthetic construct` PAT oligos | `JA792237` `JA792238` `JA792249` `JA792250` `JA792251` |
| already held by an **active curated TRUE row** | **21** |
| — correctly, per Appendix B | `PP068131`–`PP068136`, `LY501107`, `LZ216102`, `JN105289`–`JN105295` (15) |
| — **contradicting this report**, so they need *retiring* | `AJ512791` `AJ512792` (Q8→FALSE), `DD214215` `DD214221` (§4→FALSE) |
| — outside this report's population, unadjudicated | `JC013129` (179 nt), `MA400487` (672 nt) |
| union — **TRUE after the change** | **27** |
| carry an active curated **FALSE** row while shipping TRUE | **3** — `CS406436` `CS406482` `CS406483` |
| **flip TRUE→FALSE** | **516** |

**Correction, and it matters more than the numbers.** This table twice claimed
`LY501107`/`LZ216102` "need an explicit TRUE ledger row to hold TRUE", calling that a trap the rule
rewrite would fall into. **They already have active TRUE rows**, migrated from
`manual_review_overrides.csv` — the applied source of truth. So do `JN105289`–`JN105295`, which the
previous count treated as flips even though Q1 decides them TRUE. The stated held-TRUE set of 4 was
wrong on three of its four members:

- `LY501107`, `LZ216102` — already held. No action.
- `CS406483` — has an active **FALSE** row, which the re-adjudication says is wrong (unique AgeI
  site). Needs **correcting**, not adding.
- `PU749298` — genuinely has no row. This is the only one of the four that needed adding.

The general lesson is the D2 lesson again, pointed the other way: it is not enough to reason about
what curation *ought* to say, because the applied artifact may already say something else. Check the
ledger. `FV537075`–`FV537077` do **not** need a row either — Q5 carve-excludes them, so they carry no
value at all; the knock-on is that dropping all three moves the pins to **177 groups / 372 records**
and `EXPECTED_SCOPED_RECORDS` 513 → **510**.

Every one of the 12 structurally-reachable records currently ships TRUE, so **the new rule creates
zero new TRUEs** — it only removes. All of §4's "stays TRUE" records survive: 7 structurally, the
rest by curation rows that already exist. The rule and the hand adjudication agree — but note that
agreement now rests on four rows that need *changing* (three FALSE→retired-or-TRUE, one added), not
on rows that need writing from scratch.

**Blast-radius honesty — 468 of the 516 flips are unadjudicated by me.** Counted as
`516 − 48`, where 48 is the intersection of the flip set with the records this report actually
judged per-record (the 58, plus `A09260`). Two earlier figures here were mixed-basis and both were
wrong: `478` was `524 − 46`, pairing a revised flip count with a superseded adjudication count, and
`473` was `516 − 43`, subtracting the §4 *landing* set even though two of its members
(`DD214215`, `DD214221`) are not in the flip set at all — they hold active curated TRUE rows and so
sit in the 27 that stay. Subtract only sets that are actually nested.

This is the single most
important caveat in the report and it is deliberately not in the headline summary, so read it here:
**this report adjudicated 58 of the 543 records shipping TRUE.** The remaining 485 are not covered
by any per-record judgement, and the rule rewrite flips almost all of them mechanically. That is the
same "boundary inherited from whatever artifact framed the analysis" failure (root cause R4) the
prior report was criticised for — the ≥3000 nt floor is a tractability choice, not a scientific one.
`CS406433` (2,745 nt, same patent family as the D2 trio, a verbatim Sabin 2 substring, shipping TRUE
with zero ledger rows) sits just under it and is backlog item B1.

The 531 canonical TRUE records not reachable by the structured signal break down as:

| length band | n | division | notes |
|---|---|---|---|
| **≥3000** | **51** | 50 PAT, 1 VRL (`DQ205099`) | **this report's population** (58 minus the 7 SYN); 42 flip, 4 held TRUE, 3 carve-excluded, 2 open |
| 900–2999 | 30 | 23 PAT, 7 VRL | the 7 VRL are exactly `JN105289`–`JN105295` (2634–2643 nt, explicit curator TRUEs — Q1) |
| 200–899 | 301 | 298 PAT, 3 VRL | prior report measured this band as overwhelmingly exact-substring re-deposits |
| 100–199 | 17 | 15 PAT, 2 VRL | |
| <100 | 132 | 115 PAT, 17 VRL | primers, probes, oligos, and the `M30211`–`M30222` DI fragments (60 nt) |

Of the 531, **501 are PAT and 30 are VRL.** The 30 VRL records are the whole population where the
flag is doing work outside the PAT blanket, and they are worth naming because they are tractable and
they are where the remaining judgment lives:

| group | n | what | proposed |
|---|---|---|---|
| `DQ205099` | 1 | Sabin 2 cDNA clone | FALSE (this report) |
| `AJ512791` `AJ512792` | 2 | NCPV lab-stock wild PV1 recovered as a rhinovirus-stock contaminant; explicit curator TRUE | probably **FALSE** — a wild PV1 contaminant is a natural genotype nobody assembled. Not adjudicated here (295/618 nt). Flag. |
| `JN105289`–`JN105295` | 7 | in-vitro-selected drug-resistant variants of named field parents; explicit curator TRUEs | **Q1** |
| `M29182` `M29183` `M30211`–`M30222` | 14 | genuine defective-interfering particle RNAs, 60–179 nt | **Q4** (DI particles arise spontaneously in high-MOI passage — selected, not assembled, and they *do* occur in natural infections) |
| `M14761` | 1 | "Poliovirus (Lansing strain) recombinant junction", 223 nt, `recombinant/lab` | probably TRUE; not adjudicated |
| `S61236` `S65446` `S65447` `S65449` `S65450` | 5 | site-directed deletion mutants / pseudorevertants (`PV1/Delta 8`), 53–68 nt | probably TRUE; not adjudicated |

Of these 30, Appendix B decides 24 (`DQ205099` FALSE; `AJ512791`/`AJ512792` FALSE per Q8;
`JN105289`–`JN105295` TRUE per Q1; the 14 DI RNAs FALSE + reclassified per Q4). **Six were never
adjudicated by anyone** — `M14761` and `S61236`/`S65446`/`S65447`/`S65449`/`S65450`. That is a small,
closable gap and it should be closed before the rule rewrite flips them, not after.

**Three more unadjudicated records carry active TRUE curation rows, and one of them is load-bearing.**
`JC013129` (179 nt), `MA400487` (672 nt) and `DD214215` (7,456 nt — in the 58, adjudicated FALSE in
§4, but its row says TRUE) all sit outside anything Appendix B decided, or contradict it.

`JC013129` deserves naming because its situation is subtle: the ledger asserts TRUE for it, its
byte-identical twin `DI499172` has **no row**, and `DI499172` ships TRUE only because of the blanket
`\bPAT\b` bug. So the group is coherent *by accident of the defect this report exists to remove* —
the ledger-coherence check finds nothing wrong today, and the moment the rule rewrite lands the group
splits. It is the one case where "or agree with what the rest already ships" licenses something that
will not survive the change it is being checked against. Adjudicate it in the same pass as the six
above, not after the rewrite.

**Recommended landing sequence**, because 516 flips in one commit is not gate-diffable by eye. Step 1
is done; steps 2–4 restated against Appendix B's numbers:

1. ~~Land **Invariant A** (§7)~~ — **done**, and the design changed under adversarial review. A turned
   out to have no independent detection power (all 513 PAT/SYN records ship TRUE, so three
   neighbouring checks entail its green), and the live D2 defect is a *ledger*-vs-canonical split that
   no canonical-only check can see. What landed is Invariant B as a pinned violator set plus a
   **ledger-coherence check** — the earlier *differential* formulation was removed for being blind
   across the 280 records inside the 12 groups canonical already splits. See
   [`tests/test_engineered_invariants.py`](../tests/test_engineered_invariants.py).
2. Land the **42 + `A09260` = 43** flips **in the private `manual_review_overrides.csv`**, not as
   public ledger rows — the D2 episode's lesson is that a ledger assertion with no counterpart in the
   applied source of truth never takes effect. Note what this step is *not*: `LY501107`/`LZ216102`
   already hold TRUE and need nothing. What it needs instead is **retiring** four active TRUE rows
   that contradict §4 (`AJ512791`, `AJ512792`, `DD214215`, `DD214221`), **correcting** `CS406483`
   from FALSE to TRUE, and **adding** one row for `PU749298`.
3. Land the rule change as a **separate, gate-diffed commit**, staged by length band
   (`≥3000` first — it should be a no-op against step 2 — then `900–2999`, then `<900`), with the
   diff asserted to touch exactly the predicted accession set at each stage.
4. Handle the Q5 vaccine-source set, the Q5 carve-exclusion of `FV537075`–`FV537077`, and the **six
   unadjudicated VRL records** above as their own passes.
5. Adjudicate `CS406433` (backlog B1) and decide whether the 456 sub-3000 nt PAT records get a
   positive-evidence pass or ride the rewrite wholesale.

### 8.6a Residuals left by the concurrent private pass (2026-07-29)

Not created by this report and outside its ≥3000 nt population, but found while remapping against the
private repository's commit `f848530` and recorded so they are not rediscovered from scratch. Both are
cases where fixing part of a byte-identical group left the rest inconsistent:

| sha256 group | what happened | residual |
|---|---|---|
| the 2,643-nt group: `HZ411066`, `LG059180`, `LQ076634`, `MA816556`, `FW503126`, `HI553343`, `HZ037987` | the four with override rows moved to `wild`/`human`/`vaccine/reference`; the other three were left | `poliovirus_classification` now disagrees **three ways** across byte-identical records — `wild` ×5, `engineered/lab` (`FW503126`), `reference/lab` (`HZ037987`) |
| `DI499171`/`JC013128`, `DI499173`/`JC013130`, `DI499174`/`JC013131`, `DI499175`/`JC013132`, `DI499176`/`JC013133` | classification was aligned on the `DI499*` side | `origin_class` and `sampling_frame` **agreed before and disagree now** — one disagreement traded for two |

Also worth noting: the residual that pass set out to shrink (`engineered=TRUE` shipping a field-epi
classification) went **47 → 50**, because fixing 7 records' classification pulled 7 new records into
the residual while removing only 4.

### 8.7 Three latent hazards found while reading the rule layer

1. **There are two live, different definitions of `engineered_or_construct` in the same directory.**
   `extract_genbank_metadata.py:450-481` computes the column from its **own** 13-pattern list (it has
   `\bconstruct\b` and `nonfunctional VP1`, which `CONSTRUCT_PATTERNS` lacks; it lacks `\bsynthetic\b`,
   `\bmutant\b`, `\bclone\b`, `\bPAT\b`, `\boligo…\b`, `defective[- ]interfering`, and
   `modified microbial nucleic acid`; and it has **no veto**) and writes it as a bare
   `engineered_or_construct` column into `genbank_metadata.csv` at `:680`. Nothing downstream reads
   it — it is not in `blob()`'s field list and not in `RECORD_LEVEL_FIELDS`. Two columns of the same
   name with different semantics in the same working directory is a trap that will eventually be
   read by the wrong consumer. Recommend renaming it (`engineered_or_construct_extract_raw`) or
   deleting it, independent of everything else here.
2. **`infer_sampling_frame():727` writes patent provenance into a surveillance field, at "high"
   confidence, `locked_from_genbank`, and it is not veto-able.** Q8's answer says patent provenance
   should live in `division` at the source layer and `surveillance_stream` should describe what the
   record is. Line 727 does the opposite. It is *not* uniformly harmful today (it short-circuits at
   `:725` for non-polio records, which is why the CVA11 quartet ships `not_applicable`), but it is
   what will keep re-deriving `engineered/lab` for `DQ205099` and `HV202313` after their
   `engineered` rows are patched, unless the ledger rows also set `sampling_frame`. **Any ledger patch
   for the flip set must set `sampling_frame` explicitly, or line 727 must change too.**
3. **`review_genbank_reference_or_construct.csv` records `evidence = "No named reference strain in
   GenBank text"` for the S19 six** — i.e. the review queue's own evidence field says the opposite of
   what the six records' reference title says ("Six New S19 Poliovirus **Reference Strains**"). Not
   load-bearing for `engineered`, but it is the kind of contradiction that survives a rename.

---

## 9. Open questions for the curator — numbered, most consequential first

Only genuine judgment calls that survived the evidence-gathering. Everything I could settle by
measurement, I settled.

**Q1. Is a laboratory-*selected* variant `engineered`, or only a laboratory-*assembled* one?**
This is the one question that decides records I cannot decide, and it governs **at least 11 canonical
records that carry your own explicit TRUEs**: `LY501107`/`LZ216102` (CAVA cold-adapted, 24 nt from
Saukett) and `JN105289`–`JN105295` (in-vitro-selected drug-resistant variants of named AFP field
parents). Your definition's clause (a) is "someone **assembled** that specific genotype". A cold
variant selected by low-temperature passage, or a resistant variant selected under drug pressure, was
**not assembled** — so clause (a) fails and they go FALSE, which is my §3E proposal. But that reading
makes `engineered` silent about a whole category of deliberate strain construction, and I doubt that
is what you want.
*If "selected counts as engineered":* `LY501107`/`LZ216102` and `JN105289`–`JN105295` keep TRUE (only
their reason strings need fixing — see Q2), and `LY501105`/`LZ216100` become arguable too.
*If only "assembled" counts:* all 11 flip FALSE, and the dictionary should say so explicitly, because
a reader will not guess it.
Note this is the prior report's §6.2 restated with real records attached; it was not among the ten
you answered.

**Q2. `LY501107`/`LZ216102`: the recorded reason is now measurably false. Replace the reason, the
conclusion, or both?**
Your override says *"CAVA (Cold-Adapted-Viral-Attenuation) patent construct"* and the C1 write-up
justifies it as *"12.3% from all PV3"*. I reproduce the 12.3% (vs Leon 12a1b) — but `PP972258`
(Saukett/A_NIBSC) entered the database in 2024, after C1 built its panel, and **`LY501107` is 0.327%
from Saukett**, with 18 of its 19 unambiguous differences individually attested in natural field
isolates and no unique canonical restriction site. Meanwhile the 24 positions *do* fall in the 5'UTR
and 2C/3D regions where C1 says the paper places the CAVA mutations — which is real evidence *for*
keeping TRUE. So: the reason is definitely wrong; the conclusion is genuinely open. My
recommendation is to correct the reason regardless, and to hold the conclusion until Q1 is settled,
since Q1 decides it.

**Q3. When a re-deposit's parent is a field isolate, what `surveillance_stream` does it inherit?**
Q8 said `vaccine/reference` for the Sabin/MEF-1/patent re-deposits. But three of the flip set have parents
that are **AFP/clinical field isolates**: `DD214218` (parent `K01392`, PV3 Leon/37) and
`PE314016`/`PH149759` (parent `AF111984`, wild PV1 CHN-Jiangxi/89-1, `AFP/clinical`). Literally
inheriting the reference's label would create three fake AFP surveillance records out of patent
deposits — worse than the `not_applicable` they ship now. Options: (a) `vaccine/reference` for all
re-deposits regardless of parent (my lean — it reads as "reference deposit"); (b) keep
`not_applicable`; (c) a new value. Same question applies to `LY501107`/`LZ216102` if they flip
(parent `PP972258` ships `AFP/clinical`).

**Q4. Are the 14 defective-interfering-particle RNAs (`M29182`, `M29183`, `M30211`–`M30222`)
`engineered`?** They currently ship TRUE and are 60–179 nt. DI genomes arise **spontaneously** from
polymerase error during high-MOI cell-culture passage — nobody assembles them — and DI particles do
occur in natural infections. So clause (a) fails and arguably clause (b) too. But they are also
plainly artefacts of laboratory passage and would be misleading as `FALSE` field data. They are below
my 3000-nt cut so I did not adjudicate them; I raise them because the rule change in §8 flips all 14
and you should decide rather than have it happen. (Related: this report proves `DD214215`/`DD214221`,
which came from a *DI-particle patent*, are **not** DI genomes at all — `DD214215` has zero internal
gaps against Mahoney. Q6 already settled those two.)

**Q5. Should `FV537075`/`FV537076`/`FV537077` be in the canonical set as poliovirus genomes at all?**
Your existing C1 call was *"22–26% divergent; Mike: keep construct"*. I can now tell you exactly what
they are: **`FV537075` is Mahoney with every C→T, and `FV537076` = `FV537077` is the reverse
complement of Mahoney with every C→T** — the arithmetic is exact (3523 = 1786 + 1737; 3917 = 2206 +
1711; 1737 mismatches = Mahoney's C count; 1711 = Mahoney's G count). The patent is "Modified
Microbial Nucleic Acid" (JP 2009538603-A, Millar). These are **bisulfite-converted reference
strings**, not virus genotypes. So the 22–26% is not divergence at all. `engineered=TRUE` is
technically right (a C-less poliovirus is not a natural genotype) but it will read to any consumer as
"lab-made virus". More urgently they ship `organism=Poliovirus 1`, `sequence_scope=complete_genome`
and sit in `sequences.fasta.gz`, so any whole-genome PV1 MSA will ingest three C-less
pseudo-genomes — **and two of them in reverse-complement orientation.** Given the `POLIO_unified` MSA
work, my recommendation is `engineered=TRUE` *plus* a scope/status change that keeps them out of
sequence products. Your call on which mechanism.

**Q6. The Q5 29-record exempt list needs an explicit allowlist, and it is two categories, not one.**
Verified against canonical: **7 of the 29 have a blank `strain_name`**, so the stated test ("populated
`strain_name` matching a known vaccine seed strain") does not select them — `J02283`, `X00595`,
`X00596`, `X00925` name their strain only in `definition`, and `MZ245455`, `OR253701`, `OR253702` are
**nOPV designed strains**, a completely different justification (they are engineered by the ordinary
clause-(a)+(b) test, exactly like `MN654096`, which already ships TRUE). Conversely a naive
vaccine-seed regex over `strain_name` matches **653** canonical records, because hundreds of
Sabin-like *field isolates* carry `strain_name` values like `Sabin 1` or `vaccine`. So: (a) the 29
need to be a locked allowlist, not a rule; (b) the 3 nOPV records should be recorded under the
ordinary test, not the vaccine-source convention; and (c) **`AY082681` (`strain_name='FOX3'`) is
byte-identical to `AY082682` (`LederleIII`), which *is* in the 29** — if `AY082682` flips TRUE and
`AY082681` does not, that group becomes a new same-sequence contradiction. Likely omission worth
checking.

**Q7. Do you want `A09260` added to this flip set?**
It is a 900-nt PAT VP1 fragment, byte-identical to **234 natural Sabin-like records**, shipping TRUE
against their FALSE. It is the twelfth and only sub-3000-nt failure of Invariant B, and it is exactly
the same class of re-deposit as the flip set. Including it makes Invariant B land green with an **empty**
allowlist; excluding it means the invariant needs an allowlist entry on day one. I did not include it
in the 58 because it is below the length cut, not because it differs in kind.

**Q8. `AJ512791`/`AJ512792` — your explicit TRUE looks wrong under the new definition.**
Your override note reads *"NCPV#0240 lab stock: wild-type PV1 recovered as a contaminant of typed
rhinovirus working stocks — laboratory-containment report, not a field isolate."* That is a true and
useful statement about the *record*, but the *genotype* is wild-type PV1 that nobody assembled. Under
the simplified definition both clauses fail → FALSE, with the containment context living in
`surveillance_stream`. These are 295 and 618 nt so outside my adjudicated population and I did not
measure them; I flag them because the §8 rule change flips them and because they are the same
"provenance vs genotype" confusion the whole exercise is about.

**Q9. `E01570`/`E01571`/`E01572` carry `organism_name = Homo sapiens` (taxid 9606).**
All three are Sabin cDNA clone deposits from JP 1988094980-A, yet their source `/organism` is *Homo
sapiens*. They ship `poliovirus_classification=Sabin` in canonical, so the polio call is right, but
`organism_name` is a human. Not an `engineered` question — flagging it because I found it while
adjudicating them and it will confuse anyone who groups by organism. (Similarly `PE314016`/`PH149759`
ship `organism_name=unidentified` with a patent `COMMENT` reading `OS Enterovirus Human Poliovirus`.)

**Q10. Dictionary wording for the rename (Q7 of the prior report) needs the natural-occurrence
nuance this report uncovered.** The rename to `engineered` is being tracked separately, but three
findings here should land in the definition text, because without them the column is
under-determined: (i) **individual-difference attestation is not genotype attestation** — six records
here are FALSE because each of their differences occurs in nature, though no single natural record
carries the combination (§5.3); (ii) **the character of the differences is the test, not the
distance** — `CS406483` is TRUE at 6 nt and `PP068133` is TRUE at 12 nt, while `LY501107` is proposed
FALSE at 24 nt and `PP068136` is TRUE at 315 nt; (iii) **the label-inheritance rule needs a
field-by-field statement**, because `engineered` is judged on the record's own evidence while
`classification`/`sample_origin`/`surveillance_stream` are inherited from the reference — and Q3
above shows inheritance is not always literal.

---

## Appendix. Reproduction

All measurements are reproducible with `stdlib` + Biopython from the public repo alone. Every number
in §1–§4, §6, §7 and §8.6 came from the public artefacts only; the private repo was read (read-only)
solely for the **rule source** (§8.1–§8.5, §8.7), the **existing curator decisions** cited in §3F and
§5.1, and the source-layer TRUE counts (954 / 959) in §8.1, which I attribute rather than re-derive.
Working scripts (throwaway, in the session scratchpad, not
committed anywhere): a nearest-natural-neighbour k-mer screen, a windowed mosaic mapper, an
end-gap-free pairwise comparator with per-difference output, a 13-mer natural-occurrence tester, and
a 49-enzyme restriction-site delta scanner with per-position attribution. The four load-bearing
assumption-free results — 25 sha256 identities, 3 exact containments, the `FV5370xx` base-count
arithmetic, and the S19 capsid-interval confinement — need none of that machinery and can be checked
with `str.find()`, `collections.Counter` and a single alignment.

---

## Appendix B. Curator answers, 2026-07-29 — DECIDED

The ten questions in §9 are answered. Recorded verbatim, because these are the decisions the
implementation is executing against and the reasoning behind several of them is not recoverable
from the resulting data.

| Q | answer (curator, verbatim) | effect |
|---|---|---|
| Q1 | "engineered. revise my criterian to be coherent with what we're actually doing" | **Directed selection counts as engineered.** `LY501107`/`LZ216102` and `JN105289`–`JN105295` keep TRUE. Criterion restated below. |
| Q2 | "correct reason. Keep 'engeineered'" | Replace the stale `12.3% from all PV3` reason; conclusion unchanged (TRUE). |
| Q3 | "choice A" | `surveillance_stream=vaccine/reference` for **all** re-deposits regardless of parent — no fake `AFP/clinical` records. |
| Q4 | "tag as defective-interfering-particle. it's native of interest" | The 14 DI RNAs → `engineered=FALSE`, `poliovirus_classification=defective-interfering particle` (existing controlled value). |
| Q5 | "drop them from all final data with reason, as we have done occasionally elsewhere" | `FV537075/76/77` → `carve_exclusions_confirmed.csv` with reason. Not an `engineered` fix. |
| Q6 | "I support what you describe." | Locked allowlist for the vaccine-source set; the 3 nOPV recorded under the ordinary clause test; check `AY082681`. |
| Q7 | "yes" | `A09260` joins the flip set → Invariant B lands green with an **empty** allowlist. |
| Q8 | "I agree with you" | `AJ512791`/`AJ512792` → FALSE; containment context moves to `surveillance_stream`. |
| Q9 | "organism is poliovirus (or whatever we use). override" | Override `organism_name` on `E01570/71/72` (`Homo sapiens`) and `PE314016`/`PH149759` (`unidentified`). |
| Q10 | "yes record" | The three nuances land in the dictionary definition text. |

### The revised criterion (Q1)

Replaces the round-1 definition. The round-1 wording said only "assembled", which would have made
the column silent about directed selection — the curator's Q1 answer corrects that.

> **`engineered`** — someone deliberately produced this specific genotype for a stated purpose,
> either by **physical assembly** (a designed construct, a recombinant chimera, a synthesised
> sequence) **or by directed selection under an applied selective pressure** (serial passage
> specifically to select for cold-adaptation, drug resistance, or another intended phenotype). The
> genotype does not arise through ordinary undirected replication, transmission, or passage-lineage
> drift.
>
> A record is **not** `engineered` merely because:
> - it was **patent-deposited or re-deposited** from an existing reference — replicates take that
>   reference's label;
> - it arose **spontaneously without directed selection** — e.g. a defective-interfering particle
>   produced by polymerase error during high-MOI passage (real, worth tagging, not engineered);
> - it is an ordinary **lab-stock or passage-lineage variant** with no purpose-driven distinguishing
>   feature.
>
> Three qualifications that are load-bearing and not inferable from the value alone (Q10):
> 1. **Individual-difference attestation is not genotype attestation.** Six records here are FALSE
>    because each of their differences occurs in nature, although no single natural record carries
>    the combination.
> 2. **The character of the differences is the test, not the distance.** `CS406483` is TRUE at 6 nt;
>    `PP068133` is TRUE at 12 nt; `PP068136` is TRUE at 315 nt; `LY501105` is 11 nt and turns on
>    patent purpose rather than count.
> 3. **Label inheritance is field-by-field, and not always literal.** `engineered` is judged on the
>    record's own evidence, while `poliovirus_classification` / `sample_origin` /
>    `surveillance_stream` are inherited from the reference — except that `surveillance_stream`
>    inherits `vaccine/reference` for every re-deposit (Q3), never a field-isolate parent's
>    `AFP/clinical`.

### Consequential revision to §3E / §5.1 — `LY501107`/`LZ216102` stay TRUE

§3E proposed FALSE for these two under the "assembled only" reading. **Q1 reverses that**: the CAVA
patent's stated purpose is directed cold-adaptation selection, so clause (a) is satisfied by
selection. The disposition table in §4 is therefore wrong for `LY501107`/`LZ216102` — read
**TRUE** there, with the reason corrected per Q2. The measurement that prompted the question (0.327%
from Saukett `PP972258`, panel gap closed in 2024) still stands and still invalidates the *recorded
reason*; it just no longer changes the conclusion.

Totals move from "46 FALSE / 12 TRUE" to **42 FALSE / 14 TRUE / 2 open** for the 58, plus `A09260`
(Q7) as a 43rd flip outside the ≥3000 nt population.

**Arithmetic, spelled out, because an earlier draft of this line said "44 FALSE / 14 TRUE" and that
was internally incoherent** — it counted `LY501105`/`LZ216100` inside the 44 while the subsection
immediately below declares them undecided. A record cannot be both. The reconciliation:

| | n | records |
|---|---:|---|
| flip to FALSE, decided | **42** | the §4 FALSE set minus `LY501107`/`LZ216102` (now TRUE) and minus `LY501105`/`LZ216100` (open) |
| stay TRUE, decided | **14** | 9 of §3F, plus `FV537075`–`FV537077`, plus `LY501107`/`LZ216102` |
| **open, not implemented either way** | **2** | `LY501105`, `LZ216100` |
| total | **58** | |

Of the 14 staying TRUE, only **11 ship a TRUE value**: `FV537075`–`FV537077` are carve-excluded from
`final/` per Q5 and carry no `engineered` value at all.

**The set that lands is 42 + `A09260` = 43 records.** Any statement of "44 flips" is wrong in both
directions at once — too many if the open pair stays open, too few if it resolves to FALSE.

### Still open — one record pair, flagged not decided

`LY501105`/`LZ216100` never had its own numbered question; §3E folded it into Q1's discussion as
"becomes arguable". It is the **same CAVA patent family** as `LY501107` (same directed-selection
purpose) with a weaker measured signature: 11 nt from MEF-1, 10 of 11 attested in nature, the one
unattested position creating no canonical site. Under the revised criterion the patent's purpose is
the discriminating fact rather than the count, which argues **TRUE**. This is not confident and is
not being implemented in either direction until the curator rules.

