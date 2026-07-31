# Covariance-model core for the NCR structural block

Ten Infernal covariance models: four genus-wide, anchor-free models (`POLIO_unified`'s and
`NPEV_unified`'s 5' and 3' non-coding regions) and six per-serotype, Sabin-anchored models
(`PV1`/`PV2`/`PV3`'s 5' and 3' non-coding regions) — plus the seed alignment and seed Stockholm each
was built from. Copied from MAD-VDPV's own "reproducer core" (its `.gitignore` re-includes exactly
these files, for exactly this reason: `cmalign` re-runs without redoing the expensive seed-building
step).

## Why this tree exists, and why it is not regenerable in CI

Building one of the four genus-wide `.cm` files from scratch needs `mafft-xinsi` (to build the seed
alignment), `RNAalifold` (for the consensus secondary structure), and `cmbuild`. `mafft-xinsi` does
not work from a bare bioconda install — bioconda's `mafft` package omits the `mxscarnamod` helper
binary, so `mafft-xinsi`/`--qinsi` fail outright until it is compiled from a separate source
tarball. See `scripts/setup_mxscarna.sh`. The six per-serotype `.cm` files are built differently
(`cmbuild --hand` against a Sabin-anchored hand-RF Stockholm — see below) and so do not need
`mafft-xinsi` at all, but do still need `RNAalifold` and `cmbuild`.

Per Mike's decision (2026-07-30): commit all ten as declared, hash-pinned inputs-of-record. A
*routine* alignment build then needs only `mafft` + Infernal's `cmalign` — no network, no compiler,
no `mafft-xinsi`. The full rebuild path (`setup_mxscarna.sh` + `cmbuild`) exists behind a
file-presence gate — it runs only if these files are absent — and is documented as an optional
prerequisite **not expected to run even on a fresh clone**.

## What EV_unified uses

`EV_unified` does not build its own NCR covariance models. It reuses `npev_ncr_5p.cm` and
`npev_ncr_3p.cm` as-is (`cmalign` only), matching the shipped `EV_unified.provenance.json`'s
`cm_reused` field. Confirmed independently: MAD-VDPV's `grand_ev_unified` working tree carries no
`.cm` files of its own at all.

## Files

| file | serotype/side | match columns | population | seed |
|---|---|---:|---:|---:|
| `polio_ncr_5p.cm` | POLIO 5'NCR (anchor-free) | 746 | 2,036 | 80 |
| `polio_ncr_3p.cm` | POLIO 3'NCR (anchor-free) | 70 | 1,902 | 100 |
| `npev_ncr_5p.cm` | NPEV 5'NCR (anchor-free) | 738 | 2,198 | 83 |
| `npev_ncr_3p.cm` | NPEV 3'NCR (anchor-free) | 87 | 1,536 | 115 |
| `pv1_ncr_5p.cm` | PV1 5'NCR (Sabin-anchored) | 742 | 469 | 163 |
| `pv1_ncr_3p.cm` | PV1 3'NCR (Sabin-anchored) | 69 | 413 | 85 |
| `pv2_ncr_5p.cm` | PV2 5'NCR (Sabin-anchored) | 747 | 1,288 | 185 |
| `pv2_ncr_3p.cm` | PV2 3'NCR (Sabin-anchored) | 68 | 1,249 | 134 |
| `pv3_ncr_5p.cm` | PV3 5'NCR (Sabin-anchored) | 742 | 380 | 163 |
| `pv3_ncr_3p.cm` | PV3 3'NCR (Sabin-anchored) | 69 | 348 | 88 |

Each `<name>.cm` is paired with `<name>_seed.sto` (the seed alignment `cmbuild` was run against —
RNAalifold-annotated for the four genus-wide models, hand-annotated with true Sabin genome
coordinates for the six per-serotype ones) and `<name>_seed_aln.fa` (the same alignment as plain
FASTA). The four genus-wide match-column counts equal each artifact's shipped `block_widths` entry
(`final/alignments/{POLIO,NPEV}_unified.provenance.json`) exactly; the `population`/`seed` counts
for the six per-serotype models are upstream's own historical build numbers, recorded for
provenance only — see `seed_provenance.json`'s `population_note` for why they are not directly
comparable to the genus-wide models' population counts.

The four genus-wide models are **not** built `cmbuild --hand` — they use Infernal's default
`--symfrac` occupancy consensus, because there is no genus-wide reference genome to hand-anchor
them to. The six per-serotype models **are** built `cmbuild --hand`: each consensus column is a
real position in that serotype's own Sabin reference genome (`AY184219`/`AY184220`/`AY184221` for
PV1/PV2/PV3), not an occupancy-driven pick — the RF line, once cmalign'd, reads out the true Sabin
nucleotide at every match column. `seed_provenance.json`'s `cmbuild_hand` field records which
convention built each file.

## Scrubbing

Each `.cm`'s `COM` line (recorded twice — the outer header and an internal HMM-filter copy) named
an absolute local build path, and its `DATE` line a non-reproducible build timestamp. Both are
replaced with fixed placeholder text before commit; `seed_provenance.json` records the real source
commit instead. Every scrubbed file was re-verified to still run under `cmalign` (exit 0, well
formed Stockholm output) after scrubbing.

## Hashes

`seeds.sha256` pins every file in this directory (`sha256sum -c seeds.sha256` from here). `evgc
alignments verify-seeds` re-hashes them and cross-checks each `.cm`'s match-column count against
`seed_provenance.json`, so a swapped or truncated model fails on every push with no native
toolchain required.

## What is *not* here, deliberately

Not brought over: upstream's `*_segmentation.csv` and `*_block.ss`/`*_block.fasta` (genus-wide
stack), or `input_*.fasta`/`production_*.sto` (per-serotype stack). Those describe upstream's own
per-record segmentation, NCR block extraction, and production-population alignment, in upstream's
schema, over upstream's own population — they have no consumer in this repository, whose
segmentation and population selection are declared independently in `align.segment` /
`align.contract` / `align.anchored` rather than reusing a private intermediate.
