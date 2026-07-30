# Curation registry contract

`registry/decisions.tsv` is the sole authoritative ledger of human curation decisions.
It is intentionally an uncompressed UTF-8 TSV so that it remains readable in GitHub, a text
editor, a spreadsheet, and command-line tools. Generated files under `final/audit/` are release
views and must never be edited by hand.

## What the row count does and does not mean

The ledger has **2,921 rows**. Read that number carefully:

- It migrates from **2,282 input rows** across ten hand-maintained registries, because one curator
  row can assert several fields (`manual_review_overrides.csv` alone, as of the 2.4.1 resync: 2,008
  rows → 2,620 decisions, one per non-empty column).
- At the original 2.1.5 migration, those input rows carried only **310 distinct rationales** across
  all ten registries — `manual_review_overrides.csv` accounted for 1,944 of the input rows but just
  **249 distinct `note` strings** and 78 distinct sources, with one batch of 387 rows sharing a
  single note and PMID. (Not re-measured at every resync since; as of the 2.4.1 source registries,
  `manual_review_overrides.csv` alone carries 313 distinct notes and 80 distinct sources across its
  2,008 rows — still the same order of duplication, not recomputed further across all ten.)

So "2,921 decisions" is an accurate count of *field-level assertions* and overstates *human
judgments* by roughly the same order as at 2.1.5. It is not a measure of curation effort.

Reconciliation against release 2.4.1, which shipped 2,912 rows in
`final/audit/manual_decisions.tsv.gz`. (For the record: 2.1.5 shipped 2,753; 2.3.0 shipped 2,800 —
the prior public baseline, resynced from at the time; 2.4.0 shipped 2,897 privately but was never a
public baseline, see [`docs/pipeline.md`](../docs/pipeline.md).)

| | rows |
|---|---:|
| shipped in v2.4.1 | 2,912 |
| shipped decisions absent from this ledger | **0** |
| added here, carried forward (D2: 3, AB180070-73: 4, JC013129: 2 — see below) | +9 |
| **ledger total** | **2,921** |
| — of which `active` | 2,895 |
| — `retired` (redundant duplicates) | 17 |
| — `superseded` (all 9 carried-forward rows above) | 9 |

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
All 2,921 are unique.

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
`classification=wild` from the 2026 full-genome review. Divergence from MEF1 (AY238473) is 4 nt over
6,621 aligned nt for CS406436, and 4 nt and 6 nt over 7,439 for CS406482 and CS406483 — 0.05–0.08%.
That rules out codon deoptimization, which rewrites synonymous codons wholesale and would give
hundreds to thousands of substitutions. All three are GenBank division `PAT`
(`Sequence 6/52/53 from Patent WO2006042156`) and both analyses cite that same patent, so these are
the **parental** MEF1 deposited within an engineering patent.

Those figures are **remeasured from the shipped `final/canonical/sequences.fasta.gz`**, by pairwise
global alignment, so a reader of this repository can check them. That is why the denominator differs
from the curator's own rows, which report the same substitution counts over **7,435** positions from
a Sabin-frame multiple alignment that is not carried publicly. Both are right about different
quantities — 7,439 is the comparable positions of the pairwise alignment, and CS406482/CS406483 are
7,439 nt against a 7,440 nt reference. The percentages agree to three figures either way, so the
conclusion does not turn on the choice. The curator's `reason` text is carried verbatim under D1 and
keeps 7,435; the migration-authored `notes` state the remeasurement and its method.

Adjudicated by the curator: the legacy rows are `superseded`, and an explicit
`engineered_or_construct=FALSE` is asserted. These three new assertions are the entire difference
between 2,753 and 2,756.

**What that changes downstream, stated per field rather than in aggregate:**

| field | canonical ships | ledger asserts | effect of applying the ledger |
|---|---|---|---|
| `poliovirus_classification` | `wild` | `wild` (2026 review, `active`) | none — the superseded legacy rows were never the governing call |
| `engineered_or_construct` | `TRUE` | `FALSE` (added here) | **flips on all three records** |

The supersession is a no-op on shipped output; the added assertion is not. This is the one
scientific-output change the migration carries, and it is an approved curation change rather than a
migration error. Nothing in Phase A rebuilds `final/canonical/`, so the flip lands when Phase B
applies decisions — until then the ledger and the shipped canonical table disagree on this field by
design, and [`docs/pipeline.md`](../docs/pipeline.md) records it as a known pending delta.

