# site/ — the data explorer

The static exploration surface published at
<https://famulare.github.io/enterovirus-genbank-curated/>.

Five figure sets over one shared selection state: synonymous versus non-synonymous
divergence, multidimensional scaling of nucleotide distance, nucleotide phylogeny,
multidimensional scaling of protein distance, and protein phylogeny. Its purpose is to
make the structure in the release legible at a glance and to make misclassification
noticeable.

All five are the same instrument, from the same component in `src/ui/chapter.ts`: a
strip of live region thumbnails above one focus panel, with drag-to-brush zoom,
per-panel auto-scaling, seven colored categories plus Other with glyph co-encoding,
hover and full keyboard traversal, and click-to-pin showing every canonical field.
Pinning a record in one chapter highlights it in all of them. All state lives in the URL
hash, so any view is a shareable link.

- **Set 1, divergence** — synonymous against non-synonymous codon differences from a
  reference, over four coding regions. Square-root or linear axes.
- **Set 2, distance** — classical multidimensional scaling of pairwise nucleotide
  distance, over five regions including both non-coding ones, which it can reach
  because it needs no reading frame.
- **Set 3, nucleotide phylogeny** — neighbor joining on those same distances, over the
  same five regions.
- **Set 4, protein distance** — set 2 again in residue space, for the three coding
  regions. Read against set 2: structure that survives translation is structure in the
  protein, and structure that disappears was synonymous all along.
- **Set 5, protein phylogeny** — set 3 in residue space, over the same three regions.

Residue space is not a second metric. `distances.py` is parameterized over an `Alphabet`,
so the nucleotide and protein figures run one procedure over one definition, and
`distances.in_alphabet` is the single place a nucleotide floor becomes a codon floor —
rounded **up**, so a record in a protein figure is always in the nucleotide figures too.

### The axis is set by the placements the figure trusts

The two scaling figures take their default range from the confidently-placed marks only.
Letting the least reliable mark define the frame contradicts the encoding: a thin mark is
already drawn smaller *because* its position is approximate. On PV1's protein scaling,
seven records carrying 19 readable codons out of 881 stretched the second axis to 1.66 and
squashed 3,158 confident placements into 3% of it. Thin marks inside the resulting range
still draw, and each panel states how many fall outside — 134 on that panel, 10 on its
nucleotide counterpart, which is how little this changes a healthy one. The trees are
excluded from this rule: clipping a tip would leave its branch running off the panel.

A tree is a scatter with a link layer: x is distance from the root, y is position in the
ladder, and one mark per tip. That is why the trees reuse the component rather than
getting one of their own — the color scale, legend, hover, brush, pin and keyboard
traversal are all the same code, and a reader does not relearn the controls between
chapters. What a tree adds is an ordinal vertical axis, which carries no ticks because a
place in a ladder is not a quantity, and a taller panel.

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

### Sets 3 and 5: not every sequence can be on a tree

Neighbor joining needs a distance for every pair, and pairwise deletion does not
supply one — two fragments covering disjoint parts of a region share no columns, so
their distance does not exist. The tips are therefore
`distances.comparable_set`: the largest mutually-comparable set a greedy finds,
capped at 2,500 for cost. Every panel states how many sequences that left off, and
those sequences are still in the scaling views, which need no complete matrix.

That set is ordered by **overlap degree**, not by coverage, and the difference is
large. Ordering by coverage admits the longest sequence first, and one early fragment
covering only VP4 then rejects every VP1-only record behind it. On PV1's P1 that kept
672 of 3,442 attainable sequences; degree ordering starts from the part of the region
everything covers — VP1, which is the typing gene and therefore why a record is in the
alignment at all — and reaches the cap. Figure 2 gained from the same change: PV1 P1
now embeds 1,500 landmarks exactly where it embedded 652, and PV3 P1 1,360 where it
embedded 409.

