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

This document is an architectural contract, not a claim that the pipeline is complete. The shipped
release remains the immutable parity oracle while the rewrite is developed — currently 2.4.1 (see
`src/enterovirus_genbank_curated/contracts.py`'s `BASELINE_RELEASE`); 2.1.5 and 2.3.0 are retired,
immutable prior baselines, no longer verified against the tree.

## Non-negotiable boundaries

1. Existing `final/` files are comparison targets, never pipeline inputs.
2. The build may not read undeclared absolute paths, home directories, private repositories, or
   mutable external workbooks.
3. Deterministic behavior belongs in versioned rules and code. Human assertions belong only in the
   curation ledger.
4. Duplicate, conflicting, missing, or ambiguous inputs fail closed.
5. Every canonical value must have machine-readable projection provenance.
6. The current baseline release is never regenerated in place or overwritten; a new schema version
   gets a new `releases/<version>/` and the prior baseline is retired, not rewritten.
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
evgc parity --against releases/2.4.1
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

## Known pending delta: `engineered_or_construct`

Phase A does not rebuild `final/canonical/`, so the ledger and the shipped canonical table disagree.
This is recorded rather than left to be discovered as a parity failure.

**The delta is much larger than the D2 trio, and the earlier statement of it here was wrong in three
ways.** Corrected 2026-07-29 after a full-population re-adjudication
([`engineered-readjudication.md`](engineered-readjudication.md),
[`engineered-full-population-readjudication.md`](engineered-full-population-readjudication.md)):

1. **Not three records — 43, with 2 more unresolved.** Of the 58 canonical records shipping
   `engineered_or_construct=TRUE` at ≥3000 nt, **42** are re-deposits or replicates of an existing
   reference and should be FALSE, plus `A09260` below that length — **43 flips**. Two more
   (`LY501105`/`LZ216100`) are the same patent family as a record the curator ruled TRUE and are
   **open, not implemented in either direction**. 25 of the 42 are *byte-identical* to a natural
   reference that already ships FALSE. Four are not poliovirus (Coxsackievirus A11, in
   oncolytic-virus patents) and three are not viruses at all. The predicate is a text match on
   `\bPAT\b` inside a concatenated blob, so all 506 patent-division records ship TRUE regardless of
   sequence.

   **The 58 is not the whole problem.** Only 58 of the **543** records shipping TRUE were
   adjudicated per-record; the ≥3000 nt floor is a tractability choice, and the rule rewrite will
   flip ~478 unadjudicated records mechanically. `CS406433` (2,745 nt, same patent family as the D2
   trio, verbatim Sabin 2 substring) sits just under the floor and is backlog item B1.
2. **Not one field.** Taking the reference's label also moves `poliovirus_classification`,
   `sample_origin` and `surveillance_stream` on 16 of the 25 byte-identical records. Separately,
   `classification` already disagrees on six records nobody documented (`AJ416942`, `DQ205099`,
   `FJ517648`, `KR259356`, `KR259357`, `KX162685`) — that field feeds reconciliation, so a mismatch
   there is not automatically an error, but it was never true that the disagreement was one field.
3. **"Applying decisions in Phase B flips them" does not hold as written.** The D2 assertion exists
   *only* in `registry/decisions.tsv`. `engineered_or_construct` is **blank** for all three records
   in the private `manual_review_overrides.csv`, which is what the pipeline actually reads, so the
   value is recomputed as TRUE on every rebuild and the ledger row has no effect on it. A ledger
   assertion with no counterpart in the source of truth is not a pending delta — it is a permanent
   one. **Curation has to land where it is applied, not only where it is recorded.** This is the
   single most important lesson of the D2 episode and the reason the re-adjudication's flips are
   being routed through the private overrides rather than added here as more ledger-only rows.

`DQ205099` **is** now part of the delta, reversing the earlier disposition: the annotate-rather-than-
adjudicate call rested on "an infectious clone is a construct", which is exactly the reasoning the
simplified definition removes. Its three differences from Sabin 2 are each independently attested in
natural field isolates.

Eleven records stay TRUE and are genuinely engineered: the `CS406483`/`PU749298` pair (a unique
AgeI cloning site created by two synonymous changes at the VP2/VP3 junction), `MN654096` (nOPV2-CD,
recoded capsid), the six S19 capsid-swap chimeras `PP068131`–`PP068136`, and `LY501107`/`LZ216102`
(directed cold-adaptation selection). `FV537075`–`FV537077` are a fourth, separate case: they are not
poliovirus genomes at all — bisulfite-converted Mahoney reference strings, one a straight conversion
and two the reverse complement — and the disposition is to carve-exclude them from `final/` entirely
with a recorded reason, not to ship them as TRUE. Current counts are pinned in
[`tests/test_engineered_invariants.py`](../tests/test_engineered_invariants.py) so that none of these
numbers can move silently again, which is how the delta grew unnoticed in the first place.

Of those eleven, seven are reachable structurally by `division == "SYN"`. Of the remaining four,
**three already carry active curation rows** — `LY501107` and `LZ216102` hold TRUE (migrated from
`manual_review_overrides.csv`), and `CS406483` holds **FALSE**, which the re-adjudication says is
wrong and which therefore needs *correcting* rather than adding. Only `PU749298` has no row at all.

An earlier version of this paragraph called `LY501107`/`LZ216102` a trap the rewrite would fall
into. They were already held. That mistake is the D2 lesson pointed the other way: reasoning about
what curation ought to say is not a substitute for reading what the applied artifact already says.

**A concurrent private curation pass has partly overtaken point 2.** The private repository's
commit `f848530` moved `poliovirus_classification` / `sample_origin` / `surveillance_stream` on six
records in this population, changing **no** `engineered_or_construct` value. Four of the six moved to
exactly what the re-adjudication planned, so that much of the label-inheritance work is already done.
Two (`PE314016`/`PH149759`) moved the *opposite* way, to `engineered/lab`; the curator adjudicated in
favour of the re-adjudication's FALSE call, since both are `sequence_sha256`-identical to `AF111984`,
a named wild PV1 field isolate. Those two now need correcting private-side.

## Review stop conditions

Stop rather than encode guesses when a legacy value cannot be traced, two active decisions conflict,
a subject cannot be resolved uniquely, parity requires undocumented behavior, record membership or
scientific values change unexpectedly, evidence is unsuitable for public release, or an alignment
cannot be reproduced from declared inputs and parameters.