### Superseded 2026-07-29 — read this before relying on anything above

A full-population re-adjudication has overtaken D2. Two corrections matter enough to state here
rather than only in [`docs/pipeline.md`](../docs/pipeline.md):

**The mechanism refutation above is sound, but the inference from it is not.** "Too few substitutions
for codon deoptimization" is correct — the paper recoded 97% of the capsid — but ruling out *that*
mechanism does not establish that a record is not construct-derived, which is what the column meant.
The conclusion happens to be right for `CS406436` and `CS406482` for a different and better reason:
their 4-nt signature vs AY238473 is shared by patent families with no relationship to this one, so it
is lab-stock lineage. **`CS406483` is not parental and D2 was wrong about it** — it carries two
further synonymous third-position changes at the VP2/VP3 junction that create an `AgeI` site found in
exactly 2 of 24,546 records (canonical population at the time this was measured, 2.1.5/2.3.0-era —
now 24,301 canonical rows as of 2.4.1; the pair itself, CS406483 and its byte-identical twin, is
unaffected by the 245-record NPEV drop between those releases, but the site was not re-scanned
against the smaller population), itself and its own byte-identical twin. The trio is two parental
records and one engineered derivative.

**The row above claiming the flip "lands when Phase B applies decisions" is not true as written, and
this is the more important defect.** `engineered_or_construct` is **blank** for all three records in
the private `manual_review_overrides.csv`, which is the file the pipeline actually reads. The
assertion exists only in this ledger, so every rebuild recomputes the value as TRUE from the text
predicate and the ledger row changes nothing. A ledger assertion with no counterpart in the source of
truth is not a pending delta but a permanent one. **Curation has to land where it is applied, not
only where it is recorded** — and the corollary is that the re-adjudication's ~45 flips must go
through the private overrides, not be added here as more ledger-only rows.

Full evidence, per-record dispositions and the curator's revised definition:
[`docs/engineered-readjudication.md`](../docs/engineered-readjudication.md) and
[`docs/engineered-full-population-readjudication.md`](../docs/engineered-full-population-readjudication.md).

## Status vocabulary

The three values are used with distinct meanings, not interchangeably:

- `active` — the governing assertion.
- `superseded` — a call that was **contradicted** and overturned. Nine rows as of the 2.4.1 resync:
  the three D2 rows (2.1.5), the four `AB180070-73` rows (2.3.0), and two `JC013129` rows (2.4.1) —
  see `SUPERSEDED_CARRY_FORWARD` in `scripts/migrate_legacy_registries.py` for the exact mechanism
  and why each is genuinely a contradicted call rather than a mere retraction.
- `retired` — withdrawn from force **without** being contradicted. Used for the 17 (subject, field)
  pairs that two registries assert with the *identical* value: the same human judgment recorded
  twice, not a conflict.

