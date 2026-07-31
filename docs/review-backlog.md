# Review backlog — 2026-07-29 adversarial sweep

Open defects found by an adversarial review of the whole repository, triaged and left here rather
than fixed in one pass. Nothing in this file is a fix; every entry is a defect that still exists at
the commit named below unless its **status** says otherwise.

**Scope reviewed:** commit `d12ff45`, by four independent Opus reviewers with deliberately
non-overlapping charters — vacuous validation, parity-oracle integrity, data and scientific claims,
guard escape, and cross-artifact consistency. Each was told to assume defects remained and given a
worktree to break things in. Overlap between their findings was near zero, which is itself the
result: **single-reviewer recall on this codebase is low.**

## Why this file exists

Three review rounds have now run against this work:

| round | defects confirmed |
|---|---:|
| 1 (stage-4 diff) | 10 |
| 2 (round-1 fixes) | 15 |
| 3 (whole pipeline, 4 reviewers) | ~59 |

The rate is not falling. Round 2 found defects *in round 1's fixes*, including two fresh instances
of the "validation that cannot fail" class that round 1 existed to close. Round 3 found more than
rounds 1 and 2 combined. The measured rate of new defects introduced per item fixed is close to one,
so a single 59-item remediation pass would predictably produce a fourth round of comparable size.
Hence: capture first, fix in small themed batches, each independently reviewed before commit.

**The data itself is not implicated.** Reviewers independently reproduced every divergence
measurement, recomputed all 37 declared manifest hashes (all match), confirmed the DuckDB is
logically consistent with the shipped TSVs, confirmed `record_disposition` covers the source
snapshot exactly, and confirmed sequence checksums and lengths against the bytes. What these
findings are about is the **verification layer**: the guarantees made *about* the release are weaker
than the documents claim. That distinction should drive prioritisation — this is not a data-quality
emergency.

## Root causes, which matter more than the individual items

**R1 — `grep` on the author's machine silently skips `.gitignore`d files.** It is a shell function
shimming to `ugrep --ignore-files`. Every "read by nothing" / "zero consumers" reachability
conclusion in this repository was produced with it. That is the root cause of the false
"effect on canonical output: none" claim B24 records. **Use `command grep` for all reachability
work.** Verified: a needle in a gitignored directory is invisible to `grep -rn` and visible to
`command grep -rn`.

**R2 — prose guarantees drift from the event tables and rule sets that implement them, in the
optimistic direction, every time.** B2, B12, B14, B19, B21, B26, B30 are all this shape. The
generation of a claim and the verification of a claim are separate acts, and only the first was
happening reliably.

**R3 — a check that has never been observed to fail is not evidence.** Repeatedly, checks looked
load-bearing and were not (B11, B13, B16, B18). The only method that reliably found this was
deliberately breaking the protected thing and watching for red. Reasoning about soundness was
roughly a coin flip. **A check is not finished until a recorded mutation proves it fires.**

**R4 — the boundary of an analysis is inherited from whatever artifact framed it.** The four tests
guarding "the four `engineered` calls" take their universe from a legacy CSV, so they structurally
cannot see `CS406433` (B1). Ask what population a claim is *about* before trusting a check over it.

**R5 — identifiers that are constructed at runtime are invisible to a literal search, so grep
absence is not absence.** Found while re-verifying B24 with `command grep`, which was supposed to be
immune to R1. Searching the private repo for the column name `scan_legacy_override_classification`
returns **zero hits**, and that is not because nothing uses it: `build_candidate_table.py:100`
creates it with `.rename(columns={c: f"scan_{c}" for c in scan_cols ...})`, so the name only ever
exists as an f-string prefix plus a value read out of a CSV header. The column is real and populated
(1,129 and 15 nonblank rows in `vdpv_candidate_table.csv`). **A negative grep result over a
dynamically-composed name means nothing.** For reachability, follow the *artifacts* — read each
stage's declared inputs and outputs — rather than searching for field names. R1 and R5 are different
mechanisms with the same consequence, and R5 survives the `command grep` fix for R1.

---

## P0 — a load-bearing guarantee is false, or wrong data could ship

### B1. The `engineered_or_construct` adjudication rests on a non-sequitur, and a fourth patent record was never seen — **CURATION, ASSIGNED**
`registry/README.md:94-114`, `registry/legacy/README.md:131-136`, `docs/pipeline.md:117-127`

Patent WO2006042156 contributes **four** records to this dataset, not three. `CS406433` is a verbatim
substring of Sabin 2 — `AY184220[640:3384]`, exact, zero mismatches, the entire parental capsid
cassette — has **zero decisions in the ledger**, appears in no document, test or legacy CSV, and ships
`engineered_or_construct=TRUE`. Applying D2 makes `CS406436`/`CS406482`/`CS406483` the only three of
**506** `division=PAT` records with `FALSE`, while `CS406433` — same patent, more clearly parental —
stays `TRUE`. Separately, ruling out codon deoptimization does not establish that a record is not
construct-derived, which is what the column meant (`final/dictionaries/canonical_data_dictionary.tsv`:
"engineered **or construct-derived**"). And D2 set the trio `FALSE` although they are
`mol_type=unassigned DNA`, while `DQ205099` was upheld `TRUE` for being a clone though it is
`mol_type=genomic RNA` — opposite standards.

