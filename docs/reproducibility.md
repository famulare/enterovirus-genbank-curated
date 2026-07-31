# Reproducibility boundary

## Current state

The current baseline release (2.4.1; see `src/enterovirus_genbank_curated/contracts.py`'s
`BASELINE_RELEASE`) is a verified, internally consistent data release. **Its source layer is now
regenerable from `raw/` alone**, and the transportable half of canonical metadata with it; the
derived layers are not yet. The source-layer claim was true of 2.1.5 too and remains true across the
2.3.0 and 2.4.1 refreshes: none of them touched the source layer, only canonical metadata text on
already-shipped records.

**Reproducible today — `final/source/`.** `evgc parity-source` re-authenticates
`raw/sequence.gb.zip`, reparses all 25,727 records, and compares every one of the twelve
normalized relations plus their twelve Parquet counterparts against the `file_bytes` hashes
declared in `final/audit/release_file_manifest.tsv`. All twenty-four match byte-for-byte, and
repeated builds are byte-stable. Only `genbank_source.duckdb` is excluded, because DuckDB file
bytes are not reproducible; the manifest records a logical-content hash for it.

**Partly reproducible — `final/canonical/sequence_metadata.tsv.gz`.** `evgc parity-metadata`
rebuilds the canonical carve from `raw/sequence.gb.zip` and `registry/decisions.tsv` alone and
compares it to the shipped table cell by cell:

```bash
evgc parity-metadata    # 24,284 rows x 13 transported columns, cell for cell
```

This is a *transport* claim, not a claim on the table. Thirteen of the twenty-six canonical columns
hold a GenBank value moved into a canonical column — `accession`, `version`, `sequence_sha256`,
`sequence_length_nt`, `ncbi_taxid`, `organism_name`, `isolate_name`, `strain_name`, `host_name`,
`country`, `admin1`, `locality`, `biosample_accession`. Every one of those cells matches the
release exactly, in the same row order, and repeated builds are byte-stable. The split is not a
judgement call: `final/audit/canonical_projection_provenance.tsv.gz` carries a projection row for
exactly the other fourteen columns, minus `locality`, whose rule is closed-form over one GenBank
string.