When two registries assert the same field for the same subject, precedence is declared, not
inferred: `canonical_reference_confirmed.csv` (purpose-built for canonical-reference calls) >
`manual_review_overrides.csv` (current human curation) > `legacy_accession_classification_overrides.csv`
(machine-generated 2015 bridge). Where two registries *disagree* on the value, the migration raises
rather than applying precedence — adjudicating a scientific disagreement silently is how a curation
database acquires an opinion nobody chose. All 17 current duplicates agree; the only cross-registry
disagreement of that kind was D2, and a human resolved it. (The `AB180070-73` and `JC013129`
supersessions are a different shape: one registry revising its own earlier value over time, not two
registries disagreeing at once — see `SUPERSEDED_CARRY_FORWARD`'s docstring.)

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

  Those ten filenames name files in the **private** curation repository, so on its own the column is
  a reference a public reader cannot follow. One of the ten is now committed beside the ledger as
  [`registry/legacy/legacy_accession_classification_overrides.csv`](legacy/legacy_accession_classification_overrides.csv),
  and a test reconciles all 30 of its rows against the decisions that cite it — so for the one
  legacy file that affects canonical output, `source_artifact` is verifiable rather than asserted.
  The other nine are not committed because the ledger is a complete migration of their content: every
  row, every field, every rationale is here, which is what the parity test against the shipped
  `manual_decisions.tsv.gz` demonstrates. Copying them would duplicate data the ledger already
  carries, and duplicated curation data drifts.
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

**Do not point `--source-dir` at the private tip.** The private repository is a live working tree
where curation continues after any given release is built, so `--source-dir` must be the private
registries **as of the release's own build commit** — extract them there first, then migrate from
the extraction:

```bash
rm -rf /tmp/evgc-registries && mkdir -p /tmp/evgc-registries
git -C ../MAD-VDPV archive <release-build-commit> data/genbank/working \
  | tar -x -C /tmp/evgc-registries --strip-components=3
python scripts/migrate_legacy_registries.py --source-dir /tmp/evgc-registries
```

`<release-build-commit>` is the `git_sha` the target release's own
`final/audit/build_manifest.json` records (for 2.4.1: `67554e2`) — never `HEAD` of the private repo.
An earlier version of this doc recommended `--source-dir ../MAD-VDPV/data/genbank/working` directly,
which is exactly the tip-vs-build-commit mistake the next two paragraphs warn against; that command
was never actually safe to run as written.

Because it needs a private path, CI cannot run it. Its guards — the disagreement raise, the
truncation repair, the quote normalization, the D2 adjudication, the DQ205099 annotation, the
release-baseline pin and id assignment — are covered by `tests/test_migration_legacy.py` against
synthetic inputs instead. It is deterministic in the sense that matters: the same inputs produce the
same bytes.

**It is pinned to release 2.4.1's curation state, not to whatever the private repository holds
today.** That repository is a live working tree where curation continues, so re-running this script
is not idempotent over time — and the failure mode is silent, because new private rows are
well-formed decisions that migrate cleanly. Observed 2026-07-29 (during 2.3.0 prep): a concurrent
private edit added two `date_override` rows for `KP004228`/`KP004229`, and an unguarded re-run wrote
a 2,758-row ledger without comment. The ledger tests caught it, but only four stages downstream, as
six failures about counts and status distributions rather than one statement about what happened.
Verified again at the 2.4.1 resync (2026-07-30): the private tip held 2,008 `manual_review_overrides`
rows, identical to the count at the 2.4.1 build commit itself — no drift this time, but the
extraction was still done from the build commit rather than assumed safe.

So the baseline count is asserted at the point of divergence:
`EXPECTED_BASELINE_DECISIONS = 2912` is checked immediately after the registries are read and before
any adjudication is applied. A moved source now stops the migration and names what to do about it.
`--allow-baseline-drift` overrides it, deliberately awkward, for the case where the new decisions
have been diffed and approved — at which point the constant, the counts in this file, and
`tests/test_decision_ledger.py` all move together.

Those two decisions are **not** in this ledger. Whether release-era curation should be re-synced from
the private repository, and on what cadence, is an open question for Phase B rather than something
this migration should decide by running at an arbitrary moment.

## Frozen legacy registries

[`registry/legacy/`](legacy/) carries four hash-pinned CSVs that are the only surviving output of two
private pipeline stages whose external inputs no longer exist. Three of them are named as frozen
inputs-of-record in the shipped `final/audit/build_manifest.json` and were dangling references in the
published repo until they were committed.

Only 30 of those 2,315 rows are load-bearing, and they are already migrated into this ledger. Nothing
in the build reads the directory — it is provenance, and the undeclared-input guard refuses to open
anything that resolves inside it, so composing the path segment-wise or reaching it through a symlink
does not evade the rule. A hardlink would, since it is a second name for the same inode rather than a
path that resolves into the tree; that is a documented limit rather than a defended boundary. See
[`registry/legacy/README.md`](legacy/README.md) for the per-file reach analysis, the three large
derived tables deliberately *not* carried, and the DQ205099 disposition.

`scripts/migrate_decisions.py` is the generic normalizer for *future* legacy imports. It refuses to
run when an input file carries a column with no destination in the ledger — silently dropping
curator-entered data is the failure mode this repository exists to prevent. Columns that are
genuinely out of scope must be named explicitly:

```bash
python scripts/migrate_decisions.py legacy/*.csv --output registry/decisions.tsv \
  --drop-columns internal_row_id,spreadsheet_colour
```
