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