`locality` is also produced *with its provenance*, and it was the deliberately small first column for
that: reproducing a value while mislabelling which way the rule went is right by luck, so the cheapest
place to establish that the rule catalog, the outcome type and the provenance writer all agree with the
release is on one closed-form rule before a harder column is attempted. Its **value** matches the
release on all 24,284 shared records. Its **branch label** does not, and comparing the label is what
found that the shipped label was wrong — see [the second deliberate break](#the-second-deliberate-break-localitys-basis).

`virus_group` and `curation_status` are projected the same way, and they are where the rewrite first
**declines** rather than guessing. Poliovirus sits inside one enterovirus species — *Enterovirus C*,
renamed *Enterovirus coxsackiepol* — so a GenBank organism name decides membership only when it names
something at or below the type level. Six names cannot: the polio-containing species under either
name, the bare genus, and three that are not virus identifications at all (`unidentified`,
`synthetic construct`, `Homo sapiens`). The rule returns unresolved for all of them.

That matters more than it looks. Defaulting those names to non-polio scores **98.3%** against the
release, which reads as success and is a guess on 414 records — and `virus_group` gates
`sequence_scope`, `curation_status`, `poliovirus_classification` and the whole epi partition, so four
later columns would inherit the guess and each look right for the wrong reason. The honest population
is **1,733 declined rows**, not 414: 414 is only where a default would have landed wrong. Sizing an
ambiguity by its disagreements rather than by its inputs is the specific mistake being avoided here.

Of the 22,551 rows the rule does decide, every one matches the release, including `manual_override`
— TRUE on exactly the seventeen records the ledger's `is_poliovirus` decisions resolve. That is the
first place a recorded decision is shown to reach a generated provenance row rather than merely
existing in the ledger, which is the D2 failure stated positively.

### The first deliberate break: `collection_date_precision`

The date family does not reproduce the release, on purpose. This is the first place the rewrite
corrects rather than reproduces, and the second follows it.

For every record that deposited a `/collection_date`, the canonical date **is** the ISO normalization
of that qualifier and the precision **is** its shape — 19,730 rows, exactly, with no curated input,
including the floor-of-mean midpoint on all 121 interval records. The release describes these as
projections of curated fields; for these rows those curated fields evidently just held the normalized
source value.

The problem is the 4,569 records that deposited **no** date. The release splits them: 2,805 get
precision `unknown`, and 1,764 get precision `year` with a year recovered outside GenBank by an
archival reconstruction whose inputs are not in this repository. Nothing in `raw/` separates those two
groups, so the split cannot be reproduced, and guessing it would fabricate 4,569 values.

**Curator decision, 2026-07-30: a record with no date has no precision.** Those rows now carry `NA`
and a blank date.

**Invariant broken, and its replacement.** 2.4.1 guaranteed
`collection_date_precision ∈ {day, month, year, range, unknown}` and said nothing relating the
precision to the value. The vocabulary is now `{day, month, year, range, NA}` — `unknown` retired,
`NA` new — under a stronger guarantee that ties the two columns together:

> `collection_date` is blank if and only if `collection_date_precision` is `NA`.

That is checkable in both directions and both matter: a blank date with a real precision claims a
determination about a date that is not there, and a populated date with `NA` claims no determination
about one that is. It is enforced against the build's own output by `validation/invariants.py` before
anything is written, so it holds for a fresh clone with no `final/` present and cannot be satisfied by
copying. `unknown` is also freed to mean what it says — a date exists but its precision is unclear.

The break is counted, not just described: **1,761** records differ on `collection_date` and **4,549**
on `collection_date_precision`, declared in `oracle/parity.py` and required to match exactly, so a
deliberate delta changing size fails the gate. The 1,764 whose year came from identifier parsing are
recoverable later — the frozen archival-dates extract labels 21 identifier rule families, usable as a
validation oracle rather than an input — and each one recovered moves a row from `NA` back to `year`,
never the reverse.

R-DATE-1 and R-DATE-PRECISION-1 are therefore `deprecated` in the catalog and superseded by R-DATE-2
and R-DATE-PRECISION-2 on real semver. `final/audit/rules.tsv.gz` still regenerates byte-for-byte,
because the view emits only rules carrying the baseline's own `rule_version` — which is how the
catalog can evolve without moving a published artifact.

### The second deliberate break: `locality`'s basis

The same defect, found by the same method. 2.4.1 labels **every** blank `locality`
`duplicate_of_admin1_suppressed`. Measured, only **4,233 of 23,268** are suppressions:

| n | what the record deposited | the release said | the rewrite says |
|---|---|---|---|
| 4,233 | `Country: Region` | suppressed | `duplicate_of_admin1_suppressed` |
| 16,987 | `Country` only, no region | suppressed | `no_admin1_deposited` |
| 2,048 | no `/geo_loc_name` at all | suppressed | `no_geography_deposited` |

So the label asserts a determination that was never made on 19,035 records. The two new bases stay
distinct deliberately: a record naming only a country *did* deposit geography, so folding it into
"nothing deposited" would replace one overstatement with another.

**Invariant broken, and its replacement.** The release constrained the basis column to a vocabulary
and nothing more, which is how one value drifted into meaning "blank". Each basis is now a claim about
the record's own geography, and all four parts are enforced by `validation/invariants.py` against the
build's own output:

> `locality` is blank iff the basis is one of the three blank reasons;
> `duplicate_of_admin1_suppressed` implies a non-blank `admin1`;
> `no_admin1_deposited` implies a non-blank `country` and a blank `admin1`;
> `no_geography_deposited` implies both blank.

`country` and `admin1` are transport columns rather than projections, so this cannot live inside the
rule — no rule sees two columns at once, which is exactly why cross-column invariants get their own
module.

**This break is why declared deltas are counted per column rather than per field.** No `locality`
*value* changes: every blank stays blank and every non-blank was already right. The entire correction
is in `evidence_basis`. An earlier version of the parity gate compared only `final_value` for a
superseded field, so this correction would have registered as zero difference — and a genuine
regression in `source_field` or `manual_override` would have passed unnoticed alongside it. Every
provenance column is now declared for every superseded field, zeros included, so the *shape* of a
break is legible and a disagreement in an unexpected column fails.

**The row set has a known 18-record gap, and it is pinned rather than absorbed.** The transport
carves on two closed predicates — the GenBank lineage names the `Enterovirus` genus, and the ledger
does not actively exclude the accession — which reproduces 24,284 of the 24,301 shipped rows.

- Seventeen shipped records it cannot reach: patent-division deposits whose organism is
  `unidentified`, `Homo sapiens` or `synthetic construct`, recovered upstream by capsid amino-acid
  distance to a poliovirus reference (R-MEMBERSHIP-AA-1). Eight name polio in their `DEFINITION`;
  nine do not, so no text rule recovers the set — it needs the sequence stage. The curator confirmed
  on 2026-07-30 that these records belong in the carve, so this is a gap to close by implementing the
  membership rule rather than one to close by excluding them.
- One record it carves that the release excludes: `AF326751.2` (Simian agent 5 strain B165) carries
  `Enterovirus` in its lineage but ships as `non_ev_other` with no exclusion reason and no row in
  `registry/decisions.tsv`. The call is real; its basis is not in any declared input.

Both sets are declared in `derive/metadata.py` and compared for equality by the parity check, so a
record drifting in or out of the carve fails rather than being reported as a slightly larger gap.
The build never reads them — a transport that patched itself against a declared diff would pass
parity while proving nothing.

**Not yet reproducible — the rest of `final/canonical/`, and `final/audit/`,
`final/dictionaries/`, `final/alignments/`.** These still derive from a curated master produced
outside this repository. Closing that is the remaining work.

### Inherited parse loss

Biopython's GenBank scanner silently discards text it cannot fit to the structured-comment
grammar, and the shipped release inherits it. Three records (MH484164.1, MH484165.1, MH484166.1)
lose their entire `##Assembly-Data-START##` block; two more (MN918613.1, PP461545.1) lose an
`##Assembly-Data-END##` continuation line with **no warning at all**, leaving PP461545.1's comment
ending mid-sentence. The parse emits exactly nine `BiopythonParserWarning`s, a count pinned by a
test so that a Biopython upgrade which changes what is dropped fails rather than quietly altering
shipped data.

Because parity is byte-exact, this loss cannot be corrected without deliberately breaking the gate
and cutting a new release. That is a real constraint, not an oversight.

## The undeclared-input guard

Self-containment is enforced at runtime, not documented and hoped for. `evgc build-source` and
`evgc parity-source` accept `--guard-inputs`, which installs a `sys.addaudithook` that fails the
build on the first undeclared access. CI runs the real 25,727-record parity build under it on every
push.

This exists because the pipeline being replaced read `~/Downloads/*.xlsx` and a sibling repository by
absolute path for two of its stages, and nobody noticed until those files had been deleted. A prose
rule would not have caught it; a failing build would have.

**What it proves.** Within the guarded process, the build performed no read outside the clone, the
scratch directory, and the interpreter's own installation; **no read of `final/` at all**; no read of
the frozen [`registry/legacy/`](../registry/legacy/) tree; no write or filesystem mutation touching
`final/` or `raw/`; no write outside the clone and scratch; no network call; and no child process by
any of `subprocess`, `os.system`, `os.spawn*`, `os.exec*`, `os.posix_spawn` or a bare `os.fork`. It
raises *and* records every violation, and `assert_no_violations()` re-checks the record after the
build, so a caller that swallowed the exception in a bare `except` still fails. Paths are resolved
before the allowlist decision, so a symlink sitting inside an allowed root cannot alias something
outside one.

The `final/` read refusal is new, and it changed how the `parity-*` verbs run. Refusing only *writes*
left the failure that matters wide open: a derive stage that reads the shipped canonical table can
reproduce it perfectly and prove nothing, and reaching for that read is exactly what happens while
someone calibrates a rule against the oracle. The comparison itself must read `final/`, so
`--guard-inputs` on `evgc parity-source` and `evgc parity-metadata` now runs the **build in a guarded
child process** and compares in the unguarded parent, and it fails unless that child reported the
guard's own PASS line. Before this, the guard was installed in the same process that then read the
release, which made it structurally unable to distinguish a build reading the comparison target from
the comparison itself.

The reproducible evidence for all of that is `tests/test_sandbox.py`: every rule in the event tables
has a test that fails when the rule is removed, and positive controls assert legitimate work still
succeeds so that a guard which refused everything could not pass. Deliberately planted mutations
were also run by hand — a neutered containment check, a dropped violation record, an unguarded
socket, an unguarded subprocess, an added read root, a forced-false write intent, an emptied
`FROZEN_DIRS` and an emptied `MUTATION_EVENTS`, all caught — but that battery is a record of an
exercise, not a runnable artifact, and should not be cited as the check.

The scope above is narrower than what this section claimed before 2026-07-29, in the direction of
being true. A review demonstrated live bypasses of two of the guarantees as then written, and the
event tables in `sandbox.py` were extended to cover them: `os.system` and `os.spawnl` ran children
the guard never saw, and every filesystem mutation that does not pass through `open` —
`os.remove`, `os.rename`, `os.replace`, `os.mkdir`, `os.truncate`, `os.symlink`, `shutil.rmtree` —
was invisible, so `os.replace(tmp, final/canonical/...)` could rewrite the immutable release under a
clean `PASS`. Each is now refused and has a falsification test, alongside a negative control that
mutating scratch is still allowed. `os.fork` is what actually closes the child-process family: on
POSIX `os.spawnl` is fork+exec in Python and raises only that event, which was established
empirically rather than read off the audit-event table, whose documented `os.spawn` event does not
fire on this platform.

**What it does not prove.** Five limits worth stating plainly:

- **The allowlist is not just the clone.** `site-packages`, the stdlib, DuckDB's bundled extensions,
  Biopython's data files, `$TMPDIR` and a fixed list of system paths are permitted, because a guard
  that fired on `import` would test nothing. The home directory and sibling repositories are *not*
  permitted, which is the property actually under test. One consequence: if a user site-packages
  directory under `$HOME` is on `sys.path`, it is allowlisted along with the rest of `sys.path`.
- **Reads are audited through the `open` event only.** A C extension calling `fopen()` directly does
  not raise it and would not be seen. Child processes are *blocked* rather than guarded, for exactly
  this reason — an unguarded child could read anything.
- **The stat family is a genuine hole.** `os.stat`, `Path.exists()`, `os.listdir` and `os.scandir`
  raise no event this hook subscribes to, so a build can probe for undeclared paths undetected. It
  cannot *read* them, which is the property that matters for parity, but "did this file exist" is
  observable. This is pinned by a test that asserts the hole, so if it ever closes the limits get
  revisited rather than silently going stale.
- **Hardlinks are not covered.** The path checks resolve symlinks, so aliasing through one is caught,
  but a hardlink is a second directory entry for the same inode rather than a path that resolves
  elsewhere. `os.link(final/audit/x, $TMPDIR/h)` followed by `open($TMPDIR/h)` is not seen. Closing
  it would mean comparing `(st_dev, st_ino)` on every access, which is disproportionate to the
  threat model here: this guard exists to catch a build that accidentally depends on an undeclared
  file, not to contain an adversary.
- **It says nothing about determinism or correctness.** Access scope only. Byte-stability is a
  separate test, and parity against the release is a separate gate.
- **It cannot show the declared inputs are sufficient.** It detects touching something undeclared,
  not depending on something absent. A build can be fully self-contained and still wrong.

The general lesson is the one this repository keeps relearning: a guarantee stated in prose and a
guarantee implemented in an event table drift apart silently, and the prose is always the optimistic
one. The tables in `sandbox.py` are the specification; this section summarises them.

Audit hooks cannot be uninstalled, so a guarded build must be its own process; every guard test runs
under `subprocess` for that reason.

## Frozen baseline

`releases/2.4.1/parity.json` records the public release commit, source build commit, raw archive
identity, row counts, and authoritative release hashes used by the rewrite. The baseline is a test
oracle only. (`releases/2.1.5/parity.json` and `releases/2.3.0/parity.json` are retained as
historical records of retired baselines, no longer verified against the tree.)

The oracle is itself checked. `evgc validate-contracts` re-derives every claim in the contract from
the shipped release on each CI run: file-byte hashes are recomputed, `logical_content` hashes are
cross-checked against `final/audit/release_file_manifest.tsv`, row counts (including the
vouched/provisional split, which is recounted from `curation_status` rather than inferred by
subtraction) are recounted, the frozen archive's declared member is authenticated by name, size,
and uncompressed hash, and `final/audit/build_manifest.json` must agree with the contract's source
commit, schema version, and raw-snapshot hash. Editing the contract to make a future build pass
therefore fails immediately, because the contract would no longer describe the release it is
pinned to.

`public_release_commit` is the one field that is documentary rather than verified: it names the
commit at which this repository first published the release, which a later checkout cannot confirm
from its own contents.

Passing parity means at minimum:

- identical source and canonical record identity;
- identical vouched/provisional partitions;
- identical FASTA identifiers and nucleotide sequences;
- migration of all 2,912 human decisions the release shipped, and 28 deterministic rules. The ledger
  holds 3,164, and both differences are approved curation history rather than a parity failure. Nine
  are carried-forward `superseded` assertions (the three `engineered_or_construct=FALSE` D2 rows,
  plus curator revisions to `AB180070-73` and `JC013129` that a from-scratch regeneration would
  otherwise have dropped silently). The other 243 are the locked VDPV/wild reconciliation allowlist,
  migrated 2026-07-30 — the last input to `poliovirus_classification` with no counterpart here, and
  every row already agrees with the shipped column, which a test asserts. See
  [`registry/README.md`](../registry/README.md);
- equivalent normalized source and canonical scientific values;
- complete, referentially closed provenance;
- deterministic repeated builds from declared inputs.

Compressed file bytes are required to match when deterministic compression is part of the format
contract. The DuckDB convenience database is compared by logical content, not file bytes.

## Completion criterion

The README reproducibility claim changes only after a fresh clone builds and validates the complete
release without undeclared files, network access, private repositories, or existing `final/`
artifacts. That transition requires a new release version; the current baseline release remains
unchanged in the meantime, exactly as 2.1.5 and 2.3.0 did before it.