```bash
.venv/bin/python -c "
import duckdb; print(duckdb.sql(\"select accession,definition,sequence_length_nt,division from 'final/source/normalized_tsv/records.tsv.gz' where accession like 'CS4064%'\"))"
```

**Status: assigned.** The curator has ruled that the column simplifies to `engineered`, meaning
*someone assembled that specific genotype for some purpose and it is not a genotype that occurred in
nature*; replicates of naturally occurring references take the reference's label. A dedicated agent is
re-doing the adjudication under that definition. It may reverse the `DQ205099` disposition, since
"a clone is a construct" is exactly the reasoning the simplification removes.

### B2. An ordinary build can overwrite the immutable release
`src/enterovirus_genbank_curated/build.py:50-69`

`reject_immutable_output` checks the output directory and its parents by resolved path and inode, but
never its **children**, and never re-resolves per-artifact paths at write time. A symlink from inside
the output directory to `final/source/normalized_tsv/` let a build rewrite all 12 shipped release
tables; `records.tsv.gz` changed hash and `git status` showed it modified. `README.md:77-78` says
`evgc build-source` "refuses to write into `final/` or `raw/`, which are immutable" with no mention of
a flag. `--guard-inputs` *does* catch it, but is opt-in and is not the documented defence.

```bash
mkdir $OUT && ln -s <repo>/final/source/normalized_tsv $OUT/normalized_tsv
evgc build-source --output $OUT --skip-relational   # completes, mutates final/
```

**Fix:** (a) re-check containment on each artifact's resolved path immediately before writing, or open
with `O_NOFOLLOW`; make `--guard-inputs` the default.

### B3. The parity oracle moves with one edit: the `expected_artifacts` *set* is unpinned
`src/enterovirus_genbank_curated/contracts.py:365-382`, `:457-486`

