# Clean pipeline architecture

## Objective

A fresh clone must eventually regenerate the release from only declared public inputs:

```text
raw/sequence.gb.zip + registry/ + versioned rules
    -> normalized GenBank source tables
    -> deterministic metadata and sequence evidence
    -> human curation application
    -> canonical, audit, dictionaries, alignments, and manifests
```

This document is an architectural contract, not a claim that the pipeline is complete. The parity
oracle is release 2.4.1 (see `src/enterovirus_genbank_curated/contracts.py`'s
`BASELINE_RELEASE`), which no longer ships: it is preserved under `releases/2.4.1/`. 2.1.5 and 2.3.0
are retired, immutable prior baselines, no longer verified against the tree.

The pipeline has since produced releases of its own, and since 2026-08-01 they are written straight
into `final/` rather than a staging tree; the current one is 5.3.0. 2.4.1's canonical table is kept
as a fixture under `releases/2.4.1/` so `evgc parity-canonical` can hold the delta to a declared
per-class transition table. It is an output measured against that oracle, not a replacement for it.

## Non-negotiable boundaries

1. Existing `final/` files are never pipeline inputs. Until 2026-08-01 they were comparison
   targets and the build could not write them either; `final/` is the build's own destination now,
   and the refusal that remains — enforced by `sandbox.READ_REFUSED_DIRS` — is on *reading* a file
   the build did not write in this run. That was always the half that carried the property: a build
   that reads the previous canonical table can reproduce it perfectly and prove nothing.
2. The build may not read undeclared absolute paths, home directories, private repositories, or
   mutable external workbooks.
3. Deterministic behavior belongs in versioned rules and code. Human assertions belong only in the
   curation ledger.
4. Duplicate, conflicting, missing, or ambiguous inputs fail closed.
5. Every canonical value must have machine-readable projection provenance.
6. A superseded release is retired, not rewritten. 2.4.1's parity contract and its eighteen
   alignment files are preserved under `releases/2.4.1/`, where `alignment-shape` still measures the
   declared delta against them. The `release/<version>/` staging tree is gone: it existed so a build
   could be reviewed without touching an immutable `final/`, and with `final/` as the destination it
   was a second copy of the same bytes to keep in step.
7. What is left of the oracle is re-derived on every CI run and cannot be edited to accommodate a
   build that disagrees with it: the raw archive is authenticated, the build manifest is checked
   against it, the release manifest's own hashes are recomputed, and the carried files are re-hashed
   against pins in code. What retired with the promotion is the half that compared `final/` to
   2.4.1's declared hashes and row counts — `final/` does not hold 2.4.1 any more, so those checks
   could only have been kept by rewriting the numbers to match the build, and a contract rewritten
   from the thing it gates is not a contract.

## Package boundaries

The intended package is `src/enterovirus_genbank_curated/` with these responsibilities:

- `raw`: authenticate and safely extract the frozen GenBank archive;
- `genbank`: parse records and emit normalized source relations;
- `registry`: load, validate, and conflict-check decisions and rules;
- `derive`: compute metadata, typing, classification, and sequence evidence;
- `curate`: resolve subjects, apply decisions, and create disposition/provenance records;
- `export`: write canonical, audit, dictionary, alignment, and manifest artifacts;
- `validation`: enforce referential closure, parity, and determinism.

All seven exist. `derive/metadata.py` covers the canonical columns whose value is a source value —
13 of the 26 — and `derive/typing.py`, `derive/classification.py`, `derive/engineered.py`,
`derive/scope.py` and `derive/evidence.py` cover the 13 that are computed.
`derive.metadata.PENDING_COLUMNS` is **empty**: a release fills 26 of 26. `sequence_scope` was the
last, and `derive/scope.py` explains why it stayed unwritten so long — the determinant is a record's
own annotation, not coverage geometry.

One package is not in that list because it is not part of the build: `oracle` is the only place
permitted to read `final/` or `releases/`. Boundary 1 used to be enforced by care alone, with release
reads sitting in the same modules as build code, so `build.py` transitively imported code that reads
the comparison target. Now the comparators live in `oracle/parity.py`, the release verifiers in
`oracle/release.py`, and three mechanisms keep it that way: `tests/test_module_boundaries.py` refuses
a release path literal or an `oracle` import under `derive/`, `curate/`, `export/`, `registry/`,
`genbank/` or in `build.py`/`contracts.py`; `sandbox.READ_REFUSED_DIRS` refuses the read at runtime;
and the `parity-*` verbs build in a guarded child and compare in the unguarded parent.

