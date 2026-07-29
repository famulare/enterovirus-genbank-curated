# Curation registry contract

`registry/decisions.tsv` is the sole authoritative ledger of human curation decisions.
It is intentionally an uncompressed UTF-8 TSV so that it remains readable in GitHub, a text
editor, a spreadsheet, and command-line tools. Generated files under `final/audit/` are release
views and must never be edited by hand.

## What the row count does and does not mean

The ledger has **2,756 rows**. Read that number carefully:

- It migrates from **2,214 input rows** across ten hand-maintained registries, because one curator
  row can assert several fields (`manual_review_overrides.csv` alone: 1,944 rows → 2,467 decisions,
  one per non-empty column).
- Those 2,214 rows carry only **310 distinct rationales** across all ten registries. The bulk
  registry, `manual_review_overrides.csv`, accounts for 1,944 of the input rows but just **249
  distinct `note` strings** and 78 distinct sources, with one batch of 387 rows sharing a single
  note and PMID.

So "2,756 decisions" is an accurate count of *field-level assertions* and would be roughly a 9×
overstatement of *human judgments*. It is not a measure of curation effort.

Reconciliation against release 2.1.5, which shipped 2,753 rows in
`final/audit/manual_decisions.tsv.gz`:

| | rows |
|---|---:|
| shipped in v2.1.5 | 2,753 |
| shipped decisions absent from this ledger | **0** |
| added here (see D2 below) | +3 |
| **ledger total** | **2,756** |
| — of which `active` | 2,736 |
| — `retired` (redundant duplicates) | 17 |
| — `superseded` (D2) | 3 |

## Migration decisions

**Verbatim text.** The release synthesizes `reason` and `evidence_reference` as
`"{column}: {value} | {column}: {value}"` with whitespace collapsed. The ledger instead carries what
the curator actually typed, so reason text differs from the shipped artifact by design.

That deviation does **not** weaken the parity gate. The release's synthesis is a deterministic
function of curator text, so it inverts: `tests/test_decision_ledger.py` rebuilds every shipped
`reason`, `evidence_reference`, `confirmed_by`, `accession` and `source_artifact` from the ledger
alone and compares all of them, plus recomputes every `decision_id` digest. The only permitted
difference is the six repaired reasons below, and only in the direction of the ledger holding more
text than the release.

**Repaired data loss.** `polio_recovery_confirmed.csv` has a trailing comma in its header and, in six
rows, a Python list repr in the resulting unnamed column — an earlier tool split the note on a comma
and stringified the remainder. The release dropped it, shipping six truncated reasons, one ending
mid-phrase at `(<50nt`. They are rejoined here on the original comma; e.g. `KY748286` recovers
`, Nigeria 2015`.

**Typographic quotes, so naive tools work.** This is the one deliberate change to curator text
beyond the repair above. 70 ASCII double quotes across 35 `reason` fields — e.g. `paper title
explicitly says "circulating"` — are converted to typographic pairs (`“ ”`). Written with a standard
csv writer, ASCII quotes would force those fields to be wrapped and their inner quotes doubled: valid
RFC 4180, but it leaves escaping artifacts that `cut -f`, `awk -F'\t'` and hand-inspection get wrong.
With typographic quotes the standard writer has nothing to quote, so the file is both
standards-correct and safe to split naively. Every occurrence was balanced, so pairing is
unambiguous; an odd count raises rather than guessing. Curator text already contains em dashes, so
no new Unicode class is introduced.

The guarantee is enforced, not documented-and-hoped: the migration refuses to finish if the written
file contains a double quote or if naive tab-splitting yields inconsistent field counts, and
`evgc validate-ledger` re-checks the same property on every read.

**`decision_id` excludes `source_artifact`.** Previously the bare source filename was hashed into the
identity, so moving a registry to a public path would rehash every id. Ids are recomputed once here
from `(decision_type, subject_key, field_name, new_value)` and are then stable against file renames.
All 2,756 are unique.

**Subject attributes are carried as attributes, not as evidence.** The release wrote
`evidence_reference = "reference_label: Sabin1 | serotype: 1"`, but a reference's name and serotype
are properties of the subject, not evidence for the claim. They are still carried — dropping
curator-recorded values would be data loss — as **labelled attributes** in `notes`:
`reference_label=Sabin1; serotype=1`, and `linked_sibling=AJ783802` for isolate linkage.

The label has to be carried explicitly. `reference_label` coincides with `subject_key` for exactly
one row (Lansing, the accession-less negative assertion); relying on that would have silently lost
the names Sabin1/2/3, Brunhilde, MEF1, W2, Leon37, Saukett and CHAT for the thirteen rows that do
have an accession.

Attributes keep their column name because `notes` has no schema — an unlabelled `2` preserves the
value and erases its meaning. This is not the synthetic prefixing stripped from `reason`: there the
prefix wrapped the curator's own prose; here it names a structured field that would otherwise be
anonymous. `key=value` rather than `key: value` keeps the two visually distinct.

`legacy_accession_classification_overrides.curation_source` is the constant `legacy_accession_override`
on all 30 rows — pure provenance, already carried by `source_artifact` — so it is not duplicated.
Blank `evidence_reference` therefore rises from 206 rows to 250.

