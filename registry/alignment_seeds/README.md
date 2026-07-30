# Covariance-model core for the NCR structural block

Four Infernal covariance models — `POLIO_unified`'s and `NPEV_unified`'s 5' and 3' non-coding
region models — plus the seed alignment and seed Stockholm each was built from. Copied from
MAD-VDPV's own "reproducer core" (its `.gitignore` re-includes exactly these files, for exactly
this reason: `cmalign` re-runs without redoing the expensive mafft-xinsi seed step).

## Why this tree exists, and why it is not regenerable in CI

Building one of these `.cm` files from scratch needs `mafft-xinsi` (to build the seed alignment),
`RNAalifold` (for the consensus secondary structure), and `cmbuild`. `mafft-xinsi` does not work
from a bare bioconda install — bioconda's `mafft` package omits the `mxscarnamod` helper binary,
so `mafft-xinsi`/`--qinsi` fail outright until it is compiled from a separate source tarball. See
`scripts/setup_mxscarna.sh`.

Per Mike's decision (2026-07-30): commit these as declared, hash-pinned inputs-of-record. A
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
| `polio_ncr_5p.cm` | POLIO 5'NCR | 746 | 2,036 | 80 |
| `polio_ncr_3p.cm` | POLIO 3'NCR | 70 | 1,902 | 100 |
| `npev_ncr_5p.cm` | NPEV 5'NCR | 738 | 2,198 | 83 |
| `npev_ncr_3p.cm` | NPEV 3'NCR | 87 | 1,536 | 115 |

Each `<name>.cm` is paired with `<name>_seed.sto` (the hand/RNAalifold-annotated seed alignment
`cmbuild` was run against) and `<name>_seed_aln.fa` (the same alignment as plain FASTA). Match
columns above equal each artifact's shipped `block_widths` entry
(`final/alignments/{POLIO,NPEV}_unified.provenance.json`) exactly — the check that confirms these
are the right models, independent of the source repository being unavailable here.

None of the four is built `cmbuild --hand`; all use Infernal's default `--symfrac` occupancy
consensus, because there is no genus-wide reference genome to hand-anchor them to (that convention
is reserved for the Sabin-anchored `PV{1,2,3}_unified` stack, built differently). See
`seed_provenance.json` for full detail.

## Scrubbing

Each `.cm`'s `COM` line (recorded twice — the outer header and an internal HMM-filter copy) named
an absolute local build path, and its `DATE` line a non-reproducible build timestamp. Both are
replaced with fixed placeholder text before commit; `seed_provenance.json` records the real source
commit instead. Every scrubbed file was re-verified to still run under `cmalign` (exit 0, well
formed Stockholm output) after scrubbing.

## Hashes

`seeds.sha256` pins every file in this directory (`sha256sum -c seeds.sha256` from here). `evgc
alignments verify-seeds` (added in a follow-up commit) re-hashes them and cross-checks each `.cm`'s
match-column count against `seed_provenance.json`, so a swapped or truncated model fails on every
push with no native toolchain required.

## What is *not* here, deliberately

Not brought over: upstream's `*_segmentation.csv` and `*_block.ss`/`*_block.fasta`. Those describe
upstream's own per-record segmentation and NCR block extraction, in upstream's schema, over
upstream's (narrower, evidence-gated) population — they have no consumer in this repository yet,
and this repository's own segmentation stage (when it lands) derives directly from
`final/source/normalized_tsv/` rather than reusing a private intermediate.
