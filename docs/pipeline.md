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
4. Replacement of the two frozen legacy upstream stages.
5. Deterministic derivation and versioned rules.
6. Decision application, disposition, and complete provenance.
7. Dictionaries, references, and reproducible alignments.
8. Full fresh-clone parity and deterministic rebuild gate.
9. A new pipeline-native release; 2.1.5 remains historical and immutable.

## Review stop conditions

Stop rather than encode guesses when a legacy value cannot be traced, two active decisions conflict,
a subject cannot be resolved uniquely, parity requires undocumented behavior, record membership or
scientific values change unexpectedly, evidence is unsuitable for public release, or an alignment
cannot be reproduced from declared inputs and parameters.
