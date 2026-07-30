# site/ — the data explorer

The static exploration surface published at
<https://famulare.github.io/enterovirus-genbank-curated/>.

Four figure sets over one shared selection state: synonymous versus non-synonymous
divergence, multidimensional scaling of nucleotide distance, nucleotide phylogeny,
and amino-acid phylogeny. Its purpose is to make the structure in the release
legible at a glance and to make misclassification noticeable.

**Figure sets 1 and 2 ship.** Both are the same instrument, from the same component
in `src/ui/chapter.ts`: a strip of live region thumbnails above one focus panel, with
drag-to-brush zoom, per-panel auto-scaling, seven colored categories plus Other with
glyph co-encoding, hover and full keyboard traversal, and click-to-pin showing every
canonical field. Pinning a record in one chapter highlights it in the other. All state
lives in the URL hash, so any view is a shareable link.

- **Set 1, divergence** — synonymous against non-synonymous codon differences from a
  reference, over four coding regions. Square-root or linear axes.
- **Set 2, distance** — classical multidimensional scaling of pairwise nucleotide
  distance, over five regions including both non-coding ones, which it can reach
  because it needs no reading frame.

The square-root toggle does something different in each, which is why one control
serves both. In set 1 it transforms the drawn **axis**. In set 2 it selects which
**embedding** to show: the one fitted to the distances, or the one fitted to their
square roots. The drawn axis there is always linear, because scaling coordinates are
signed.

Scaling square roots is not cosmetic. Masked Hamming distance is not Euclidean, so
part of the geometry cannot be drawn in a plane at all — up to 44% of it in the 3'NCR.
Square roots usually fix that. Measured on this release, the non-Euclidean share falls
from 0.199 to 0.037 (PV1 5'NCR) and from 0.436 to 0.159 (PV1 3'NCR), and reaches
**exactly zero** for the non-polio 5'NCR and P1. Across all twenty-five panels the
selftest asserts no panel is made less Euclidean, twenty-five improve, and five become
exact.

Two dimensions then carry less of the variance — 0.61 down to 0.51 for PV1 P1 — and
that is not a real loss. Under the linear fit part of that 0.61 rested on a geometry a
plane could not honestly represent; under the square root the geometry is sound and
the variance is spread across dimensions that genuinely exist.

Sets 3 and 4, the two phylogenies, carry placeholders naming what lands there.

## Reproducing from a fresh clone

Two independent toolchains, in this order.

```bash
uv run --no-project site/pipeline/cli.py build   # final/ -> site/data/
npm --prefix site ci && npm --prefix site run build
```

The Python step needs only `uv`; dependencies are declared inline in
[`pipeline/cli.py`](pipeline/cli.py) (PEP 723) rather than in the project's
`pyproject.toml`, so it does not require installing the package being rewritten
alongside it. The Node step needs Node 23.6 or newer — `npm test` runs the TypeScript sources
directly and relies on unflagged type stripping. Declared in `package.json` engines.

To review locally:

```bash
npm --prefix site run serve
```

### Later stages will add a tree builder

Stages 3 and 4 build neighbour-joining trees from the same masked distance
matrices the MDS uses, so the tree and the embedding cannot disagree about how
partial sequence overlap was handled. That requires a distance-matrix tree tool,
which is not in Homebrew:

```bash
git clone https://github.com/iqtree/decenttree ~/.local/src/decenttree
cmake -S ~/.local/src/decenttree -B ~/.local/src/decenttree/build -DCMAKE_BUILD_TYPE=Release
cmake --build ~/.local/src/decenttree/build -j
ln -s ~/.local/src/decenttree/build/decenttree ~/.local/bin/decenttree
```