`verify_expected_artifacts` iterates whatever the contract declares. There is no `EXPECTED_ARTIFACT_PATHS`
counterpart to `EXPECTED_BASELINE_COUNTS` (`:56-63`), so deleting a declaration deletes the check.
Deleting 6 of 7 entries and then writing `TAMPERED` into the `accession` column of every row of
`sequence_metadata.tsv.gz`, `sequence_metadata_vouched.tsv.gz` and `record_disposition.tsv.gz` left
`evgc validate-contracts` PASS and all tests green. Falsifies `docs/pipeline.md:28-30` and
`docs/reproducibility.md:117-119` ("Editing the contract to make a future build pass therefore fails
immediately") — you cannot *change* a declaration, but you can *delete* one.

**Fix:** (a) pin the artifact path set as the counts are pinned, and/or require coverage of every
`authoritative=TRUE` manifest row.

### B4. Artifact hashes are only ever compared to a second copy of themselves
`src/enterovirus_genbank_curated/contracts.py:466-486`

Parity is cross-checked against the release manifest and recomputed from the file, but the *value* is
pinned nowhere and neither declaration file is itself hashed. Flipping one nucleotide in
`sequences.fasta.gz`, recompressing at `mtime=0`, then one `sed` replacing the old hash in both
`releases/2.1.5/parity.json` and `final/audit/release_file_manifest.tsv` left everything PASS. Counts
require a **code** edit to move; hashes require only a **data** edit.

**Fix:** (c) needs a decision between pinning the hashes in code, comparing the declaration files to
their blobs at the `2.1.5` tag, or signing the release.

### B5. The vouched partition is counted but never identified
`src/enterovirus_genbank_curated/contracts.py:489-518`

Row counts of `sequence_metadata_vouched.tsv.gz` and a `curation_status` tally over
`sequence_metadata.tsv.gz` are checked independently and never joined, so **any** 10,086 rows satisfy
the gate. Replacing the vouched table with 10,086 rows drawn from the *provisional* partition,
relabelled, passed. Counts themselves are honest — `provisional_rows` is tallied, not subtracted, and
flipping one record's status is caught.

**Fix:** (a) assert the vouched table is exactly the `curation_status == 'vouched'` subset, keyed on
`version`, column for column.

### B6. `logical_content` is a hash scope nothing ever computes
`src/enterovirus_genbank_curated/contracts.py:480`, `docs/reproducibility.md:138-139`

There is no `logical_content` branch. Replacing the ~100 MB `final/source/genbank_source.duckdb` with
the 22-byte string `THIS IS NOT A DATABASE` passed every gate. Worse, the scope is an oracle-move
lever: flipping `hash_scope` from `file_bytes` to `logical_content` for `canonical/sequences.fasta.gz`
in both declaration files, changing no hash, then replacing the FASTA with 18 bytes, passed. "The
DuckDB convenience database is compared by logical content" describes a comparison that does not exist.
(The shipped database *is* logically consistent — all 12 table row counts match the TSVs. It is the
check that is absent.)

**Fix:** (a) implement a deterministic logical digest and refuse any `logical_content` declaration for
a path with no registered computer.

---

## P1 — coverage gaps and guarantees weaker than documented

### B7. 19 of 58 shipped `final/` files have no hash anywhere; 7 more are declared but never recomputed
`src/enterovirus_genbank_curated/contracts.py:395-416`

Undeclared: every file in `final/alignments/` (a headline deliverable per `README.md:28-31`), plus the
self-referential manifest. Declared but never recomputed: `audit/build_manifest.json`,
`audit/canonical_projection_provenance.tsv.gz`, `audit/sequence_evidence.tsv.gz`, and all four
`dictionaries/*.tsv`. Truncating all 19 alignment files to zero bytes, deleting one outright, and
replacing the four dictionaries and two audit tables with the word `garbage` left every gate PASS. No
document says the alignments are outside the hash gate; the docs only say they are not yet
*regenerable*, which is a different claim.

**Fix:** (a) recompute every `file_bytes` hash the manifest declares and add a bidirectional
completeness check; (b) state which tiers are byte-gated.

### B8. `build_manifest.json` contradicts the contract without anything noticing
`src/enterovirus_genbank_curated/contracts.py:521-536`

Only four fields are verified. Rewriting the manifest to `"validation": "FAIL"`,
`"canonical_rows": 999999`, `"vouched_rows": 1`, `"provisional_rows": 2`, `"source_records": 3` passed
all gates — the release's own build record declaring its validation failed.

**Fix:** (a) compare those counts to `expected_counts` and require `validation == "PASS"`.

### B9. `evgc parity-source` has no coverage floor
`src/enterovirus_genbank_curated/build.py:127-190`, `cli.py:107-110`

The `missing` guard protects the 12 TSVs but not the 12 Parquet. Flipping one Parquet entry to
`logical_content` and replacing the file with 18 bytes gave `source parity: PASS (23 artifacts…)` —
the count silently dropped from 24 and still reported PASS. `tests/test_source_parse.py:298-311`
catches it in CI, so the CLI gate that `README.md:71-73` presents as *the* check is the weak one.

**Fix:** (a) extend the guard to the Parquet set and assert the expected count in the CLI.

### B10. `multiprocessing` and inbound network traffic both escape the guard
`src/enterovirus_genbank_curated/sandbox.py:41-68`, `:57`, `:292`

Spawn-start `multiprocessing` goes through `_posixsubprocess.fork_exec`, which raises none of the
eight `ESCAPE_EVENTS`; a child read `/etc/hosts` and listed `$HOME` with the parent recording zero
violations and printing PASS. The code comment claiming "blocking fork also blocks `multiprocessing`"
is false. `NETWORK_EVENTS` has no `socket.bind`, no `socket.sendmsg` and **no receive events at all**;
a complete UDP round trip ran clean. Ingesting data over the network is the precise property the guard
exists to prevent.

**Fix:** (a) both are cheap to add.

### B11. "Every rule in the event tables has a test that fails when the rule is removed" — true for 11 of 31
`docs/reproducibility.md:52-54`, `.github/workflows/ci.yml:31-32`

Established by deleting each of the 31 entries one at a time and re-running. Untested: 4 of 6 network,
5 of 8 escape, 11 of 17 mutation. `FROZEN_DIRS` — the rule preventing reintroduction of the undeclared
upstream dependency this whole rewrite exists to remove — has **no test at all**. `os.spawn` is dead
weight on this platform. Several are genuinely untestable in isolation (`os.exec`/`os.posix_spawn` are
shadowed by `os.fork` firing first), but `os.chmod`, `os.utime`, `shutil.copyfile`, `shutil.move` and
`urllib.Request` are trivially testable and untested.

**Fix:** (b) correct both statements to the covered subset; (a) add the ~8 cheap missing tests.

### B12. `os.mkfifo` and `os.mknod` plant nodes inside `final/` and cannot be caught
`src/enterovirus_genbank_curated/sandbox.py:89-94`

CPython raises **no audit event** for either — established by adding them to `MUTATION_EVENTS`,
watching the probe still escape, and then enumerating events directly. They are deliberately absent
from the table, because an entry for an event that never fires is itself a check that cannot fail.
Recorded as a real, unfixable-in-hook gap.

**Fix:** (b) document in the "what it does not prove" list.

### B13. The nine-warning parse-loss pin is count-only
`src/enterovirus_genbank_curated/genbank/parse.py:91-94`, `tests/test_source_parse.py:314-329`

`len(parser_warnings) == 9` discards messages and accessions, so a Biopython change that dropped a
*different* nine lines passes. `docs/reproducibility.md:25-27` credits the pin with catching exactly
that. Detection actually falls to byte-parity, which fires with a diagnostic pointing at the wrong
layer.

**Fix:** (a) assert the sorted message tuple or the three accessions.

### B14. Byte-stability is claimed for 24 artifacts and tested for 12
`tests/test_source_parse.py:349-359`

The repeat-build test passes `relational=False`. Parquet bytes come from DuckDB `COPY` and depend on
the DuckDB version and possibly writer parallelism. Verified true today by hand for all 24; pinned for
12. `README.md:63-64` carries no tier qualifier at all.

**Fix:** (a) add a `relational=True` repeat-build assertion; (b) qualify the README.

### B15. `_within` resolves symlinks for events that operate on the link, not the target
`src/enterovirus_genbank_curated/sandbox.py:160-178`

`os.remove` and `os.rename` act on the link itself, so resolving first gives a false positive
(refusing to unlink a scratch symlink pointing outside) and a narrow false negative (allowing
`os.remove` of a symlink physically inside `final/` whose target resolves into a write root).

**Fix:** (a) choose lexical or resolved per event rather than uniformly.

### B16. `__pycache__` warmth makes the guard's verdict nondeterministic
`src/enterovirus_genbank_curated/sandbox.py`

A cold import writes a `.pyc` and trips a spurious `write outside the clone` violation, so a new stage
importing a fresh module fails the guard for an unrelated reason.

**Fix:** (a) allowlist `__pycache__` writes under already-allowed read roots, or disable bytecode
writing in guarded runs.

### B17. The 25 deterministic rules exist only inside `final/`
`docs/pipeline.md:5-20`

The declared public input set is `raw/ + registry/ + versioned rules`, and `final/` files are declared
"comparison targets, never pipeline inputs" — but `registry/` holds only `rules.schema.json`, a
contract with no instance. The 25 rules live solely in `final/audit/rules.tsv.gz`. Unlike the two
frozen legacy stages, this gap appears in no not-yet-regenerable list.

**Fix:** (c) migrate them to `registry/rules.tsv` as was done for `decisions.tsv`, or add them to the
frozen-inputs-of-record list.

**Closed 2026-07-30.** All 28 are now declared in `registry/rules.json` — JSON rather than TSV
because `parameters` is an object and a TSV cell holding one would need quote-escaping, which the
ledger's plain-tab guarantee forbids. `export/audit.py: write_rules_view` regenerates
`final/audit/rules.tsv.gz` from the catalog **byte-for-byte**, which is what establishes that the
instance describes the release rather than merely resembling it.

### B18. `rules.schema.json` has never validated any data, and requires fields the shipped table lacks
`registry/schemas/rules.schema.json:8-16`

It requires `implementation`, `parameters`, `status`; `final/audit/rules.tsv.gz` has four columns
(`rule_id, rule_version, field_name, description`) for all 25 rules, with thresholds embedded as prose
inside `description`. `contracts.py:549-552` validates only the schema's *shape*. There is no
`registry/rules.tsv`, so the `rule_id` pattern, `rule_version` pattern and `status` enum are entirely
unexercised.

**Fix:** (c) decide whether those fields are required for the migrated 2.1.5 rules or optional until a
later stage populates them.

**Closed 2026-07-30**, by keeping all seven required and populating them. Every threshold is lifted
out of the prose into `parameters` as a decimal **string** (`"0.15"`), compared with `Fraction` rather
than float division, and a coherence check requires every declared value to appear verbatim in its
own `description` — so the two representations cannot drift, which is the failure this item is really
about. `implementation` is a stable key resolved through a dict, never an import path, and
`bind_rules` fails on an orphan rule *and* on an orphan implementation: code computing a value no
published rule declares is how a rule table and its code drift apart. 28 of 28 implementations are
declared pending with a per-rule reason. `tests/test_rule_catalog.py` supplies the falsification
battery, including a threshold perturbation that must turn a real gate red.

### B19. Controlled values do not fail closed
`registry/README.md:196-197`, `registry/schemas/decisions.schema.json`

Only `status` has an `enum`, and `contracts.py:228-260,307` derives enforcement from the schema's
enums — so nothing constrains `decision_type`, `field_name` or `new_value`. Three `active`
`classification` assertions carry values outside the target column's vocabulary, including
`D-0eead42d3d8b` `FJ517648 = 'iVPDV'`, a **misspelling of `iVDPV`** migrated verbatim and unannotated.
`registry/README.md:220-224` states the scope correctly, so the document contradicts itself.

**Fix:** (a) add enums if closure is wanted; (c) for the `iVPDV` typo.

### B20. `decision_id` collision handling emits an id the published schema rejects
`scripts/migrate_legacy_registries.py:674`, `tests/test_migration_legacy.py:315-323`

The collision branch produces `D-<digest>-2`, which fails the schema pattern `^D-[0-9a-f]{12,64}$`.
The migration validates its own output, so the first genuine identity collision aborts after all the
work with a cryptic pattern error rather than "two rows share an identity tuple". A **passing** test
asserts the broken form. Latent only because the 2,756 committed ids happen to be collision-free.

**Fix:** (c) either widen the pattern or make collisions a hard `ContractError` and change the test to
assert the raise. The second suits the repo's fail-closed posture but is a contract decision.

### B21. `scripts/migrate_decisions.py` still uses the abandoned pre-D3 id scheme — **RESOLVED BY DELETION 2026-07-30**
`scripts/migrate_decisions.py:32-38`, `:63` (both now gone)

It hashed `source_artifact` into the identity and emitted 20-hex digests, so the documented tool for
future imports reproduced exactly the failure mode D3 was introduced to eliminate — renaming a source
file rehashes every id — and would mix 20-hex ids into a ledger of 12-hex ids. Both forms satisfy the
schema pattern, so **no check anywhere would catch this**.

**Resolved:** the script and `tests/test_migration.py` were deleted rather than repaired. It had
produced no committed artifact, had never run against real data, and was reachable only through a
`registry/README.md` section recommending it — so the cheapest correct fix was to stop shipping a
broken tool and write the normalizer when an import actually needs one. `registry/README.md` now says
so, and item 5 in "Claims nothing would catch if they drifted" is withdrawn.

---

## P2 — documentation accuracy

Each of these is a false or misleading statement; the underlying code or data is correct.

| id | location | the defect |
|---|---|---|
| B22 | `README.md:50-53` | The vouched/provisional split described does not exist. `curation_status` is a pure restatement of `virus_group` — all 10,086 poliovirus rows are `vouched`, **zero** provisional; the parentheticals ("confirmed canonical reference or membership-verified" vs "name/annotation-derived") describe a distinction absent from the data. Contradicts `R-STATUS-1` and the shipped dictionary. This is the release's headline confidence tier. |
| B23 | `docs/pipeline.md:117-119`, `registry/README.md:126-127` | "Disagree on exactly one field for exactly three records" — there are **nine**. Six undocumented `classification` disagreements: `AJ416942`, `DQ205099`, `FJ517648`, `KR259356`, `KR259357`, `KX162685`. (`classification` is an input to `classification_reconciled`, so a mismatch is not automatically an error — but the claim is stated absolutely.) |
| B24 | `registry/legacy/README.md:46,56-73`, `docs/pipeline.md:86-88` | **CONFIRMED 2026-07-29, chain traced end to end.** `legacy_2026_bridge.csv` "effect on canonical output: none" is **false**, and the enumeration of "all five readers" is incomplete. Verified chain: bridge → `scan_vdpv_classification_artifacts.py:30,118,578` → `legacy_possible_classifications` / `legacy_override_classification` in `vdpv_accession_scan.csv` (1,889 / 23 nonblank) → **`build_candidate_table.py:98-100`**, the reader the trace missed, which carries both columns forward renamed `scan_legacy_*` (1,129 / 15 nonblank in `vdpv_candidate_table.csv`) → `triage.py` → `vdpv_candidate_triage.csv` → `stage_metadata_only_candidates.py` → `*.STAGED.csv` → `consolidate_promotion_overrides.py`, whose own docstring reads *"Consolidate the ratified papers-review flips into one manual_review_overrides row-set. Ratified promotion set (Mike, 2026-07-24): 1,387 clean paper-confirmed cVDPV/iVDPV + 46 Madagascar-2005"* → `manual_review_overrides.csv` (private commit `71f9ea3`, "Promote 1,518 VDPV->cVDPV/iVDPV (papers review)") → canonical `poliovirus_classification`. **One correction to the finding:** the last step is a deliberate human ratification, not code — `consolidated_promotion_overrides.csv` has zero automated readers and `manual_review_overrides.csv` is hand-maintained (20 commits). So the bridge reaches canonical output through curator judgment rather than a closed code loop. That does not rescue the README: the claim is "effect on canonical output: none", and the effect is real, large, and undocumented. Root cause R1 for the original miss, **R5 for why a `command grep` re-check initially appeared to exonerate it.** |
| B25 | `registry/README.md:105-110` | The 7,435 reconciliation is wrong for `CS406436`: its curator rows say `4nt/6621`, not 7435. Only CS406482/83 use 7435, so "the curator's rows report the same counts over 7,435 positions" and "keeps 7,435" are false for that record. |
| B26 | `README.md:104` | "Every declared hash is recomputed from the shipped bytes" — only `file_bytes` scope is. `docs/reproducibility.md:112-113` words it honestly; the README does not. |
| B27 | `README.md:59-60` | "Traceable to the specific decision" — no join key exists. `canonical_projection_provenance` has no `decision_id`, and the field-name vocabularies are nearly disjoint: 33 of 2,476 manual-override provenance pairs match a decision by `(accession, field_name)`; 2,443 do not. |
| B28 | `README.md:69`, `docs/reproducibility.md:6` | "The source layer regenerates from `raw/` alone" — the build also reads `releases/2.1.5/parity.json` for the archive member name, both hashes, the byte size and the expected record count. Declared and in-clone, but it collides with "the baseline is a test oracle only" (`:108-109`). |
| B29 | `registry/README.md:220-224` | The decisions schema is not a one-way "executable source of truth" — `contracts.py:33-48` restates the column set and order in Python and `tests/test_contracts.py:38-47` pins all four properties, so editing the schema *fails* rather than changing what CI enforces. The real mechanism is a bidirectional pin, which is better than what the doc describes. |
| B30 | `README.md:40-41`, `:108-110` | Says `registry/decisions.tsv` is future work and "not part of the initial change". It has existed since `ce1504b` with 2,756 rows. |
| B31 | `docs/pipeline.md:46-56` | Command list omits both commands that exist (`build-source`, `parity-source`) and lists three that do not (`build`, `verify`, `parity`); the "PR 1" framing is three stages stale. |
| B32 | `docs/pipeline.md:34-42` | Package boundaries name seven subpackages; two exist. `build.py`, `cli.py`, `contracts.py`, `sandbox.py` appear nowhere, though they implement the `raw` and `validation` responsibilities. |
| B33 | `registry/legacy/README.md:123`, ledger `D-76ece1bbec32` | DQ205099's provenance is inverted: patent WO2006042156 has priority 2004-10-08 and published 2006-04-20; the paper is J Virol April 2006. The patent **precedes** the paper, so "the study the patent derives from" is backwards. Also "no shipped value changes" conflicts with its own `active` assertion (`classification=engineered`) against canonical `Sabin-like`. The scientific verdict is sound; the surrounding claims are not. |
| B34 | `README.md:23-24` | "Why every record was in/out" — `exclusion_reason` is blank on 1,008 of 1,181 exclusions. The *coverage* claim (25,727 = full snapshot) is true; the *reason* claim is not. |
| B35 | `raw/genbank_query.md:7` vs `:10` | Two non-equivalent queries ship. The displayed "User query" lacks 13 `[Organism]` terms present in the results link, including `"Enterovirus C"[Organism]`, under which 16,055 records with no "poliovirus" in the organism name arrive. Probably as-typed vs NCBI-translated, but `README.md:34` calls it *the* defining query. Needs (c). |
| B36 | `raw/raw_manifest.json` | Declares private-repo paths (`data/genbank/raw/...`) that do not exist in this clone, and **no code reads it** — the authentication `README.md:36-38` credits it with is done by `contracts.verify_raw_input` against `parity.json`. Its five fields agree with the contract today; nothing enforces that. |
| B37 | `registry/README.md:15` | "310 distinct rationales across all ten registries" — the registries hold 309. The 310th is the migration's own D2 string, in no registry. Overcounts curator work by one. |
| B38 | `registry/README.md:81-83` | The `reference_label` enumeration lists 9 names for 13 rows, omitting Mahoney, Brunenders, USOL-D-bac and Fox — Mahoney being the canonical PV1 reference. Presented as closed. |
| B39 | `registry/README.md:51-52` | "Six truncated reasons, one ending mid-phrase at `(<50nt`" — five of the six end there; only `KY748286` is the other case. |
| B40 | `registry/legacy/README.md:100` | "46 MB" — `genbank_metadata.csv` is 34 MiB; no file in that directory is 46 MB. |
| B41 | `registry/legacy/README.md:17` | The Downloads path omits a `buildDatabase/` segment. Faithfully quoted from `build_manifest.json`, so the error originates in the shipped manifest — needs (c) on whether to diverge from it or note it. |
| B42 | `registry/legacy/README.md:129` | Calls a Sabin-2 clone "the **wild-type** control". Hazardous in a database where `wild` and `Sabin-like` are distinct controlled values; the paper says "unmodified". |
| B43 | `README.md:84` | Says the parse loss affects five records; four lose content. |
| B44 | `README.md:28-31` | Describes five alignment sets; six ship (`POLIO_unified` omitted). |
| B45 | `README.md:26-27` | Promises "controlled vocabulary, observed population … for every table above", but only `canonical_data_dictionary.tsv` has those columns; `release_file_manifest.tsv` and `reference_region_coordinates.tsv` ship undocumented. |
| B46 | `src/enterovirus_genbank_curated/genbank/parse.py:21` | Cites `VERBATIM_COLUMNS`; the constant is `RAW_COLUMNS` and the stale name exists nowhere else. |
| B47 | `registry/README.md:109` | References "D1" as a labelled decision; only D2 is defined anywhere in the repo. |
| B48 | `registry/schemas/rules.schema.json:43-46` | `status` enum is `active`/`deprecated`; `deprecated` appears in no document, and the decisions vocabulary uses `retired` for the same concept. Three different "status" vocabularies across the repo, two sharing `active` with different meanings. |
| B49 | ledger, `AH004344` | The reason cites "**shipped** 71.875% over only 32 codons", but `AH004344` is excluded and appears in neither `sequence_evidence.tsv.gz` nor the provenance table — the figure is in no shipped artifact. |
| B50 | `raw/sequence.gb.zip` | Contains an undeclared second member, `__MACOSX/._sequence.gb` (726 B). `archive_sha256` covers it; the member declaration does not mention it. |
| B51 | `final/alignments/*.provenance.json` | `unified_stockholm_provenance.json` claims its scope "EXACTLY matches" `build_reference_msa.py`, but `reference_msa_provenance.json` reports 9143/7610/4045 against the shipped 3732/3604/1425. PLAUSIBLE; needs (c). |

---

## Claims nothing would catch if they drifted

True today, verified where verifiable, and unprotected. Distinct from the defects above: these are
places where the repository asserts something it does not check.

1. `final/alignments/` — 19–20 shipped files with no hash in any manifest and no test. A corrupted
   `POLIO_unified.sto.gz` passes everything. (Same gap as B7.)
2. The DuckDB `logical_content` hash, never computed, with "logical content" undefined anywhere. (B6.)
3. Seven manifest-declared `file_bytes` hashes recomputed by nothing. (B7.)
4. `raw_manifest.json` agreement with `parity.json` on their five shared fields. (B36.)
5. ~~`migrate_decisions.py`'s id scheme — both schemes satisfy the schema pattern. (B21.)~~
   **Withdrawn 2026-07-30:** the script was deleted, so there is no second scheme to drift.
6. ~~`rules.schema.json` in its entirety — no data has ever been validated against it. (B18.)~~
   **Withdrawn 2026-07-30:** `registry/rules.json` is now validated against it on every run, and
   `tests/test_rule_catalog.py` mutates a copy per constraint to prove each one rejects.
7. `README.md:64-67`'s three headline audit guarantees — referential closure of provenance, declared
   controlled vocabularies, and `final/audit/` "**proves — not just asserts**" its record-disposition
   coverage. All three are **true** (checked: zero missing `winning_rule_id`, zero undeclared
   vocabulary values, disposition version set identical to `records.tsv.gz`). No code in this
   repository checks any of them; the cited machine-readable record is
   `build_manifest.json`'s `"validation": "PASS"`, an opaque string from the private builder. So the
   sentence claiming proof is itself an assertion. All three are cheap to check from shipped bytes.
8. `R-EXCLUDE-1`'s `field_name` is the prose string `canonical inclusion` — the only such value in
   `rules.tsv.gz`. Nothing constrains that column's shape.
9. Rule reachability in both directions: 14 of 25 rules are referenced by no provenance row.
   Legitimate — they govern upstream sequence evidence — but unstated and unchecked.
10. `registry/README.md:12-18`'s input-side figures (2,214 rows, 309/310 rationales, 249 notes, 78
    sources, the 387-row batch) describe private files this repo does not contain, so they are
    permanently unfalsifiable from a public clone — and the private source now holds 2,216 rows, so
    the present-tense phrasing is already stale.