A second package is also not in that list, for the opposite reason: `align` derives alignment
inputs *from* `final/` deliberately. That was originally because the stages producing them natively
did not exist; now that they do, it is a pinning decision — the alignment layer is anchored to the
2.4.1 release, and "The alignment layer's anchor" in `docs/reproducibility.md` measures what that
costs. It is oracle-adjacent rather than a build module: free to read `final/` and import `oracle`,
exempted from
`test_module_boundaries.py`'s build-tree rule by name rather than by accident. `align/contract.py`
carries one exception to its own exemption, by decision (2026-07-30): it may not redeclare a `final/`
path itself, only import one already declared in `oracle.parity`, which a dedicated test enforces.

## The alignment layer today

`align/` makes each alignment's row set derivable from `final/canonical/` and `final/audit/` alone:
`evgc alignment-population` prints all six populations and their tier/family breakdowns from
metadata, with no aligner installed. Since 2026-08-15 those are 5.0.0's populations — `final/` is
this pipeline's own release — and they are **not** 2.4.1's; see
[`reproducibility.md`](reproducibility.md) for the measured delta and why it is the point rather
than a defect. The native toolchain (`mafft`, Infernal) is declared once in `pixi.toml`, pinned twice
(statically via conda-meta, dynamically via each binary's own self-report) in
`registry/toolchain.json`, and checked by `evgc alignment-toolchain`. The ten NCR covariance models
the structural block needs (four genus-wide, six per-serotype Sabin-anchored) are committed as
inputs-of-record under `registry/alignment_seeds/` and hash-gated by `evgc alignment-verify-seeds`,
so a routine build needs no compiler and no network; the full from-scratch rebuild path
(`scripts/setup_mxscarna.sh`) exists behind a file-presence gate and is not expected to run even on
a fresh clone. `evgc alignment-build` then produces artifacts into `derived/alignments/` (strictly
one at a time — concurrent aligner processes are what exhausted memory on a real machine), `evgc
alignment-verify` gates them against metadata-derived populations with no aligner installed, and
`evgc alignment-shape` writes the shape report and the declared delta against 2.4.1.

All six declared populations are built, at one parameter set, from the 5.0.0 canonical table, and
promoted into `final/alignments/`. The previous state — five artifacts, two parameter sets, no
`EV_unified` at all — is what made the promotion worth doing rather than a rename. Each artifact's
`.provenance.json` records its own parameters, row set digest and tool identity.

### The indel repairs, 2026-08-16

An audit of `EV_unified`'s and `NPEV_unified`'s indel structure by serotype found that **92% of the
subtype-level indel signal in EV, by codon, was artifact** — 338 signatures over 4,882 codons, of
which 134 over 399 codons survive once the records producing them are set aside. NPEV was 96%. Four
repairs, all of them in the segmentation and seeding stages rather than in MAFFT's parameters:

1. **The inferred reading frame is chosen by homology, not by length** (`align/segment.py`). The
   6-frame fallback took the longest stop-free run, which is a coin flip about whether the run is
   protein; it lost the flip for 51 `EV_unified` records and 20 `NPEV_unified` ones, including the
   whole `OR538731`-`OR538740` PV3 cluster, whose seven rows alone held open ~155 of `EV_unified`'s
   319 low-occupancy codon columns.
2. **A record no frame of which reads as protein leaves the CDS block** and offers its sequence to
   the 5'NCR block instead. 1,351 records take this route; 99.9% of the ones that map to a reference
   at all are 5'UTR amplicons, which were previously given a spurious ORF in the CDS block *and*
   refused by the NCR blocks. A record neither pool recognises — 116, mostly tiny patent deposits —
   places nothing, which is what `method="none"` now means.
3. **Four RefSeq rhinovirus polyproteins join the seed** and are removed before backtranslation
   (`align/exemplars.py`, `registry/alignment_seeds/clade_exemplars.fa`). No RV-A or RV-B record in
   this corpus can reach `seed_min_aa`, so 456 rows were aligned against a seed holding no member of
   their own species. A type with no seed exemplar had residues exiled more than 200 codon columns
   from its own block at 8.4%, against 0.14% for a type that has one.
4. **A padded assembly gap leaves the ORF before alignment**. A run of 30 or more wholly-ambiguous
   codons is dropped; 50 records are affected, 39,528 nt in total. The count survives per record in
   the coverage sidecar's new `unsequenced_nt` column, which is what keeps "gap because unsequenced"
   distinguishable from "gap because deleted".

Every threshold these introduce sits in a measured gap rather than at a tuned value; the
measurements are in `CodonSpec`'s own comments, and each repair is named in the artifact's
`parameter_departures`.

### Two more, 2026-08-17

Investigating what the first four left behind found two defects the first four could not express,
and both took the same shape as repair 1: geometry proposes, homology decides.

5. **An amplicon spanning the 5'UTR/capsid boundary is cut at the boundary** (`segment._boundary_cut`).
   `OR538737` is one 897 nt deposit that reads stop-free in a single frame end to end, so all of it
   arrived as one candidate ORF and 504 nt of 5'UTR went into the CDS block with the 393 nt of
   capsid, holding `POLIO_unified`'s first 462 columns open with no other row in any of them.
   Repair 2's choice was all-coding or all-non-coding, and both are wrong about a record that is
   genuinely half of each. The head now goes to the 5'NCR block and the tail stays the ORF. Where to
   cut has no free parameter; whether to cut reuses four thresholds that already meant exactly this,
   so this repair adds no field to `CodonSpec`. It fires on two records — the second, `OM885400`, was
   the largest private-column owner in `EV_unified`.
6. **A cluster of residues MAFFT parked far from its own row, with nothing homologous where it
   landed, is gapped** (`codon.gap_flung_clusters`). `KM486565`'s first seven residues sat 558
   columns from the rest of it where the consensus disagreed 7-for-7, and because ten of the affected
   rows are EV-B77 from one submission the stretched span read as a serotype-wide deletion. Being far
   away is only what makes a cluster worth examining: 43 candidates score either 0.000-0.333 or
   0.667-0.955 with nothing between, and the nine above are genuine bipartite fragments whose halves
   each land on real homology. Which rows lost which residues is named individually in provenance,
   and each row's own count is in the coverage sidecar's new `unplaced_nt` column, because this is
   the only repair that removes residues a deposit really has. `unplaced_nt` needs its own column
   rather than sharing `unsequenced_nt` because it makes the opposite claim about the same kind of
   gap: these nucleotides *were* sequenced and *were* placed, and were removed because the placement
   could not be believed. Without it a gapped row would read as a record with an ordinary deletion —
   the very artifact these six repairs exist to remove.

One residual is deliberately left alone. `OR538735` holds 216 private nucleotides in
`NPEV_unified` because it carries two internal frameshifts — frame +1 reads as protein exactly where
its declared frame does not. That is a property of the deposit, not of this pipeline, and it is not
gateable: 24 records show the pattern, their shares spread continuously with no empty interval, and
ten of them have a *higher* shifted share than `OR538735` while placing perfectly well. Any threshold
that caught it would sweep in the other twenty-three on a tuned number, so it is recorded as a pin in
`tests/test_alignment_placement.py` rather than repaired.

## Public commands

```bash
evgc validate-contracts
evgc validate-ledger registry/decisions.tsv
evgc build-source   --output DIR
evgc parity-source
evgc build-metadata --output DIR
evgc check-declines
evgc parity-canonical
evgc alignment-population
evgc alignment-toolchain
evgc alignment-verify-seeds
evgc alignment-build  --output-dir DIR [--artifact NAME ...] [--threads N]
evgc alignment-verify --output-dir DIR [--artifact NAME ...]
evgc alignment-shape  --output-dir DIR [--artifact NAME ...]
```

The `alignment-*` verbs are named `alignment-<stage>` rather than `build-alignments` /
`parity-alignments` on purpose. There is deliberately no `parity-alignments`: the shipped alignment
bytes cannot be reproduced even in principle, so a verb promising parity with them would be claiming
a symmetry with `build-source`/`parity-source` that does not exist. `alignment-verify` checks the
rebuild against metadata instead, and `alignment-shape` states the declared delta against 2.4.1.

Only `alignment-build` and `alignment-toolchain` need the native toolchain. `alignment-population`,
`alignment-verify-seeds`, `alignment-verify` and `alignment-shape` are all pure Python, which is what
lets the gate run on every push while a build takes hours.

`alignment-build` has no `--parallel` option, and that absence is load-bearing rather than an
omission: no single step of a build needs more than about 0.7 GB, but running several concurrently
reached roughly 50 GB and froze a real machine. Artifacts are built strictly one at a time.
`--threads` defaults to 8, a measured literal rather than `os.cpu_count()`, because the thread count
is a declared parameter recorded in provenance — see `align/runner.py`.

Still planned, and not yet in any form:

```bash
evgc build --release candidate
evgc verify
evgc parity --against releases/2.4.1
```

`check-declines` replaced `parity-metadata` on 2026-08-01. The old verb compared the rebuilt
transport to `final/` cell by cell, which was the right check while `final/` held 2.4.1 and is a
self-comparison now that it holds this build's own output. The replacement makes a claim that needs
no oracle: the build declines exactly where `oracle/parity.py`'s `UNRESOLVED_*` constants say it
declines, per canonical field, including the named zeros. A rule that quietly starts guessing where
it used to refuse moves a number there and fails. The row-set gap is still
declared in code, compared for equality, and invisible to the build; `R-MEMBERSHIP-AA-1` closed most
of it, leaving two records, and the build carves 24,305 rows against the shipped 24,301 — nine the
release excludes and this pipeline admits, less two it leaves undecided and three carve-excluded on
2026-08-14 as laboratory conversions of the Mahoney parental sequence. See
[`reproducibility.md`](reproducibility.md).

## Staged delivery

1. Architecture, schemas, parity contract, migration utility, and CI foundation.
2. Consolidated human-decision ledger migration.
3. Raw verification and normalized GenBank source generation.
4. Retirement — not replacement — of the two frozen legacy upstream stages. Investigating them
   showed there is nothing to rebuild: see below.
5. Deterministic derivation and versioned rules. **Delivered:** the canonical metadata transport
   covers the 13 columns that are source values, the 12 computed columns are
   derived by `derive/typing.py`, `derive/classification.py`, `derive/engineered.py` and
   `derive/evidence.py`, and `registry/rules.json` declares all 39 rules with their thresholds as
   data, regenerating the shipped rule table byte-for-byte. `locality` is projected through the rule
   catalog with its provenance row compared to the release on all nine columns. **No column remains
   unwritten.**
6. Decision application, disposition, and complete provenance. **Delivered:** 6,348 decision
   applications from a 4,939-row ledger, 340,270 provenance rows, and 25,051 declined cells
   collapsed into 268 curation-queue groups. `record_disposition.tsv.gz` gained a producer on
   2026-08-14 and now carries a reason on every one of its 1,422 exclusions.
7. Dictionaries, references, and reproducible alignments. **Delivered.**
   The alignment layer is built natively by this repository (`evgc alignment-build`) from
   `final/canonical/`, `final/source/` and the committed covariance-model core, using only `mafft`
   and `cmalign` — segmentation, the codon-aware CDS block, the Sabin-anchored CDS projection, the
   structural NCR block, stitching and the export writer all exist. `evgc alignment-verify` gates
   the result against metadata-derived populations and `evgc alignment-shape` states the declared
   delta against 2.4.1, both without an aligner. All six populations are built at one parameter set
   from the canonical table and promoted into `final/alignments/`; 2.4.1's eighteen files moved to
   `releases/2.4.1/alignments/`, where they remain the delta baseline. `final/dictionaries/` has had
   a producer since 2026-08-14 (`export/dictionaries.py`).
8. Full fresh-clone parity and deterministic rebuild gate.
9. A new pipeline-native release. **Delivered as 4.0.0:** `final/` is the pipeline's own output,
   and 2.1.5/2.3.0/2.4.1 remain historical and immutable in git and under `releases/`.

## The two frozen legacy stages, and why neither is ported

`final/audit/build_manifest.json` names two private stages as `input_provenance_caveats` — stages
whose external inputs no longer exist, whose outputs the release therefore has to treat as committed
inputs-of-record. Staged-delivery item 4 originally called for replacing them. Neither is being
replaced, and a reader who goes looking for the missing stages should find this section instead.

**`extract_genbank_metadata.py` reduces to 30 committed rows.** It writes three of the four CSVs
carried here — two hand-curated pass-throughs of external files that no longer exist
(`legacy_title_key_table.csv` from a Downloads workbook, `legacy_accession_classification_overrides.csv`
from `amendedClassification.csv`) and one derived join, `legacy_2026_bridge.csv`. The fourth,
`legacy_date_location_extract.csv`, belongs to the other frozen stage below.

Exactly one of the three reaches a canonical value: `legacy_accession_classification_overrides.csv`,
30 rows, all of them migrated into `registry/decisions.tsv` in stage 2. The other two affect nothing
downstream — `legacy_title_key_table.csv` is read by no code at all, and `legacy_2026_bridge.csv` has
five readers that are all evidence, scan or review-queue tooling whose one forward chain dead-ends in
a column nothing consumes. All four files are committed under
[`registry/legacy/`](../registry/legacy/) and pinned by hash, with the per-file reach analysis and
that trace in [`registry/legacy/README.md`](../registry/legacy/README.md). There is no stage left to
port: the human judgments are in the ledger and the frozen files are in the repo.

**`reconstruct_archival_wpv1_dates.py` is dead code.** Verified in stage 4 rather than assumed:

- it writes six CSVs and a summary `.md`, grepping both `to_csv` and the project's `write_csv`
  wrapper, because the script does not use the same writer as the rest of the pipeline;
- **five of the six have zero consumers** anywhere in the private repository;
- the sixth, `legacy_date_location_extract.csv`, is read by one script that uses it for three
  row-count scalars in a summary `.md` — it never reaches the curated master;
- it declares three inputs by absolute path across two *other* repositories, and its hard-coded
  working directory — the location it both reads its third input from and writes every output to —
  is a path inside one of them that does not exist on disk today. Two of the three inputs, a legacy
  dated CSV and an R script in `AfgPak-sequence-analysis`, are present and tracked. The third,
  `genbank_metadata.csv` in `iVDPV-vs-cVDPV`, is absent from that repository's entire git history at
  that path.

That last point is the reason the stage is not reconstructible **now**; it is not evidence that the
stage never ran. `genbank_metadata.csv` is itself a generated artifact, so its absence from git is
equally consistent with it having existed untracked at the time, and the outputs are in fact
committed in the private repo. `final/audit/build_manifest.json` states this narrowly and correctly;
this section is a summary of it, not a stronger claim.

Its scientific conclusions survive as registry rows migrated in stage 2. Porting it would mean
rebuilding a stage that produced nothing anyone consumed.

## Resolved delta: `engineered_or_construct`

This section tracked a disagreement between the ledger and the shipped table while the rewrite was in
progress. It is closed:

- Since 3.0.0 (`30eaaf0`, 2026-07-31) the column is derived by `R-CONSTRUCT-2` instead of the
  inherited `\bPAT\b` text match, which had shipped all 506 patent-division records TRUE. That landed
  the re-adjudication's flips: about 500 records TRUE -> FALSE.
- `FV537075`-`FV537077` are bisulfite-converted reference strings, not genomes, and are
  carve-excluded from 5.0.0 (`e398c61`).
- `DQ205099` is ruled TRUE by an accession-level ledger row (`4b2fb32`). `LY501105`/`LZ216100`,
  which the re-adjudication left open, hold active FALSE rows.
- 45 records ship TRUE, pinned as `EXPECTED_TRUE_TOTAL` in
  [`tests/test_engineered_invariants.py`](../tests/test_engineered_invariants.py).

The reasoning and per-record evidence are in [`engineered-readjudication.md`](engineered-readjudication.md)
and [`engineered-full-population-readjudication.md`](engineered-full-population-readjudication.md).
The lasting lesson is that curation has to land where it is applied, not only where it is recorded,
which is why every decision now reports its outcome in `final/audit/decision_applications.tsv.gz`.

## Review stop conditions

Stop rather than encode guesses when a legacy value cannot be traced, two active decisions conflict,
a subject cannot be resolved uniquely, parity requires undocumented behavior, record membership or
scientific values change unexpectedly, evidence is unsuitable for public release, or an alignment
cannot be reproduced from declared inputs and parameters.
