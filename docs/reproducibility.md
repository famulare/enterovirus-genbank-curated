# Reproducibility boundary

## Current state

Release 2.1.5 is a verified, internally consistent data release. It is not yet regenerable from
`raw/` alone because the historical build depended on a curated registry and two frozen upstream
processing stages that were not included in the initial public repository.

PR 1 does not change that status. It establishes executable contracts for removing those
limitations without rewriting history or treating existing `final/` artifacts as source data.

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
- migration of all 2,753 human decisions and 25 deterministic rules;
- equivalent normalized source and canonical scientific values;
- complete, referentially closed provenance;
- deterministic repeated builds from declared inputs.

Compressed file bytes are required to match when deterministic compression is part of the format
contract. The DuckDB convenience database is compared by logical content, not file bytes.

## Completion criterion

The README reproducibility claim changes only after a fresh clone builds and validates the complete
release without undeclared files, network access, private repositories, or existing `final/`
artifacts. That transition requires a new release version; release 2.1.5 remains unchanged.
