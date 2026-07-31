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

**Canonical metadata regenerates in part, and the part is precisely stated:**

```bash
evgc parity-metadata                          # 24,299 rows: 13 transported columns + 12 projected
evgc build-metadata --output release/3.2.0    # write the whole dataset, manifests included
```

From `raw/` and `registry/` alone this carves the canonical row set and fills **25 of the 26
canonical columns**.

*Thirteen transported columns* — identity, sequence hash and length, taxid, organism,
isolate/strain/host, parsed country/admin1/locality, BioSample — where the canonical value **is** the
GenBank value. Every cell equals the shipped cell, in the same row order.

*Twelve projected columns*, each produced with a machine-readable provenance row naming the rule that
decided it and which branch of that rule fired: `virus_group`, `curation_status`, `virus_type`,
`poliovirus_classification`, `sample_origin`, `surveillance_stream`, `specimen_type`,
`collection_date`, `collection_date_precision`, the `collection_year_*` pair, and
`engineered_or_construct` — plus `locality`, which is both transported and projected. Several
deliberately **differ** from the release, because the shipped value asserted a determination that was
never made; each break retires a weak guarantee, states a stronger one enforced against the build's
own output, and pins the difference as an exact count *and a witness hash over the disagreeing
records*, so a substituted disagreement fails the gate even when the count does not move.

**One column is not written: `sequence_scope`.** The sequence stage that would produce it exists —
`derive/evidence.py` builds the Sabin 1/2/3 reference frame from the frozen archive's own
`mat_peptide` features, reproducing the shipped `reference_region_coordinates.tsv` exactly — and its
coverage geometry does *not* reproduce the shipped column. Fitted against every threshold
combination it agrees on 86.7% of poliovirus records, with systematic rather than boundary errors:
745 records the release calls `other_fragment` have a complete VP1, capsid or genome. So
`record_type` is not a function of coverage against Sabin VP1 alone, and fitting to 86.7% would
assert a wrong determination on 1,332 records. It stays declared-pending instead.

What that same stage *does* support is classification. `poliovirus_classification` is decided by VP1
nucleotide divergence from the matching Sabin reference, using the thresholds the release already
publishes in its own rule table — Sabin-like below 1% (0.6% for PV2), wild at or above 15%. Measured
before those parameters were read, every `Sabin-like` record in the release sits below 1% and every
`wild` record above 18%, so the published thresholds are recovered from the data rather than imposed
on it.

Three properties matter as much as the coverage. A rule that cannot decide from declared inputs
**declines** rather than guessing — 12,700 records whose `/isolation_source` carries no specimen
keyword, 3,189 whose classification no sequence or ledger row settles, 2,216 whose organism name
states no type, 1,596 whose organism name cannot settle poliovirus membership — and every declined
cell becomes one row in a curation queue, grouped by the input the rule could not decide from, so
that 28,392 declined cells reduce to 302 curator questions. The build cannot read `final/` at all:
the undeclared-input guard refuses it, so a rule cannot quietly reproduce the answer it is being
compared against. And a blank cell is never a claim — `audit/projection_provenance.tsv.gz` carries
`unresolved_reason` per cell, and `audit/build_manifest.json` states per column how many cells are
filled, how many are blank and how many were declined.

Every curation decision also gets a recorded outcome. `audit/decision_applications.tsv.gz` says what
became of each of the 3,168 ledger rows — applied and changed something, applied and made no
difference, filled a cell a rule declined, withdrawn, or reaching no canonical column — and a decision
with *no* row is a build failure. That is the D2 lesson as an artifact: the failure it prevents is an
assertion sitting in the ledger for two releases while the pipeline quietly recomputed the value. As
of release 3.0.0 the `field_not_projected` bucket is **empty**: every ledger field mapped to a
canonical column now reaches a rule that projects it.

### Release 3.2.0