---

## Verified sound — do not re-litigate

Recorded so future work does not re-derive it. Independently confirmed by more than one reviewer where
noted.

- **The data.** All four divergence measurements recompute exactly from
  `final/canonical/sequences.fasta.gz` (CS406436 4/6621, CS406482 4/7439, CS406483 6/7439, DQ205099
  3/7439 with `A2616G`/`A3303T`/`T5640A`); every `sequence_sha256` and `sequence_length_nt` matches the
  bytes; FASTA ids ≡ canonical versions with no duplicates; all 37 manifest `file_bytes` hashes
  recompute; the DuckDB is logically consistent with all 12 TSVs; `record_disposition` covers the
  25,727-record snapshot exactly; every controlled-vocabulary value in canonical is declared; Sabin
  reference rows recover canonical exactly at RF match columns for all three serotypes;
  `EV_unified` = `POLIO_unified` + `NPEV_unified` exactly.
- **The ledger.** 2,756 rows / 2,736 active / 17 retired / 3 superseded; all ids unique and every one
  reproducible as `"D-" + sha256("type|subject|field|value")[:12]`, confirming `source_artifact` is
  excluded per D3; all 2,753 shipped decisions present; 2,747 reasons verbatim with exactly the six
  claimed repairs; no active `(subject, field)` conflicts; all 17 retired rows agree in value with
  their active peer. `tests/test_decision_ledger.py` was described by one reviewer as the best-built
  gate in the repo — full-column resynthesis, ids recomputed from content, additions enumerated
  individually — and it survived a deliberate attempt to hole it.
