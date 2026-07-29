# Reproducibility boundary

## Current state

Release 2.1.5 is a verified, internally consistent data release. **Its source layer is now
regenerable from `raw/` alone**; the derived layers are not yet.

**Reproducible today — `final/source/`.** `evgc parity-source` re-authenticates
`raw/sequence.gb.zip`, reparses all 25,727 records, and compares every one of the twelve
normalized relations plus their twelve Parquet counterparts against the `file_bytes` hashes
declared in `final/audit/release_file_manifest.tsv`. All twenty-four match byte-for-byte, and
repeated builds are byte-stable. Only `genbank_source.duckdb` is excluded, because DuckDB file
bytes are not reproducible; the manifest records a logical-content hash for it.

**Not yet reproducible — `final/canonical/`, `final/audit/`, `final/dictionaries/`,
`final/alignments/`.** These still derive from a curated master produced outside this repository.
Closing that is the remaining work.

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
scratch directory, and the interpreter's own installation; no read of the frozen
[`registry/legacy/`](../registry/legacy/) tree; no write or filesystem mutation touching `final/` or
`raw/`; no write outside the clone and scratch; no network call; and no child process by any of
`subprocess`, `os.system`, `os.spawn*`, `os.exec*`, `os.posix_spawn` or a bare `os.fork`. It raises
*and* records every violation, and `assert_no_violations()` re-checks the record after the build, so
a caller that swallowed the exception in a bare `except` still fails. Paths are resolved before the
allowlist decision, so a symlink sitting inside an allowed root cannot alias something outside one.

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

`releases/2.1.5/parity.json` records the public release commit, source build commit, raw archive
identity, row counts, and authoritative release hashes used by the rewrite. The baseline is a test
oracle only.

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
- migration of all 2,753 human decisions the release shipped, and 25 deterministic rules. The ledger
  holds 2,756: the three extra are the `engineered_or_construct=FALSE` assertions added by the D2
  adjudication, which is an approved curation change rather than a parity failure. See
  [`registry/README.md`](../registry/README.md);
- equivalent normalized source and canonical scientific values;
- complete, referentially closed provenance;
- deterministic repeated builds from declared inputs.

Compressed file bytes are required to match when deterministic compression is part of the format
contract. The DuckDB convenience database is compared by logical content, not file bytes.

## Completion criterion

The README reproducibility claim changes only after a fresh clone builds and validates the complete
release without undeclared files, network access, private repositories, or existing `final/`
artifacts. That transition requires a new release version; release 2.1.5 remains unchanged.