`release/3.2.0/` is the dataset this pipeline produces end to end from public inputs. 3.0.0 was the
**major** break: `engineered_or_construct` flips TRUE to FALSE on 511 records (2.4.1's predicate
matched the database division code as free text, so it largely reported *where* a sequence was
deposited); `sequence_scope` is empty; and several thousand cells are blank-because-undetermined where
2.4.1 filled them from inputs this pipeline does not have.

3.1.0 closed 3.0.0's largest declared gap. `R-MEMBERSHIP-AA-1` now decides carve membership for
records whose GenBank lineage does not name the `Enterovirus` genus, by capsid **amino-acid**
p-distance to Sabin in the polyprotein reading frame — amino acids and not nucleotides because the
records in question are 1980s patent transcriptions of Sabin cDNA whose synonymous sites have
saturated, sitting ~20% away in nucleotide (right where the `wild` threshold lives) and 0.2-3% away
on the protein. The row set goes 24,285 -> 24,308: 23 added, none removed, no column semantics
changed, so a minor bump.

Fifteen of the 23 are records 2.4.1 carves and 3.0.0 could not reach. The other **eight are records
2.4.1 does not carve and the declared rule says it should** — six are byte-identical to a record the
release already carves (the same basis the release itself used to include `JA792237`-`251`), and two
are poliovirus capsid at 2.1% and 2.3% AA. `audit/membership_rescue.tsv` gives the distance, codon
count, or twin accession that admitted each one.

That the ledger already knew is the strongest evidence the old carve was wrong rather than merely
incomplete: `subject_outside_carve` in `audit/decision_applications.tsv.gz` falls from 18 to 6,
because twelve curator decisions had been asserting an origin, a sampling frame or a classification
about records the build was not carving.

3.2.0 adds two more things, both additive in the same sense as 3.1.0 — filling previously-blank
cells and writing previously-omitted files, never changing a value another consumer already read.

A curated `classification` decision now **entails poliovirus membership**, because the vocabulary it
comes from — `cVDPV`, `nOPV-L`, `wild` — is poliovirus-only. The rule that checks membership was
testing the organism name before the ledger, so 259 records named only `Enterovirus C` or
`Enterovirus coxsackiepol` (the polio-*containing* species, hence uninformative alone) declined
`virus_group`, and then declined `poliovirus_classification` for "following" a partition a
paper-based ledger decision had already settled. All 259 land on the value 2.4.1 already ships.
[`docs/classification-migration-gap.md`](docs/classification-migration-gap.md) accounts for every
one of the 2,159 remaining differences from 2.4.1's `poliovirus_classification` by category — mostly
epidemiological attribution (`cVDPV` vs `iVDPV` vs `wild`) that no property of a sequence carries.

Two audit views the build could already produce are now written: `audit/rules.tsv.gz`, which
reproduces the shipped file byte-for-byte, and `audit/vp1_divergence.tsv.gz`, the VP1 divergence
measurement `poliovirus_classification` was decided from and previously discarded after use.

It carries no wall-clock timestamp. `audit/build_manifest.json` identifies the build by the hashes of
its four determinants — the frozen archive, the decision ledger, the rule catalog, and the code — so
the same inputs produce the same bytes tomorrow, and a difference between two builds points at which
determinant moved. [`tests/test_release_integrity.py`](tests/test_release_integrity.py) re-checks
those same four hashes against the committed release directory on every test run, so a code or
registry change that lands without a matching rebuild fails immediately rather than shipping a
release whose manifest describes a build that no longer exists.

**What is still not true:** of `final/audit/` only `rules.tsv.gz` is regenerated; the rest of it,
`final/dictionaries/` and `final/alignments/` are not. And two records the shipped carve reaches are
not in this one — `E00765.1` and `E01571.1`, which land in R-MEMBERSHIP-AA-1's undecided 8-15% band.
Both look like patent transcription artifacts (their same-patent siblings sit at 0.2-0.6%), but
moving a published threshold to catch two records would be fitting the parameter to the answer, so
they stay a declared gap awaiting a curator decision about the patent text.

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
