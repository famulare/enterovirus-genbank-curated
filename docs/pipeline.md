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

This document is an architectural contract, not a claim that the pipeline is complete. Release
2.1.5 remains the immutable parity oracle while the rewrite is developed.

## Non-negotiable boundaries

1. Existing `final/` files are comparison targets, never pipeline inputs.
2. The build may not read undeclared absolute paths, home directories, private repositories, or
   mutable external workbooks.
3. Deterministic behavior belongs in versioned rules and code. Human assertions belong only in the
   curation ledger.
4. Duplicate, conflicting, missing, or ambiguous inputs fail closed.
5. Every canonical value must have machine-readable projection provenance.
6. Release 2.1.5 is never regenerated in place or overwritten.
7. The parity oracle is re-derived from the shipped release on every CI run. Its hashes, counts,
   and raw-archive identity are recomputed, not taken on trust, so the oracle cannot be edited to
   accommodate a build that disagrees with it.

## Package boundaries

The intended package is `src/enterovirus_genbank_curated/` with these responsibilities:

- `raw`: authenticate and safely extract the frozen GenBank archive;
- `genbank`: parse records and emit normalized source relations;
- `registry`: load, validate, and conflict-check decisions and rules;
- `derive`: compute metadata, typing, classification, and sequence evidence;
- `curate`: resolve subjects, apply decisions, and create disposition/provenance records;
- `export`: write canonical, audit, dictionary, alignment, and manifest artifacts;
- `validation`: enforce referential closure, parity, and determinism.

PR 1 supplies only contract validation and the command-line shell needed to guard later work.

## Planned public commands

```bash
evgc validate-contracts
evgc validate-ledger registry/decisions.tsv
evgc build --release candidate
evgc verify
evgc parity --against releases/2.1.5
```

Only the first two commands are in scope for PR 1.

## Staged delivery

1. Architecture, schemas, parity contract, migration utility, and CI foundation.
2. Consolidated human-decision ledger migration.
3. Raw verification and normalized GenBank source generation.
4. Retirement — not replacement — of the two frozen legacy upstream stages. Investigating them
   showed there is nothing to rebuild: see below.
5. Deterministic derivation and versioned rules.
6. Decision application, disposition, and complete provenance.
7. Dictionaries, references, and reproducible alignments.
8. Full fresh-clone parity and deterministic rebuild gate.
9. A new pipeline-native release; 2.1.5 remains historical and immutable.

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

## Known pending delta: `engineered_or_construct` on the D2 trio

Phase A does not rebuild `final/canonical/`, so the ledger and the shipped canonical table currently
disagree on exactly one field for exactly three records. `CS406436`, `CS406482` and `CS406483` ship
`engineered_or_construct=TRUE`; the ledger asserts `FALSE` under the D2 adjudication. Applying
decisions in Phase B flips them.

This is recorded rather than left to be discovered as a parity failure. It is the only intended
scientific-output change carried by the stage-2 migration, and the reasoning is in
[`registry/README.md`](../registry/README.md). `DQ205099` — the fourth legacy `engineered` call — is
*not* part of this delta: it was annotated rather than adjudicated, precisely because its shipped
values are already correct.

## Review stop conditions

Stop rather than encode guesses when a legacy value cannot be traced, two active decisions conflict,
a subject cannot be resolved uniquely, parity requires undocumented behavior, record membership or
scientific values change unexpectedly, evidence is unsuitable for public release, or an alignment
cannot be reproduced from declared inputs and parameters.