- **Raw authentication is real**: archive hash, member name, uncompressed size and uncompressed hash
  all recomputed before any parse.
- **The source layer genuinely rebuilds byte-identically from `raw/` alone** for all 24 artifacts, and
  `compare_source_to_release` is **not** circular — the authority is the release manifest, and a
  tampered shipped file is reported separately from a bad build.
- **`final/` is not a build input** for the source layer; the only reads are oracle reads.
- **Guard routes correctly blocked**: `subprocess.run`, `os.system`, `os.posix_spawn`,
  `socket.getaddrinfo`, direct reads of the private sibling repo and `/etc/hosts`, direct reads of
  `registry/legacy/`, `os.replace` into `final/` without `dir_fd`, renames out of the clone, symlink
  aliasing in both directions, and `os.chdir` + `..` traversal. The realpath-first fix from round 2
  genuinely holds.
- **CI wiring is correct**: `-m slow` overrides the `addopts` marker filter, the real-corpus guarded
  build runs and asserts both PASS lines, and no pipe or `|| true` could mask a failure.
- **The private-repo reach analysis**, apart from B24: `reconstruct_archival_wpv1_dates.py` writes 6
  CSVs + 1 `.md`, exactly 5 with zero consumers; `legacy_title_key_table.csv` genuinely read by
  nothing; `legacy_date_location_extract.csv` reaches only three summary scalars;
  `genbank_metadata.csv` absent from `iVDPV-vs-cVDPV`'s entire history; all four legacy CSVs
  byte-identical to the private originals and matching their pins; `classification_scan` genuinely
  absent from both carves.
