# Rebuilt alignments

Multiple-sequence alignments built by this repository from `final/canonical/`, `final/source/` and
the committed covariance-model core under `registry/alignment_seeds/`, using only `mafft` and
Infernal's `cmalign`.

**Five of the six declared populations are committed here.** `align/contract.py` declares six;
`EV_unified` — the 24,301-row genus-wide artifact — has not been built. And the five are not one
uniform set: `POLIO_unified` and `NPEV_unified` were built with MAFFT `--ep 0.5`, while `PV1`,
`PV2` and `PV3` predate that parameter and carry the old gap-extension default. Each artifact's
`.provenance.json` records which, under `codon.gap_extend`, and the two later ones additionally
carry a `parameter_departures.gap_extend` note. A uniform rebuild of all six is pending; these
bytes are here to be compared against, not to be depended on.

```bash
pixi run -e align evgc alignment-build  --output-dir derived/alignments
pixi run -e align evgc alignment-verify --output-dir derived/alignments
pixi run -e align evgc alignment-shape  --output-dir derived/alignments
```

## Why `derived/` and not `final/`

`final/alignments/` holds the 2.4.1 release's alignments, which boundary 6 keeps immutable: a
baseline is never regenerated in place. These are the rebuild, kept beside it so the two can be
compared while the rebuild is reviewed. Promoting them into a new `releases/<version>/` and `final/`
is a separate, reviewed step, and it has to happen together with the site rebuild that depends on
those files.

## Four files per artifact

| file | what it is |
|---|---|
| `<name>.sto.gz` | the alignment, Stockholm, one dialect for all six |
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
