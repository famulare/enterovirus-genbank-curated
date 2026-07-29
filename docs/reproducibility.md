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