- **The biology**, apart from B1's inference: PMID 16537593 and patent WO2006042156 verified live
  (title, journal, volume, pages, authors, clone designation, applicant, inventors). The
  "hundreds to thousands of substitutions" expectation is corroborated by the paper's own figures —
  97% of the capsid recoded, CpG raised 97 → 302 — so the *mechanism refutation* in B1 is sound; only
  the inference from it to `engineered_or_construct=FALSE` is not. DQ205099's three substitutions are
  all synonymous third-position (two in VP1, one in 3C), which decisively rules out deoptimization,
  and the abstract confirms S2R9 is the unmodified Sabin 2 parental clone.
- **`build-source`'s output refusal** holds against all 12 destinations tested, including symlinks,
  `..` composition and case-aliasing, because it compares `(st_dev, st_ino)`. The gap in B2 is
  *children of the output directory*, not the output directory itself.
- **The vouched/provisional counts** are honest: `provisional_rows` is tallied from `curation_status`,
  not subtracted, and flipping one record's status is caught. B5 and B22 are about *membership* and
  *description*, not arithmetic.
- **`read_tsv_gz`'s QUOTE_MINIMAL handling** is correct and load-bearing (`comments.tsv.gz` is 18,476
  rows across 27,038 physical lines).

---

## Working agreement for remediation

