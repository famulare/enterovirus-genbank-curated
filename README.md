# enterovirus-genbank-curated

A curated, versioned view of publicly available GenBank Enterovirus sequence data —
**poliovirus** (with Sabin 1/2/3 vaccine reference alignments) and **non-polio enterovirus** —
with epidemiology-first metadata, full provenance for every curated field, and reference
multiple-sequence alignments.

**→ Explore the data in your browser:
[famulare.github.io/enterovirus-genbank-curated](https://famulare.github.io/enterovirus-genbank-curated/)**

Five linked views of every sequence in the release — divergence from reference,
multidimensional scaling of nucleotide and of protein distance, and neighbor-joining trees over
those same distances — colored by any curated trait, brushable, and linked back to the full
record. An exploration surface that shows the structure in the data and makes
misclassification visible. Source and build instructions in [`site/`](site/README.md).

This is a **data release** with an early public pipeline foundation. It is not yet a fully
self-contained reproducible pipeline. See [Reproducibility status](#reproducibility-status) for the
precise boundary and [`docs/pipeline.md`](docs/pipeline.md) for the staged rewrite architecture.

## What's here

```text
final/
  canonical/       One row per included sequence, poliovirus + non-polio enterovirus,
                    in a shared epidemiology-first schema. sequences.fasta.gz is the
                    nucleotide payload (header = accession.version).
  source/          The raw GenBank records, fully normalized into relational tables
                    (records, features, qualifiers, references, comments, taxonomy,
                    cross-references), shipped as Parquet, TSV, and a convenience DuckDB.
  audit/           Full provenance: why every record was in/out, what every curated field
                    was projected from, every human curation decision (one row per
                    field-level assertion, content-stable IDs), and the versioned rule
                    catalog those decisions and projections reference.
  dictionaries/    Column-level data dictionaries (definition, type, nullability,
                    controlled vocabulary, observed population) for every table above.
  alignments/      Reference multiple-sequence alignments: per-serotype poliovirus
                    (PV1/PV2/PV3), all-serotype poliovirus pooled, a non-polio-only
                    subset, and the full enterovirus genus, each as Stockholm (.sto.gz)
                    and FASTA (_aln.fasta.gz), plus a genomic region coordinate map.

raw/
  genbank_query.md    The GenBank query that defined this release's candidate record set.
  sequence.gb.zip     The frozen GenBank flat-file download this release was built from.
  raw_manifest.json   Authenticates sequence.gb.zip end-to-end (archive hash, the
                      archived member's name/size/hash) — a fresh clone can verify the
                      raw input is exactly what it claims to be without contacting NCBI.

registry/             The human-readable curation ledger (decisions.tsv), the deterministic
                      rule catalog (rules.json), and the JSON Schemas both are validated
                      against. rules.json regenerates final/audit/rules.tsv.gz byte-for-byte.
site/                 Source for the browser data explorer linked above, plus the
                      precomputed artifacts it serves and the gate that keeps them
                      in step with final/.
src/                  Pipeline foundation and executable contract validation.
releases/2.4.1/       Immutable parity contract for the current release (releases/2.1.5/
                      and releases/2.3.0/ are retained as historical records, no longer
                      verified against the tree — see src/enterovirus_genbank_curated/
                      contracts.py's module docstring).
docs/                 Pipeline architecture and the reproducibility boundary.
```

## Data model at a glance

Every included sequence gets one row in `final/canonical/sequence_metadata.tsv.gz`, keyed by
`version` (the GenBank `accession.version`). Poliovirus records are further split into
`vouched` (confirmed canonical reference or membership-verified) and `provisional`
(name/annotation-derived); non-polio enterovirus records are labeled `provisional` throughout,
never presented as vouched gold-standard.

Every curated field (classification, sample origin, surveillance stream, collection date, virus
type, ...) has a corresponding row in `final/audit/canonical_projection_provenance.tsv.gz` naming
exactly which upstream field it was projected from, under which versioned rule
(`final/audit/rules.tsv.gz`), and whether a human decision touched it — traceable to the specific
decision in `final/audit/manual_decisions.tsv.gz`.

## Reproducibility status

**What is verified today:** the release build is internally self-consistent and idempotent
(rebuilding from the same inputs is byte-for-byte identical), every canonical field's provenance is
referentially closed, every controlled-vocabulary value is declared, and `final/audit/` proves — not
just asserts — that its record-disposition table covers the full source snapshot exactly. See
`final/audit/build_manifest.json` for the machine-readable validation record.

**The source layer regenerates from `raw/` alone, today:**

```bash
evgc parity-source    # reparse 25,727 records; compare 24 artifacts to the release manifest
```

This reparses the authenticated archive and checks every normalized relation and Parquet file
against the hashes `final/audit/release_file_manifest.tsv` declares. All match byte-for-byte.
`evgc build-source --output DIR` writes a build somewhere of your choosing; it refuses to write
into `final/` or `raw/`, which are immutable.

**The transportable half of canonical metadata regenerates too:**

```bash
evgc parity-metadata    # 24,284 rows x 13 canonical columns, cell for cell
```

From `raw/` and `registry/decisions.tsv` alone, this carves the canonical row set and fills the
thirteen columns whose value is a GenBank value moved into a canonical column — identity, sequence
hash and length, taxid, organism, isolate/strain/host, parsed country/admin1/locality, BioSample.
Every one of those cells equals the shipped cell, in the same row order. The row set reproduces
24,284 of 24,301 rows; the 18-record difference is pinned in code and fails if it moves.

**What is not yet true:** the other thirteen canonical columns, and the rest of the *derived* layers
— `final/audit/`, `final/dictionaries/`, `final/alignments/` — still come from a curated master
produced outside this repository, or need a sequence-comparison stage that does not exist here yet.
None of that affects the correctness of what's shipped; it affects whether you can regenerate all of
it yourself today. See [`docs/reproducibility.md`](docs/reproducibility.md), which states the
per-column boundary and also documents an inherited GenBank parse loss affecting five records.

For `final/alignments/`, the groundwork is laid but no alignment file is produced yet:
`evgc alignment-population` derives each of the six shipped alignments' row set from
`final/canonical/` and `final/audit/` alone, and it is not the same population the shipped
alignments carry — see [`docs/reproducibility.md`](docs/reproducibility.md) for the measured gap.

The rewrite is staged and parity-gated. Existing `final/` files remain immutable comparison targets,
never pipeline inputs. The reproducibility claim changes only after a fresh clone regenerates the
release from declared public inputs and passes the complete parity contract. See
[`docs/reproducibility.md`](docs/reproducibility.md).

## Development contract checks

With [pixi](https://pixi.sh) and the `align` environment installed (`pixi install --locked -e
align`):

```bash
pixi run -e align evgc validate-contracts    # contract shape + re-verification of the shipped release
pixi run -e align pytest
```

`validate-contracts` does two separable things. It checks that the schemas and
`releases/2.4.1/parity.json` are well-formed and declare nothing undeclared, and it then checks
that the parity contract actually describes the release in this repository: every declared hash is
recomputed from the shipped bytes, every declared row count is recounted, the frozen GenBank
archive is authenticated member-by-member, and the release's own `build_manifest.json` is required
to agree with all of it. Pass `--skip-baseline-verification` for the shape-only check. A parity
contract that nothing can contradict is not a contract, so CI runs the full form.

The human-readable curation ledger is `registry/decisions.tsv`. Its contract and review rules are
documented in [`registry/README.md`](registry/README.md).

Note that two version numbers coexist and are deliberately independent: the **data release** is
2.4.1 (see `CITATION.cff` and `final/audit/build_manifest.json`), while the Python package version
tracks the pipeline rewrite and stays at 0.0.0 until it can build a release end to end.

## Licensing and citation

- **Code** — MIT, see [`LICENSE`](LICENSE).
- **Curated data** — dedicated to the public domain, see [`LICENSE-DATA`](LICENSE-DATA) (CC0-1.0).
- **Underlying GenBank records** — see [`NOTICE`](NOTICE) for the upstream data notice and
  submitter-rights caveat.
- If this data is useful to your work, a citation is appreciated but not required — see
  [`CITATION.cff`](CITATION.cff).
