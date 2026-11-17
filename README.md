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
final/                Release 5.0.0 — what this pipeline produces, rebuilt from raw/ and
                      registry/ alone. A build destination, not a comparison target: a
                      guarded build may write it and may not read a file it did not write.
releases/2.4.1/       The superseded release, retired rather than rewritten: its parity
                      contract, and the eighteen alignment files evgc alignment-shape
                      still measures the declared delta against. (releases/2.1.5/ and
                      releases/2.3.0/ are historical records, no longer verified against
                      the tree — see src/enterovirus_genbank_curated/contracts.py.)
derived/alignments/   Where evgc alignment-build writes; final/alignments/ is the promoted
                      copy, promoted into final/alignments/.
docs/                 Pipeline architecture and the reproducibility boundary.
```

## Data model at a glance

Every included sequence gets one row in `final/canonical/sequence_metadata.tsv.gz`, keyed by
`version` (the GenBank `accession.version`). `curation_status` records **how much curatorial attention a record has had**, which is not the
same question as any other column answers. `vouched` means the maintainer has gone over these
records directly — scanning the distributions and outliers on the explorer site, and reading them
against the poliovirus literature — to make them as correct as he can. `provisional` means that
depth of review has not happened yet.

Today that lands exactly on the partition: all 10,087 poliovirus records are `vouched` and all
14,218 non-polio ones are `provisional`, because the review has covered poliovirus and not yet
covered non-polio EV. The two columns therefore carry the same *bits* right now and different
*claims*, and they will separate the first time a non-polio family is reviewed. Read
`curation_status` as a statement about the reviewing, not as a restatement of `virus_group`.

Every curated field (classification, sample origin, surveillance stream, collection date, virus
type, ...) has a corresponding row in `final/audit/projection_provenance.tsv.gz` naming
exactly which upstream field it was projected from, under which versioned rule
(`final/audit/rules.tsv.gz`), and whether a human decision touched it — traceable to the specific
decision in `registry/decisions.tsv`, through
`final/audit/decision_applications.tsv.gz`.

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
into `raw/`, the frozen input.

**Canonical metadata regenerates in part, and the part is precisely stated:**

```bash
evgc check-declines                # every declined cell equals its declared count
evgc build-metadata --output final # write the whole dataset, manifests included
```

From `raw/` and `registry/` alone this carves the canonical row set and fills **all 26 canonical
columns**.

*Thirteen transported columns* — identity, sequence hash and length, taxid, organism,
isolate/strain/host, parsed country/admin1/locality, BioSample — where the canonical value **is** the
GenBank value. Every cell equals the shipped cell, in the same row order.

*Fourteen projected columns*, each produced with a machine-readable provenance row naming the rule that
decided it and which branch of that rule fired: `virus_group`, `curation_status`, `virus_type`,
`poliovirus_classification`, `sample_origin`, `surveillance_stream`, `specimen_type`,
`collection_date`, `collection_date_precision`, the `collection_year_*` pair, `sequence_scope` and
`engineered_or_construct` — plus `locality`, which is both transported and projected. Several
deliberately **differ** from the release, because the shipped value asserted a determination that was
never made; each break retires a weak guarantee, states a stronger one enforced against the build's
own output, and pins the difference as an exact count *and a witness hash over the disagreeing
records*, so a substituted disagreement fails the gate even when the count does not move.

**`sequence_scope` was the last column written, and it was unwritten for the wrong reason.** It was
recorded as blocked on coverage geometry: fitted against every threshold combination, coverage
against Sabin VP1 agrees with the shipped column on only 86.7% of poliovirus records, with
systematic rather than boundary errors — 745 records the release calls `other_fragment` have a
complete VP1, capsid or genome. The measurement was right and the model was wrong. Scope is a
statement about a deposit's own *annotation*, not about how much genome it spans, so no threshold on
coverage was ever going to find it. Read as a seven-branch precedence over which region the record
names, `R-SCOPE-2` reproduces 2.4.1's column on **every one of the 24,296 rows both tables carry**,
and the 745 are where its final `else` correctly lands.

What that same stage *does* support is classification. `poliovirus_classification` is decided by
nucleotide divergence from the matching Sabin reference — VP1 first, and where VP1 alone is absent
or too short, the whole capsid (VP4-VP2-VP3-VP1) as a guarded fallback — using the thresholds the
release already publishes in its own rule table — Sabin-like below 1% (0.6% for PV2), wild at or
above 15%. Measured before those parameters were read, every `Sabin-like` record in the release sits
below 1% and every `wild` record above 18%, so the published thresholds are recovered from the data
rather than imposed on it.

Three properties matter as much as the coverage. A rule that cannot decide from declared inputs
**declines** rather than guessing — 12,617 records whose `/isolation_source` carries no specimen
keyword, 1,789 whose organism name and definition line both state no type, 475 whose classification
no sequence or ledger row settles, and **zero** whose membership is unsettled — and every declined
cell becomes one row in a curation queue, grouped by the input the rule could not decide from, so
that 25,061 declined cells reduce to 268 curator questions. The build cannot read `final/` at all:
the undeclared-input guard refuses it, so a rule cannot quietly reproduce the answer it is being
compared against. And a blank cell is never a claim — `audit/projection_provenance.tsv.gz` carries
`unresolved_reason` per cell, and `audit/build_manifest.json` states per column how many cells are
filled, how many are blank and how many were declined.

Every curation decision also gets a recorded outcome. `audit/decision_applications.tsv.gz` says what
became of each of the 4,900 ledger rows — applied and changed something, applied and made no
difference, filled a cell a rule declined, withdrawn, or reaching no canonical column — and a decision
with *no* row is a build failure. That is the D2 lesson as an artifact: the failure it prevents is an
assertion sitting in the ledger for two releases while the pipeline quietly recomputed the value. As
of release 3.0.0 the `field_not_projected` bucket is **empty**: every ledger field mapped to a
canonical column now reaches a rule that projects it.

### Release 5.0.0

`final/` **is** release 5.0.0 — the dataset this pipeline produces end to end from public inputs.

4.1.0 is a curation-only correction on top of 4.0.0: thirteen accession-level
`poliovirus_classification` decisions in [`registry/decisions.tsv`](registry/decisions.tsv), no rule
change, no threshold change, no column semantics change. `AY563379` -> `VDPV`; `KR817054`/`55`/`56`/
`60` -> `iVDPV` (the 28-year immunodeficient-shedder series, whose lineage lives in the paper rather
than in the divergence band); `CS406483` and its byte-identical twin `PU749298` -> `engineered/lab`,
so the classification tier says what `engineered_or_construct=TRUE` already said; `OR208593`/`600`/
`605`/`612` -> `chimera`, as accession-level overrides rather than a revival of the reverted
generalized recombinant rule; and `AF065158` and `AB467472` were recorded confirmations of `wild`,
against papers whose titles could have been read the other way. Eleven cells change value, two
confirmed the value the band already reached.

**Those last two confirmations were wrong, and 2026-08-16 overturns both** — `AF065158` -> `VDPV`,
`AB467472` -> `Sabin-like`. The papers' titles could not, in fact, have been read the other way: one
is *"A Sabin vaccine-derived field isolate ... including a deletion in antigenic site 1"* and the
other is an mOPV1 shedding series on a deposit whose own `/strain` qualifier reads `Sabin 1`. What
the band reached was an artifact of that very deletion — both records carry a 6 nt in-frame deletion
in the VP1 BC loop, `compare_vp1` is ungapped and fitted its diagonal downstream of it, and the
~300 nt upstream then read at the unrelated-sequence rate and averaged in to 26%. Measured in
`final/alignments/`, they sit at 0.33% and 0.66% from Sabin 1. Confirming a band value is only worth
recording when the band value was independently checked; here that check was the missing step, and a
confirmation made the error harder to see rather than easier.

4.0.0 shipped the accumulated 3.0.0-3.3.0 line below as one major bump: reconciliation against the
hand-curated 2.4.1 baseline is now complete in the sense this pipeline can make that claim (every
one of the remaining `poliovirus_classification` differences is categorized, not just counted —
see [`docs/classification-migration-gap.md`](docs/classification-migration-gap.md)), and it pairs
that metadata with reference multiple-sequence alignments built by this repository rather than
carried from a private pipeline.

3.0.0 was the **major** break within that accumulated line: `engineered_or_construct` flips TRUE to
FALSE on 502 records (2.4.1's predicate matched the database division code as free text, so it
largely reported *where* a sequence was deposited), and several thousand cells are
blank-because-undetermined where 2.4.1 filled them from inputs this pipeline does not have.
`sequence_scope` was empty then too; 5.0.0 writes it.

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

Two audit views the build could already produce are now written: `audit/rules.tsv.gz`, which
reproduces the shipped file byte-for-byte, and `audit/classification_divergence.tsv.gz`, the
divergence measurement `poliovirus_classification` was decided from and previously discarded after
use.

3.3.0 adds a fallback to the same rule, for records VP1 alone cannot classify. 1,911 carved,
name-serotyped records have no usable VP1 at all; `derive/evidence.compare_capsid_nt` measures
divergence over the whole capsid (VP4-VP2-VP3-VP1) instead, over the same thresholds — the same
VP1-first / P1-fallback precedence the upstream sequence classifier states outright. 148 records
newly resolve, every one agreeing with the shipped classification wherever 2.4.1 has one to compare
against.

The fallback needed a guard VP1 alone does not — at the time. VP1 in poliovirus has no indels
relative to Sabin — measured, and the reason an ungapped single-offset comparison is exact there —
but that fact does not extend to VP4, VP2 or VP3, and two records surfaced it directly: a run of
mismatches at the unrelated-sequence rate beginning at one exact position, resolved by shifting the
query **one nucleotide** from that point on. A real indel in a coding, replicating poliovirus genome
must be a multiple of three to preserve the reading frame, so a one-nucleotide break is a single bad
base call in the deposit, not biology. `derive/evidence.py` declines the whole comparison when any
150 nt chunk of it deviates from the window's own divergence by more than a measured floor — the
three broken windows this found sit at 21.5, 21.8 and 55.2 percentage points of internal deviation;
the next-highest genuine one sits at 8.1.

`MIN_VP1_NT`/`MIN_CAPSID_NT` later dropped from 300 to the upstream published floor, 50 nt,
recovering 60 more declines, every one agreeing with the shipped classification — but lowering the
floor without protection surfaced the same single-bad-base failure in VP1 for the first time
(`AY320423`, `JN092124`, `AY365233`, each 15-24 points more divergent than the upstream alignment
over a 171-225 nt window), because the old 300 nt floor had always been enough sequence to dilute one
bad call rather than be defined by it. `compare_vp1` now shares `compare_capsid_nt`'s
chunked-homogeneity guard below the old floor, unchanged at or above it.

Two more mechanisms close most of what was left. A reference-title text fallback
(`derive.classification._group_b_text_fallback`) reads the cited paper's title — a new
`RecordView.reference_titles` input, never read anywhere else — for `wild`/`VDPV`/`Sabin-like` only,
and fires only where no divergence measurement exists at all: 708 records resolve, 705 agreeing with
the shipped value (3 do not, traced to a diagonal-search bug on those specific records rather than a
text-matching error — see `oracle/parity.py`). Isolate-linked inference
(`derive/isolate_linkage.py`) is a whole-corpus pass, not a per-record rule — it runs once every
`poliovirus_classification` row is projected and inherits a value from a sibling accession sharing
the depositor's own `isolate`/`strain` name and serotype, when every such sibling with a *measured*
classification (never a decision or the text fallback — propagating either would compound whichever
one is wrong) agrees on one label: 191 more resolve, 190 agreeing (the one that does not is the
known Mahoney/Sabin-1 trap below, reaching a second record through the link).

A fourth mechanism closes most of what `virus_group` itself was still declining. `R-MEMBERSHIP-AA-1`
was already active for carve membership — a record's capsid under 8% amino-acid distance from a
poliovirus reference rescues it into the carve even when GenBank's own lineage annotation excludes
it. The catalog always declared the rule's other half too: the same two-sided band (below 8% rescues
to `poliovirus`, at or above 15% confirms `non_polio_enterovirus`) for a carved record whose organism
name only reaches `Enterovirus C`, `Enterovirus sp.`, `unidentified` or `synthetic construct` —
`derive.evidence.measure_poliovirus_membership_band`, built 2026-08-01, implements it. 211 records
resolve, 209 of them agreeing with the shipped `virus_group` (2 are not in the shared carve at all).
`poliovirus_classification` benefits too: a `poliovirus`-banded record has no name serotype by
definition, but the band's own nearest-capsid match already identified one, and the classification
rule now measures VP1/capsid divergence against it exactly as it would a name-stated serotype — 138
more records resolve, 130 agreeing with the shipped classification.

[`docs/classification-migration-gap.md`](docs/classification-migration-gap.md) accounts for every
one of the 525 remaining differences from 2.4.1's `poliovirus_classification` by category — 97.8%
of the shared carve agrees, and 465 of the 525 are a decline rather than a contradiction. The
epidemiological refinement `cVDPV`/`iVDPV` is now emitted wherever the record itself states it,
including from `isolation_source` and `note`; the 95 that were not are two published environmental
studies whose circulation claim lives in the paper rather than in any deposit, and a further 28
strain-identity/patent (`reference_or_lab_text`) and unpublished-reference (`group_A_text_owned`)
records are likewise now decisions rather than declines — all traced by decomposing the largest
remaining discrepancy block into the upstream pipeline's own named mechanisms. Only the 4 `chimera` records remain
outside the sequence rule's reach — a recombination-detection rule was built and reverted after it
misclassified 192 other records, see the migration-gap doc for why.

It carries no wall-clock timestamp. `audit/build_manifest.json` identifies the build by the hashes of
its four determinants — the frozen archive, the decision ledger, the rule catalog, and the code — so
the same inputs produce the same bytes tomorrow, and a difference between two builds points at which
determinant moved. [`tests/test_release_integrity.py`](tests/test_release_integrity.py) re-checks
those same four hashes against the committed release directory on every test run, so a code or
registry change that lands without a matching rebuild fails immediately rather than shipping a
release whose manifest describes a build that no longer exists.

**What is still not true:** one file under `final/` has no producer here —
`audit/sequence_evidence.tsv.gz`, the alignment layer's tier oracle, which waits on the deferred EV
reference-panel pass. And two records the shipped carve reaches are not in this one — `E00765.1`
and `E01571.1`, which land in R-MEMBERSHIP-AA-1's undecided 8-15% band.
Both look like patent transcription artifacts (their same-patent siblings sit at 0.2-0.6%), but
moving a published threshold to catch two records would be fitting the parameter to the answer, so
they stay a declared gap awaiting a curator decision about the patent text.

For `final/alignments/`, the alignment layer builds its own. `evgc alignment-build` writes Stockholm
and FASTA artifacts for **all six** declared populations into `derived/alignments/`, and promotion
into `final/alignments/` is a separate reviewed copy. `evgc alignment-shape` reports each one's shape
against the retired 2.4.1 alignments, which are kept in `releases/2.4.1/alignments/` as the
comparand. They are not byte-identical to those files and cannot be — that code no longer exists in
that form, and was run at an unrecorded thread count. What replaces byte parity is a declared delta.
See [`docs/reproducibility.md`](docs/reproducibility.md) for the measured gaps and the build times.

`final/` is the build's own destination and never a pipeline input: a build cannot read a file
under `final/` that it did not write in the same run. The reproducibility claim changes only after
a fresh clone regenerates the release from declared public inputs and passes the complete parity
contract — stage 8 of [`docs/pipeline.md`](docs/pipeline.md), not yet delivered. See
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

Note that three version numbers coexist and are independent: the **data release** is 5.0.0
(`CITATION.cff`, and `release_version` in `final/audit/build_manifest.json`), the canonical
**schema** is 2.4.1 (`schema_version` in the same manifest), and the Python package version is
0.0.0.

## Licensing and citation

- **Code** — MIT, see [`LICENSE`](LICENSE).
- **Curated data** — dedicated to the public domain, see [`LICENSE-DATA`](LICENSE-DATA) (CC0-1.0).
- **Underlying GenBank records** — see [`NOTICE`](NOTICE) for the upstream data notice and
  submitter-rights caveat.
- If this data is useful to your work, a citation is appreciated but not required — see
  [`CITATION.cff`](CITATION.cff).