**D2 — CS406436 / CS406482 / CS406483.** These carried genuinely contradictory live decisions:
`classification=engineered` from the 2015 legacy bridge ("codon-deoptimized MEF1") against
`classification=wild` from the 2026 full-genome review. Measured divergence from MEF1 (AY238473)
is 4 nt over 6,621 aligned nt for CS406436, and 4 nt and 6 nt over 7,435 for CS406482 and CS406483 —
0.05–0.08%. That rules out codon deoptimization, which rewrites synonymous codons wholesale and
would give hundreds to thousands of substitutions. Both analyses cite the same patent
(WO2006042156), so these are the **parental** MEF1 deposited within an engineering patent.
Adjudicated by the curator: the legacy rows are `superseded`, and an explicit
`engineered_or_construct=FALSE` is asserted. Canonical already ships `wild`, so **no scientific
output changes**. These three new assertions are the entire difference between 2,753 and 2,756.

## Status vocabulary

The three values are used with distinct meanings, not interchangeably:

- `active` — the governing assertion.
- `superseded` — a call that was **contradicted** and overturned. Currently only the three D2 rows.
- `retired` — withdrawn from force **without** being contradicted. Used for the 17 (subject, field)
  pairs that two registries assert with the *identical* value: the same human judgment recorded
  twice, not a conflict.

When two registries assert the same field for the same subject, precedence is declared, not
inferred: `canonical_reference_confirmed.csv` (purpose-built for canonical-reference calls) >
`manual_review_overrides.csv` (current human curation) > `legacy_accession_classification_overrides.csv`
(machine-generated 2015 bridge). Where two registries *disagree* on the value, the migration raises
rather than applying precedence — adjudicating a scientific disagreement silently is how a curation
database acquires an opinion nobody chose. All 17 current duplicates agree; the only disagreement
was D2, and a human resolved it.

## Fields with no source

`effective_from` and `effective_through` are blank throughout, and `status` is derived rather than
migrated: **no source registry has a date, version, or supersession column.** Inventing effective
dates would be fabrication; `effective_from` could only be reconstructed from git blame, which is a
derived fact about the file, not something a curator asserted.

Supersession that predates this migration is unrecoverable. At least one reversed call (`MK719554`,
which the note says "REVERSES the earlier not-polio call") had its superseded row physically deleted
from the source registry, so the ledger's history begins here.

## Required columns

The exact order is:

```text
decision_id decision_type subject_key accession field_name new_value reason
evidence_reference confirmed_by source_artifact status effective_from effective_through notes
```

The real file is tab-delimited. The wrapped display above is only for readability.

- `decision_id` is a stable `D-<lowercase hex>` identifier.
- `subject_key` is always populated. It is the accession when one exists; otherwise it is a stable
  reference, family, or other accession-less subject label.
- `accession` is unversioned and may be blank.
- `reason`, `evidence_reference`, and `confirmed_by` preserve recorded text. Missing historical
  information stays blank; it is never reconstructed or embellished.
- `source_artifact` records where the assertion came from: one of the ten migrated registry
  filenames, or `curator_adjudication_2026-07-29` for the three D2 rows, which were authored during
  this migration and are recorded in no registry.
- `status` is `active`, `superseded`, or `retired`.
- effective boundaries are explicit strings and may be blank until release-scoped semantics are
  required.

## Ordering and conflicts

Rows are sorted by `decision_type`, `subject_key`, `field_name`, then `decision_id`. Row order never
controls precedence. Two active assertions for the same subject and field are invalid until an
explicit versioned conflict policy exists. Unknown subjects, fields, decision types, or controlled
values fail closed.

## Generated audit relationship

The future pipeline will generate:

- `final/audit/manual_decisions.tsv.gz`: normalized release view of the ledger;
- `final/audit/decision_applications.tsv.gz`: each decision's resolved output effects, including
  before and after values and a non-silent application status;
- `final/audit/canonical_projection_provenance.tsv.gz`: field-level deterministic and manual
  provenance.

CI will require equality of decision-ID sets between the ledger and generated manual-decision
audit, and will reject omitted, duplicated, conflicting, or silently ignored decisions.

## Local validation

Validate the ledger at any time with:

```bash
evgc validate-ledger registry/decisions.tsv
```

The record-level schema is `registry/schemas/decisions.schema.json`, and it is the *executable*
source of truth: the validator derives the column set and order, the non-blank fields, the
`decision_id` pattern, and the `status` vocabulary from the schema rather than restating them in
Python. Tightening or loosening the published schema therefore changes what CI enforces, and the
two cannot drift apart.

Deterministic rules are a separate concern governed by `registry/schemas/rules.schema.json`; human
assertions must not be encoded as executable special cases.

## Migration

**`scripts/migrate_legacy_registries.py` produced the committed ledger.** It is a one-time
historical tool, not a pipeline stage: it reads the private curation repository once and leaves this
public artifact behind, after which the ledger is the source of truth and nothing in the build looks
outside the clone again. It encodes every decision documented above and refuses to finish on any of
them being violated.

```bash
python scripts/migrate_legacy_registries.py \
  --source-dir ../MAD-VDPV/data/genbank/working
```

Because it needs a private path, CI cannot run it. Its guards — the disagreement raise, the
truncation repair, the quote normalization, the D2 adjudication and id assignment — are covered by
`tests/test_migration_legacy.py` against synthetic inputs instead. It is deterministic: re-running
it reproduces `registry/decisions.tsv` byte for byte.

`scripts/migrate_decisions.py` is the generic normalizer for *future* legacy imports. It refuses to
run when an input file carries a column with no destination in the ledger — silently dropping
curator-entered data is the failure mode this repository exists to prevent. Columns that are
genuinely out of scope must be named explicitly:

```bash
python scripts/migrate_decisions.py legacy/*.csv --output registry/decisions.tsv \
  --drop-columns internal_row_id,spreadsheet_colour
```