Adopted in response to this sweep. The point is not more effort; it is that generation and
verification were the same act and must not be.

1. **No prose guarantee without a test that fails when the guarantee is violated.** If the test cannot
   be written, the claim goes in "what this does not prove" instead.
2. **No check without a recorded mutation proving it fires.** Breaking the protected thing and watching
   for red is the only method that has worked. Reasoning about soundness has been roughly a coin flip.
3. **No number without a derivation from data**, and the derivation lives next to the number as a test
   — not as a substring assertion against the number's own spelling.
4. **Reachability work uses `command grep`.** See R1.
5. **Small themed batches**, each independently reviewed before commit. Fix passes are at least as
   defect-dense as original work; three rounds now say so.
6. **Nothing self-certified.** The adversarial-reviewer pattern found ~59 defects across four
   charters with near-zero overlap. It is a standing gate, not an escalation.

### B52. The seventeen patent-division poliovirus records the transport cannot carve
`src/enterovirus_genbank_curated/derive/metadata.py` (`SEQUENCE_RESCUED_INCLUSIONS`)

Raised and dispositioned 2026-07-30. All seventeen are `division=PAT` with an organism of
`unidentified` (9), `Homo sapiens` (3) or `synthetic construct` (5), so no organism-name predicate
reaches them; the release recovers them by capsid amino-acid distance (R-MEMBERSHIP-AA-1). They span
three quite different cases: patent claims on Sabin capsid fragments (`E00765`–`E00769`, 709–1,786
nt) and whole Sabin genes (`E01570`–`E01572`, ~4,670 nt); five 70-nt fragments from WO2012090000
(`JA792237`/`38`/`49`/`50`/`51`); and `PE314016`/`PH149759`, which are `sequence_sha256`-identical to
`AF111984`, a named wild PV1 field isolate.

Since the dataset is described as epidemiology-first and these carry no date, place, host or
surveillance context, carve-exclusion was considered — there is precedent in the `FV537075`–`77`
exclusion. **Curator disposition: they belong in the carve.** So this is a gap to close by
implementing the membership rule, not by dropping records, and closing it by exclusion would remove
real poliovirus sequence from the release. `SEQUENCE_RESCUED_INCLUSIONS` should reach empty when the
pairwise sequence-evidence stage lands.