`rapidNJ` (<https://github.com/somme89/rapidNJ>) is the fallback if that build
fails; it implements the same algorithm family and takes the same PHYLIP input.
`site/data/manifest.json` records whichever version actually produced the
committed trees.

## Why the data is committed rather than built on deploy

Distances are cheap (~30 s for the full 24,038² masked-Hamming matrix), but the
trees are not, and the tree builder needs a source build that has no business in a
Pages workflow. So the derived artifacts under `site/data/` are committed, and
`.github/workflows/ci.yml` runs

```bash
uv run --no-project site/pipeline/cli.py check
```

on every push. That recomputes the SHA-256 of every `final/` file the build read,
plus the hashes of the pipeline sources themselves, and fails if any differs from
what the manifest recorded. A data change cannot silently ship a stale figure.
Build identity is derived from those hashes rather than from the git SHA, so two
runs over the same inputs produce the same identity.

## Layout

```
pipeline/          Python. Reads final/, writes site/data/.
  contract.py        THE ONLY place naming a final/ path or a canonical column
  frame.py           Alignment loading; region -> alignment column mapping
  traits.py          Canonical records plus derived species / concordance / date
  reference.py       What each sequence is measured against (set 1)
  divergence.py      The synonymous / non-synonymous metric (set 1)
  distances.py       Masked pairwise distance and landmark choice (sets 2-4)
  embed.py           Classical scaling with out-of-sample placement (set 2)
  scaling.py         One region's embedding, assembled (set 2)
  records.py         The shared record table every figure reads
  panels.py          Per-selection artifacts the browser loads
  summary.py         The counts, catalogs and caveats the page opens with
  manifest.py        Input hashing and the staleness gate
  selftest.py        Correctness checks; `cli.py selftest`
  cli.py             `build`, `check`, `selftest`
data/              Committed derived artifacts + manifest.json
src/               TypeScript. model/ is DOM-free and unit-tested; ui/ renders.
  ui/chapter.ts      ONE figure component; both chapters are instances of it
  model/specs.ts     What each chapter adds beyond that component
  model/mark.ts      The boundary between them: what a scatter draws
test/              node --test over model/
scripts/           esbuild build, and a dev server
tokens.css         Vendored from the scientific-page-style kit
dist/              Built output. Gitignored; what Pages publishes.
```

`pipeline/contract.py` is the blast-radius firewall. The generation pipeline is
being rewritten upstream, so every path into `final/` and every canonical column
name is declared there once. Two changes are already expected and are marked
`# UPCOMING:` — `collection_date` normalizing to ISO, and an added date-range
field. A `# SWITCHOVER:` note marks where the derived species trait moves to a
native canonical column once one exists.

`collection_date` stays canonical, holding the value as GenBank recorded it, so the
parsed decimal year is a permanent derived field rather than a stopgap. The record
inspector shows both, the derived one tagged and separately labelled — they were briefly
two rows called "Collection date" with different values, which is worse than either
alone.

## Deviations from the scientific-page-style kit

The kit is at `~/git/famulare/my_environments/web/scientific-page-style/` and is
installed as a skill at `.claude/skills/scientific-web-style`. Three deliberate
departures, each recorded here because the kit's coherence depends on deviations
being visible:

1. **Canvas for mark layers, SVG for everything else** (from Stage 1 on). The kit
   is SVG-first for figures, but these panels carry 3,700 to 24,000 marks, which
   pure SVG cannot render interactively. Axes, legends, labels and annotations stay
   SVG, so the typography and rule vocabulary are unchanged.
2. **Readable URL-hash parameters** instead of base64url canonical JSON. The kit's
   recipe guards against float-formatting drift in a scenario object; this state is
   six short enumerated values with no floats, and a reader of a data explorer will
   want to hand-edit a link. Validation is still strict — an unrecognized value
   degrades to the default and is reported in the status line, never accepted.
3. **A smaller `--fs-display`** and tighter hero padding. On an essay the display
   size can own the first screen; here the reader must reach the control bar and
   the top of a figure without scrolling. The body-size floor is untouched.

## What the divergence metric is not

The first figure set counts synonymous and non-synonymous codon differences from a
reference and divides each by the number of codons the two sequences can be compared
at: those where both carry three unambiguous bases, **plus** those an insertion or
deletion touches. It is **not** the query's sequence length — an ambiguity code or a
both-gapped position lowers the denominator without contributing a difference.

Indels are charged one non-synonymous difference **per codon they touch**, and those
codons join the denominator. That pairing is what keeps both axes inside 0-1 with
x + y <= 1, and the selftest asserts it over every point in every built panel.
Charging one count per indel *event* against a comparable-codon denominator does not
bound the axes: a patchy fragment can span 900 nt while contributing only 68
comparable codons, and its non-synonymous rate then exceeds 1.

The metric is **not dN/dS**: there is no per-synonymous-site or
per-non-synonymous-site normalization and no multiple-hit correction, and it is not
an evolutionary rate. It is an uncorrected similarity metric, chosen because it
keeps both axes on one interpretable 0–1 scale and keeps partial sequences
comparable to whole genomes. The page says so where the figure is, not only here.

Figure set 2 normalizes the same way, per pair: distance is mismatches divided by
the number of alignment columns where **both** sequences carry an unambiguous base.

## Reference choice, and one rejected design

Poliovirus is measured against the Sabin genome of its serotype. Non-polio
enterovirus is measured against a consensus of **its own virus type** — and against
nothing else.

An earlier version stepped outward when a type was too thin: type, then species,
then genus. That was wrong, and the figure showed it. An enterovirus species holds
dozens of serotypes that differ across roughly a quarter of the capsid, so a
per-column majority over a whole species is a chimera, and distance from it folds
"how unusual is this type within its species" into "how far has this sequence
drifted within its type" — two quantities that cannot share an axis. Empirically,
records assigned a species consensus were 11× over-represented among the points
above 1.0 non-synonymous per codon, and dropping the rung removed 188 of the 349
such points and pulled the maximum from 2.55 to 1.78.

### Known limitation in the consensus, left in place on purpose

`reference._consensus` marks a column as carrying a base whenever **any** contributor
has one. For a large, fragmentary type that makes the consensus a *union* of coverage
rather than a typical genome, so a partial record reads as deleted at every column it
does not span but some same-type record does. Its indel-codon count — and therefore
its non-synonymous rate — inflates in proportion to how fragmentary its type is.

Measured on release 2.1.5: 487 of 13,160 non-polio polyprotein records exceed 0.5
non-synonymous per codon, and **81%** of that group's numerator is indel codons. They
concentrate in the largest types (CVA24 238, CVA13 81), exactly as the mechanism
predicts.

This is not patched here. The consensus is a stand-in for per-type reference sequences
the release does not yet carry for non-polio; a quorum rule bolted onto a stand-in
would trade one artifact for another. The fix is upstream. Until it lands the artifact
is stated in the figure's own method disclosure, so a reader meets it where it matters
rather than discovering it later.

A record whose type is unrecorded or too thin is therefore reported **unmeasurable**
in figure set 1, with a count on the figure. In the release as it stands that is 890
of 14,050 aligned non-polio records: 1,121 carry no `virus_type` at all and 160 sit
in one of 74 types holding fewer than five sequences. Neither is a data error —
they are limits of what GenBank records — and neither costs the record its place in
the reference-free views.

## Data problems are reported, never repaired

The closing chapter counts data-quality issues live from the release, so each entry
disappears on its own once the generation pipeline fixes it upstream. Nothing in
`site/` patches a value. If a fix is needed it happens at the source and the
release is regenerated.
