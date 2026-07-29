# enterovirus-genbank-curated

A curated, versioned view of publicly available GenBank Enterovirus sequence data —
**poliovirus** (with Sabin 1/2/3 vaccine reference alignments) and **non-polio enterovirus** —
with epidemiology-first metadata, full provenance for every curated field, and reference
multiple-sequence alignments.

This is a **data release**, not (yet) a fully self-contained reproducible pipeline. See
[Reproducibility status](#reproducibility-status) below for the precise, honest boundary of what
that means.

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
                    (PV1/PV2/PV3), the full enterovirus genus, and a non-polio-only
                    subset, each as Stockholm (.sto.gz) and FASTA (_aln.fasta.gz), plus a
                    genomic region coordinate map.

raw/
  genbank_query.md    The GenBank query that defined this release's candidate record set.
  sequence.gb.zip     The frozen GenBank flat-file download this release was built from.
  raw_manifest.json   Authenticates sequence.gb.zip end-to-end (archive hash, the
                      archived member's name/size/hash) — a fresh clone can verify the
                      raw input is exactly what it claims to be without contacting NCBI.
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

**What is not yet true:** this repository does not yet contain a pipeline that regenerates
`final/` from `raw/` alone. The curated master this release was built from depends on a hand-curated
registry and two frozen upstream processing stages that are not yet part of this repository. None of
that affects the correctness of what's shipped — it affects whether you can *regenerate* it yourself
today.

Porting the generation pipeline into this repository, so that `final/` becomes fully derivable from
`raw/` + a shipped, consolidated registry, is planned future work.

## Licensing and citation

- **Code** (none ships in this release; will be MIT when the pipeline lands) — see [`LICENSE`](LICENSE).
- **Curated data** — dedicated to the public domain, see [`LICENSE-DATA`](LICENSE-DATA) (CC0-1.0).
- **Underlying GenBank records** — see [`NOTICE`](NOTICE) for the upstream data notice and
  submitter-rights caveat.
- If this data is useful to your work, a citation is appreciated but not required — see
  [`CITATION.cff`](CITATION.cff).