Branch lengths are observed differences per position compared, in the same
uncorrected currency as the rest of the site. No substitution model is applied, so a
long branch is a statement about observed difference and nothing more. Negative
branches — which neighbor joining produces routinely, because real distances are not
exactly additive — are clamped to zero and the count is reported on the figure.

Rooting is on Sabin for the poliovirus selections and for `all`, at the midpoint of
that tip's own branch; the reference is forced into the tip set so a panel can never
silently fall back. Non-polio is midpoint-rooted, because it has no member ancestral
to the rest and nominating an outgroup would assert something untrue.

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

I keep this to two toolchains. An earlier plan built `decenttree` from
source for the trees; the implementation in [`pipeline/trees.py`](pipeline/trees.py)
replaced it. Neighbor joining is forty lines of deterministic arithmetic rather than a
heuristic search, and I chose it for two reasons. A fresh clone needs no bioinformatics
toolchain at all. And the trees have to come out the same on every run, which a
multithreaded tool's tie-breaking will not promise. `selftest` asserts both the
exactness (an additive matrix is recovered to 2e-16) and the determinism (identical
trees across runs, including on an all-ties matrix) — and the trees do in fact
reproduce byte for byte across platforms, which the consensus panels do not.

The cost is speed: 2,500 tips take about ten seconds, and forty trees are built per
release, so the tree stage adds a few minutes to a build that is already minutes long.
That is the trade for a step that now runs on every deploy.

## Why the data is built on deploy rather than committed

It used to be committed. Distances are cheap (~30 s for the full 24,038²
masked-Hamming matrix) but forty neighbor joins are not, so the derived artifacts
under `site/data/` were checked in and `ci.yml` ran a hash check that failed if
`final/` had moved since the last build.

That check could not tell a rebuild from a re-stamp. It compared the manifest to
what sat on disk, and refreshing the manifest satisfied it just as well as
regenerating the figures — so editing a pipeline module and re-stamping would
publish stale numbers behind a green tick. The obvious repair, rebuilding in CI and
diffing against what was committed, does not work either: the build is
byte-reproducible on one machine but **not across platforms**. On a Linux runner,
`records.json`, `summary.json`, every tree and the three per-serotype panels
reproduce exactly, while `panels/NPEV.json` and `panels/all.json` do not — the two
panels measured against a consensus computed over the genus-wide alignment, which
points at platform linear algebra rather than logic.

Two builders cannot agree on bytes, so there is one. `pages.yml` builds
`site/data/` from `final/` and publishes what it built; nothing is committed, so
nothing can be stale and there is no `check` subcommand. `ci.yml` runs the same
build on every pull request, then the selftest and the site tests, so a pipeline
break fails before merge rather than at deploy. The workflow also triggers on
`final/**` and `raw/**`, so a data refresh republishes on its own.

The manifest is still written and still ships: it records the SHA-256 of every
`final/` file the build read and of the pipeline sources, so a published page can
be traced to the inputs and code behind it. It documents provenance now instead of
gating staleness.

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

Whether `collection_date` gets normalized to ISO upstream is undecided, and nothing here
rests on the answer: `traits.parse_collection_date` reads both the ISO shapes and the
ones GenBank records verbatim, so the derived decimal year is correct either way. The
record inspector shows both values, the derived one tagged and separately labeled — they
were briefly two rows called "Collection date" with different values, which is worse than
either alone.

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

How large it is, this file no longer says. `summary.consensus_inflation` counts it off
the shipped non-polio polyprotein panel on every build, writes it to
`site/data/summary.json`, and the page renders that. The figure lived here and in
`reference.py` as a hand-copied pair, and was wrong in both from 2.1.5 through 2.4.0 —
the denominator was 13,160 when the panel held 13,161 — because nothing recomputed it.
One measured source beats two prose copies. The records that carry it concentrate in the
largest, most fragmentary types, exactly as the mechanism predicts.

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
