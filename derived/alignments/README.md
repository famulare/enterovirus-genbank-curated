# Rebuilt alignments

Multiple-sequence alignments built by this repository from `final/canonical/`, `final/source/` and
the committed covariance-model core under `registry/alignment_seeds/`, using only `mafft` and
Infernal's `cmalign`.

**All six declared populations are built here, at one parameter set, from the 4.0.0 canonical
table**, and promoted into `final/alignments/`. This directory is the build's working output; the
release copy is what consumers read.

The previous state is worth recording because it is what made the rebuild necessary rather than
cosmetic: five artifacts, no `EV_unified` at all, and two different gap-extension settings —
`POLIO_unified` and `NPEV_unified` carried MAFFT `--ep 0.5` while `PV1`/`PV2`/`PV3` predated that
lever. Each artifact's `.provenance.json` records its own parameters under `codon.gap_extend`, so a
mixed set is legible rather than assumed.

```bash
pixi run -e align evgc alignment-build  --output-dir derived/alignments
pixi run -e align evgc alignment-verify --output-dir derived/alignments
pixi run -e align evgc alignment-shape  --output-dir derived/alignments
```

## Why `derived/` as well as `final/`

`alignment-build` writes here, and promotion into `final/alignments/` is a separate, reviewed copy —
the same shape as `site/data/`, where the producer and the published copy are distinct steps. The
2.4.1 alignments these replaced are preserved at `releases/2.4.1/alignments/`, which is what
`alignment-shape` measures the declared delta against; a baseline is retired, not overwritten.

## Four files per artifact

| file | what it is |
|---|---|
| `<name>.sto.gz` | the alignment, Stockholm, one dialect for every artifact |
| `<name>_aln.fasta.gz` | the same rows as FASTA — a faithful projection, checked as one |
| `<name>.coverage.tsv.gz` | per record per block: present or absent, and why absent |
| `<name>.provenance.json` | every count recomputed from the rows, plus tool identity and hashes |

`evgc alignment-shape` additionally writes `shape_report.{json,md}` over whatever is present.

## What these are not

**Not byte-identical to the shipped alignments, and they cannot be.** The shipped bytes came from
code that no longer exists in that form, built at an unrecorded thread count with tie-breaking that
was deterministic only by accident. What replaces parity is the declared delta in the shape report:
exactly which accessions each rebuild adds and drops relative to the shipped file, with a reason per
dropped row from a closed vocabulary. An *undeclared* drop fails rather than being absorbed, which is
the property that keeps a real regression from hiding among adjudicated changes.

**Not lossless, in two places, both by construction.** The NCR blocks keep only `cmalign` match
columns, so insert-column residues are discarded. The anchored (`PV{n}`) CDS block is a projection
onto the reference's coordinate frame, so a query base with no reference position has nowhere to go.
Both are reported in the shape report's residue-occupancy distribution rather than hidden.

## Two properties worth knowing

The row set is **1-to-1 with `final/canonical/sequence_metadata.tsv.gz`** by construction: every
record in an artifact's declared population gets exactly one row, even one where nothing could be
placed. Such a row is all gaps, and `<name>.coverage.tsv.gz` says which blocks are absent and why —
so "no data here" stays distinguishable from "aligned and deleted" without inventing a new alignment
character.

For the three anchored artifacts, **every column is a real Sabin genome position**, because their
covariance models are `cmbuild --hand` against that serotype's own reference. The three block widths
therefore sum to exactly the reference genome length (7,441 / 7,439 / 7,432), the reference row
projected onto its own frame equals its genome byte-for-byte, and `#=GC RF` *is* that genome. All
three are checked by `evgc alignment-verify`.
